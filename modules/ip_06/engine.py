"""[IP-06] 整改方案AI推荐引擎 —— 问题分类 + 方案匹配 + 效果预估 + 优先级排序。

算法设计（纯 stdlib）：

  * _load_model:
      - 问题分类体系（财务/内控/合规/治理/业务 5 大类 15+ 子类）
      - 方案库（每方案含适用问题/行业/措施/预估工期/成功概率）
      - 优先级权重（问题严重度 30% + 紧迫性 25% + 整改难度 15% + 效果确定性 15% + 依赖关系 15%）
  * _preprocess: 提取 issues 列表，规范化字段
  * _infer:
      ① 为每个 issue 匹配候选方案（类型/行业/严重程度加权匹配）
      ② 效果预估（实施难度 / 成功概率 / 周期 / 成本 / 效果评分）
      ③ 综合评分 → 推荐等级（≥85 强烈推荐，70-84 推荐，50-69 可选）
      ④ 多问题全局优先级排序（依赖关系图 + 综合权重）
  * _postprocess: 返回按优先级排序的方案列表 + 整改路线图 + 统计
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from modules.shared.base_engine import AbstractEngine


ISSUE_CATEGORIES = {
    "财务": ["收入确认", "成本核算", "资产减值", "会计政策", "税务处理"],
    "内控": ["资金管理", "采购内控", "销售内控", "信息系统", "授权审批"],
    "合规": ["税务合规", "环保合规", "劳动合规", "行业监管"],
    "治理": ["关联交易", "资金占用", "三会运作", "董事高管履职"],
    "业务": ["业务模式", "持续经营", "客户依赖", "供应商集中"],
}

SOLUTION_LIBRARY = [
    {"id": "SOL-001", "issue_types": ["收入确认"], "industries": ["软件和信息技术服务业", "制造业", "default"],
     "severity": ["high", "medium"], "actions": ["修订收入确认政策文档", "建立控制权转移判断流程",
     "对销售合同进行模板化改造并明确控制权转移节点", "组织财务和销售团队培训"],
     "duration_days": 30, "success_prob": 0.85, "difficulty": "medium", "cost_level": "low"},
    {"id": "SOL-002", "issue_types": ["资产减值"], "industries": ["制造业", "电子信息制造业", "default"],
     "severity": ["high", "medium"], "actions": ["制定资产减值测试指引", "定期执行减值测试并留存证据",
     "建立可变现净值计算模型", "关注行业价格趋势"],
     "duration_days": 45, "success_prob": 0.80, "difficulty": "medium", "cost_level": "low"},
    {"id": "SOL-003", "issue_types": ["关联交易"], "industries": ["批发和零售业", "制造业", "default"],
     "severity": ["high"], "actions": ["按 CAS 36 号梳理全部关联方", "制定关联交易定价政策并书面化",
     "建立关联交易审批流程（董事会/独立董事审核）", "准备可比交易定价数据"],
     "duration_days": 45, "success_prob": 0.75, "difficulty": "medium", "cost_level": "medium"},
    {"id": "SOL-004", "issue_types": ["资金管理", "资金占用"], "industries": ["default"],
     "severity": ["high"], "actions": ["规范资金归集模式", "杜绝股东/关联方非经营性资金占用",
     "建立资金月度对账机制", "独立董事每季度核查资金占用情况"],
     "duration_days": 30, "success_prob": 0.90, "difficulty": "easy", "cost_level": "low"},
    {"id": "SOL-005", "issue_types": ["客户依赖"], "industries": ["default"],
     "severity": ["medium", "low"], "actions": ["制定客户拓展计划", "明确新客户开发目标",
     "加强销售团队激励", "建立客户结构月度分析机制"],
     "duration_days": 90, "success_prob": 0.55, "difficulty": "high", "cost_level": "medium"},
    {"id": "SOL-006", "issue_types": ["税务合规"], "industries": ["default"],
     "severity": ["high", "medium"], "actions": ["复核税收优惠资质", "与主管税务机关沟通确认",
     "建立税务合规自查机制", "聘请税务顾问定期审计"],
     "duration_days": 30, "success_prob": 0.80, "difficulty": "medium", "cost_level": "medium"},
    {"id": "SOL-007", "issue_types": ["研发费用"], "industries": ["软件和信息技术服务业", "医药制造业"],
     "severity": ["high", "medium"], "actions": ["建立研发项目立项文档模板", "明确资本化/费用化边界并书面化",
     "按项目归集研发费用并留存工时记录", "定期聘请第三方评估研发项目技术可行性"],
     "duration_days": 60, "success_prob": 0.70, "difficulty": "medium", "cost_level": "low"},
    {"id": "SOL-008", "issue_types": ["三会运作", "董事会"], "industries": ["default"],
     "severity": ["medium", "low"], "actions": ["制定董事会/监事会/股东大会运作制度",
     "完善会议记录和决议文件保管", "确保决议程序合法合规"],
     "duration_days": 20, "success_prob": 0.95, "difficulty": "easy", "cost_level": "low"},
]

SEVERITY_WEIGHT = {"critical": 30, "high": 25, "medium": 18, "low": 10}
URGENCY_WEIGHT = {"critical": 25, "high": 22, "medium": 15, "low": 8}


class LLMEngine(AbstractEngine):
    """整改方案 AI 推荐引擎（纯 stdlib：类型匹配 + 效果预估 + 优先级排序）。"""

    def _load_model(self) -> None:
        self.model = {
            "categories": ISSUE_CATEGORIES,
            "solutions": SOLUTION_LIBRARY,
            "severity_weight": SEVERITY_WEIGHT,
            "urgency_weight": URGENCY_WEIGHT,
            "prio_weights": {"severity": 0.30, "urgency": 0.25, "difficulty": 0.15,
                            "certainty": 0.15, "dependency": 0.15},
        }

    def _preprocess(self, input_data: Any) -> Any:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 issues 列表")
        issues = input_data.get("issues", []) or []
        industry = input_data.get("industry", "default")
        norm: list[dict] = []
        for i, issue in enumerate(issues):
            if not isinstance(issue, dict):
                continue
            severity = issue.get("severity", "medium")
            if severity not in ("critical", "high", "medium", "low"):
                severity = "medium"
            urgency = issue.get("urgency", "medium")
            if urgency not in ("critical", "high", "medium", "low"):
                urgency = "medium"
            norm.append({
                "issue_id": issue.get("issue_id", f"ISS-{i + 1:03d}"),
                "issue_type": issue.get("issue_type", ""),
                "issue_desc": issue.get("issue_desc", ""),
                "severity": severity,
                "urgency": urgency,
                "depends_on": issue.get("depends_on", []),
                "raw": issue,
            })
        return {"industry": industry, "issues": norm}

    def _infer(self, prepared: Any) -> Any:
        industry = prepared["industry"]
        issues = prepared["issues"]
        solutions = self.model["solutions"]
        recommended: list[dict] = []
        for issue in issues:
            matched = self._match_solutions(issue, solutions, industry)
            if not matched:
                continue
            top = matched[0]
            score, grade = self._score_solution(issue, top)
            difficulty_penalty = {"easy": 0, "medium": 5, "high": 12}
            duration = top["duration_days"]
            cost_level = top["cost_level"]
            recommended.append({
                "issue_id": issue["issue_id"],
                "issue_type": issue["issue_type"],
                "severity": issue["severity"],
                "solution_id": top["id"],
                "solution_name": f"{top['issue_types'][0]}整改方案",
                "actions": top["actions"],
                "score": score,
                "grade": grade,
                "duration_days": duration,
                "success_prob": top["success_prob"],
                "difficulty": top["difficulty"],
                "cost_level": cost_level,
                "depends_on": issue["depends_on"],
            })

        prioritized = self._priority_sort(recommended)
        roadmap = self._build_roadmap(prioritized)
        return {"solutions": prioritized, "roadmap": roadmap}

    def _match_solutions(self, issue: dict, solutions: list[dict], industry: str) -> list[dict]:
        scored: list[tuple[float, dict]] = []
        itype = issue["issue_type"]
        sev = issue["severity"]
        for s in solutions:
            score = 0.0
            if itype in s["issue_types"]:
                score += 0.45
            else:
                score += 0.1
            if industry in s["industries"] or "default" in s["industries"]:
                score += 0.25
            if sev in s["severity"]:
                score += 0.2
            else:
                score += 0.05
            score += s["success_prob"] * 0.1
            scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    def _score_solution(self, issue: dict, solution: dict) -> tuple[int, str]:
        sev_score = self.model["severity_weight"].get(issue["severity"], 10)
        urgency_score = self.model["urgency_weight"].get(issue["urgency"], 10)
        success = solution["success_prob"] * 100
        difficulty_penalty = {"easy": 0, "medium": 10, "high": 20}[solution["difficulty"]]
        raw = (sev_score * 0.3 + urgency_score * 0.25 + success * 0.3
               + (50 - difficulty_penalty) * 0.15)
        score = int(max(0, min(100, raw)))
        if score >= 85:
            grade = "强烈推荐"
        elif score >= 70:
            grade = "推荐"
        elif score >= 50:
            grade = "可选"
        else:
            grade = "不推荐"
        return score, grade

    def _priority_sort(self, solutions: list[dict]) -> list[dict]:
        deps: dict[str, float] = defaultdict(float)
        for s in solutions:
            for d in s["depends_on"]:
                deps[d] += 1.0
        for s in solutions:
            sev = self.model["severity_weight"].get(s["severity"], 10) / 30
            urg = self.model["urgency_weight"].get(s["issue_type"], 15) / 25
            diff_score = 1.0 if s["difficulty"] == "easy" else (0.6 if s["difficulty"] == "medium" else 0.3)
            certainty = s["success_prob"]
            dep_boost = deps.get(s["issue_id"], 0) / max(len(solutions), 1)
            total = (sev * 0.30 + urg * 0.25 + diff_score * 0.15
                     + certainty * 0.15 + dep_boost * 0.15) * 100
            s["priority_score"] = round(total, 2)
        solutions.sort(key=lambda x: x["priority_score"], reverse=True)
        for i, s in enumerate(solutions, 1):
            s["priority_rank"] = i
            if s["priority_score"] >= 70:
                s["priority_level"] = "高优先级"
            elif s["priority_score"] >= 45:
                s["priority_level"] = "中优先级"
            else:
                s["priority_level"] = "低优先级"
        return solutions

    def _build_roadmap(self, prioritized: list[dict]) -> list[dict]:
        week = 0
        roadmap: list[dict] = []
        for i, s in enumerate(prioritized):
            start_week = week
            end_week = week + max(1, int(math.ceil(s["duration_days"] / 7.0)))
            roadmap.append({
                "issue_id": s["issue_id"],
                "solution_id": s["solution_id"],
                "priority_rank": s["priority_rank"],
                "start_week": start_week + 1,
                "end_week": end_week,
                "duration_days": s["duration_days"],
                "grade": s["grade"],
            })
            week = end_week
        return roadmap

    def _postprocess(self, result: Any) -> Any:
        solutions = result["solutions"]
        total = len(solutions)
        strong = sum(1 for s in solutions if s["grade"] == "强烈推荐")
        rec = sum(1 for s in solutions if s["grade"] == "推荐")
        overall_days = sum(s["duration_days"] for s in solutions)
        result["statistics"] = {
            "total_issues": total,
            "strongly_recommended": strong,
            "recommended": rec,
            "optional": total - strong - rec,
            "total_duration_days": overall_days,
        }
        result["top_actions"] = solutions[:3]
        return result
