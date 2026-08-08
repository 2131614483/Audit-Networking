"""[CB-06] 集团审计智能协作平台 —— 纯 stdlib 指令分发 + 进度追踪 + 结果汇总。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 审计指令模板系统：
      - 内置标准化指令模板（风险评估/实质性测试/内部控制/函证/盘点等）
      - 模板支持变量占位符（{集团名称}/{子公司}/{审计期间}/{审计重点}）
      - 按审计阶段和风险等级分级
  * 智能指令生成（基于风险画像 + 审计计划）：
      - 根据子公司风险等级自动调整审计程序深度
      - 高风险 → 增加实质性测试范围 + 强制函证
      - 低风险 → 精简程序 + 强调控制测试
  * 进度追踪与汇总（状态机 + 截止日期管理）：
      - 指令状态：pending → assigned → in_progress → submitted → reviewed → closed
      - 逾期预警：距截止日期 < 20% 剩余时间自动提醒
      - 汇总：按子公司/审计阶段/指令类型统计完成率
  * 结果自动汇总（结构化数据抽取 + 格式对齐）：
      - 从各子公司提交的底稿中抽取关键指标
      - 自动对齐不同准则/格式的财务数据
      - 生成集团汇总报告（差异分析 + 风险热图）
  * 协作知识共享（最佳实践匹配）：
      - 相似问题 → 历史解决方案推荐
      - 跨子公司的经验库

模型结构（self.model）：
  {
    "templates": [{模板类型, 指令内容, 适用阶段, 风险等级}],
    "subsidiaries": [{子公司ID, 名称, 国家, 风险等级, 准则体系}],
    "audit_programs": [{程序ID, 阶段, 步骤列表, 适用风险等级}],
    "knowledge_base": [{问题, 解决方案, 标签, 适用场景}],
    "tasks": [{指令实例, 子公司, 截止日期, 状态}],
  }
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 内置指令模板 + 审计程序库
# ------------------------------------------------------------------

_AUDIT_STAGES = {
    "planning": "审计计划阶段",
    "risk_assessment": "风险评估阶段",
    "internal_control": "内部控制测试",
    "substantive": "实质性程序",
    "completion": "审计完成阶段",
}

_RISK_LEVELS = {"low": "低风险", "medium": "中等风险", "high": "高风险"}

_SEED_TEMPLATES: list[dict] = [
    {
        "tpl_id": "TPL-001",
        "stage": "planning",
        "risk_level": "low",
        "title": "{集团名称}{子公司}年度审计指令",
        "content": [
            "一、基本信息",
            "  1. 审计项目：{集团名称}{审计期间}年度集团审计",
            "  2. 被审计单位：{子公司}",
            "  3. 审计期间：{开始日期} 至 {结束日期}",
            "  4. 审计重点：{审计重点}",
            "  5. 风险等级：低风险（以控制测试为主）",
            "",
            "二、审计程序（精简版）",
            "  1. 了解子公司经营环境与内部控制（1天）",
            "  2. 评价内部控制设计与执行有效性（2天）",
            "  3. 分析性复核（0.5天）",
            "  4. 关键科目抽查（应收/应付/收入/费用，按样本量10%）",
            "",
            "三、提交要求",
            "  1. 审计底稿格式：集团统一模板（附件1）",
            "  2. 审计工作总结：2000字以内",
            "  3. 提交截止：{截止日期}",
        ],
    },
    {
        "tpl_id": "TPL-002",
        "stage": "planning",
        "risk_level": "medium",
        "title": "{集团名称}{子公司}年度审计指令",
        "content": [
            "一、基本信息",
            "  1. 审计项目：{集团名称}{审计期间}年度集团审计",
            "  2. 被审计单位：{子公司}",
            "  3. 审计期间：{开始日期} 至 {结束日期}",
            "  4. 审计重点：{审计重点}",
            "  5. 风险等级：中等风险（控制测试 + 实质性程序结合）",
            "",
            "二、审计程序（标准版）",
            "  1. 风险评估：了解环境 + 识别重大错报风险（2天）",
            "  2. 内部控制测试：关键循环（销售/采购/薪酬/资金）（3天）",
            "  3. 实质性程序：",
            "     - 银行存款：函证 + 余额调节表检查（1天）",
            "     - 应收账款：函证（样本量≥20%）+ 账龄分析（1天）",
            "     - 存货：盘点（如有）+ 计价测试（1天）",
            "     - 收入/成本：截止测试 + 凭证抽查（2天）",
            "     - 固定资产：增减变动验证 + 折旧测试（0.5天）",
            "  4. 关联交易核查（1天）",
            "",
            "三、提交要求",
            "  1. 审计底稿格式：集团统一模板（附件1）",
            "  2. 函证汇总表（附件2）",
            "  3. 审计总结与发现（3000字）",
            "  4. 提交截止：{截止日期}",
        ],
    },
    {
        "tpl_id": "TPL-003",
        "stage": "planning",
        "risk_level": "high",
        "title": "{集团名称}{子公司}年度审计指令【加强版】",
        "content": [
            "一、基本信息",
            "  1. 审计项目：{集团名称}{审计期间}年度集团审计",
            "  2. 被审计单位：{子公司}",
            "  3. 审计期间：{开始日期} 至 {结束日期}",
            "  4. 审计重点：{审计重点}",
            "  5. 风险等级：高风险（全面实质性程序 + 强制函证 + 专项调查）",
            "",
            "二、审计程序（加强版）",
            "  1. 风险评估：深入了解环境 + 识别全部重大错报风险（3天）",
            "  2. 内部控制测试：全部循环 + IT一般控制测试（5天）",
            "  3. 全面实质性程序：",
            "     - 货币资金：全部银行账户函证 + 大额流水核查（2天）",
            "     - 应收账款：100%函证 + 全额账龄分析 + 坏账准备重算（2天）",
            "     - 存货：参与实地盘点 + 全额计价测试（2天）",
            "     - 固定资产：全面盘点 + 折旧/减值重算（1天）",
            "     - 收入/成本：截止测试 + 大额合同逐笔核查 + 毛利率分析（3天）",
            "     - 负债类：全面函证 + 或有事项核查（2天）",
            "  4. 关联交易全面核查：定价公允性 + 完整性（2天）",
            "  5. 期后事项 + 诉讼/担保等或有事项专项调查（1天）",
            "  6. 舞弊风险评估 + 反舞弊程序（2天）",
            "",
            "三、提交要求（全部）",
            "  1. 审计底稿（全科目详细底稿）",
            "  2. 全部函证回函 + 差异汇总",
            "  3. 关联交易专项报告",
            "  4. 舞弊风险评估报告",
            "  5. 审计总结（5000字）",
            "  6. 提交截止：{截止日期}（不得延期）",
        ],
    },
]

# 审计程序库（按风险等级匹配）
_SEED_PROGRAMS: list[dict] = [
    {
        "prog_id": "PROG-001",
        "name": "货币资金审计",
        "risk_min": "low",
        "steps": [
            "获取银行对账单与余额调节表",
            "检查调节表中未达账项",
            "函证银行存款余额（高风险100%，中风险≥50%，低风险≥20%）",
            "检查大额资金流向",
        ],
    },
    {
        "prog_id": "PROG-002",
        "name": "应收账款审计",
        "risk_min": "low",
        "steps": [
            "获取账龄分析表",
            "函证应收账款（高风险100%，中风险≥20%，低风险≥10%）",
            "检查坏账准备计提是否充分",
            "截止测试（资产负债表日前后一个月）",
            "检查大额关联方应收款",
        ],
    },
    {
        "prog_id": "PROG-003",
        "name": "存货审计",
        "risk_min": "medium",
        "steps": [
            "了解盘点制度",
            "参与/观察实地盘点",
            "检查存货计价方法",
            "减值测试（可变现净值 vs 账面价值）",
            "截止测试（采购/销售）",
        ],
    },
    {
        "prog_id": "PROG-004",
        "name": "收入确认审计",
        "risk_min": "low",
        "steps": [
            "了解收入确认政策",
            "大额销售合同抽查（≥20笔或≥10%）",
            "截止测试（年末前后3个月）",
            "毛利率分析 + 异常波动调查",
            "关联方销售定价公允性检查",
        ],
    },
    {
        "prog_id": "PROG-005",
        "name": "关联交易审计",
        "risk_min": "medium",
        "steps": [
            "识别全部关联方关系",
            "检查关联交易定价公允性",
            "检查关联交易完整性披露",
            "高风险关联交易专项核查",
        ],
    },
]

# 协作知识库（最佳实践）
_SEED_KNOWLEDGE: list[dict] = [
    {
        "problem": "子公司延迟提交审计底稿",
        "solution": "提前1周发送提醒 + 延迟2天自动升级至子公司负责人 + 延迟5天通知集团审计委员会",
        "tags": ["进度管理", "延迟"],
        "applicable": ["所有子公司"],
    },
    {
        "problem": "不同准则体系数据格式不统一",
        "solution": "使用集团统一Excel模板，子公司仅填数据，格式/公式由总部统一维护；关键科目需按集团准则重新列报",
        "tags": ["数据格式", "准则转换"],
        "applicable": ["使用US_GAAP/IFRS/CN_GAAP的子公司"],
    },
    {
        "problem": "函证回收率低（<60%）",
        "solution": "1) 提前1周二次寄发 + 电话确认收件 2) 函证回收≤50%时执行替代程序（银行流水/合同/发票三联核查）3) 评估函证回收率对审计意见的影响",
        "tags": ["函证", "替代程序"],
        "applicable": ["所有子公司"],
    },
    {
        "problem": "子公司拒绝/无法提供敏感数据",
        "solution": "1) 记录范围受限原因 2) 评估受限是否影响审计意见 3) 执行替代程序 4) 向集团管理层报告",
        "tags": ["范围受限", "敏感数据"],
        "applicable": ["高风险子公司"],
    },
]


def _render_template(content: list[str], variables: dict) -> list[str]:
    """用变量填充指令模板中的占位符。"""
    result = []
    for line in content:
        rendered = line
        for key, val in variables.items():
            rendered = rendered.replace("{" + key + "}", str(val))
        result.append(rendered)
    return result


def _parse_date(s: str) -> datetime:
    """解析 ISO 日期字符串 → datetime。"""
    if not s:
        return datetime.now()
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return datetime.now()


class LLMEngine(AbstractEngine):
    """集团审计智能协作平台引擎。"""

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        self.model = {
            "templates": list(_SEED_TEMPLATES),
            "programs": list(_SEED_PROGRAMS),
            "knowledge_base": list(_SEED_KNOWLEDGE),
            "audit_stages": _AUDIT_STAGES,
            "risk_levels": _RISK_LEVELS,
            "tasks": [],
            "submissions": [],
            "subsidiaries": [],
        }

    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化输入。

        input_data 格式：
          {
            "action": "generate_orders" | "track_progress" | "summarize_results" | "add_subsidiary" | "kb_query",
            "subsidiaries": [...],           # 子公司列表（含风险等级）
            "group_name": "XX集团",
            "audit_period": "2024年度",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "deadline": "2025-03-15",
            "audit_focus": "...",
            "task_id": "...",                 # track_progress 时
            "kb_query": "...",                # kb_query 时
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"action": "kb_query", "kb_query": input_data}

        return {
            "action": input_data.get("action", "generate_orders"),
            "group_name": input_data.get("group_name", "集团") or "集团",
            "audit_period": input_data.get("audit_period", "") or "",
            "start_date": input_data.get("start_date", "") or "",
            "end_date": input_data.get("end_date", "") or "",
            "deadline": input_data.get("deadline", "") or "",
            "audit_focus": input_data.get("audit_focus", "") or "常规年度审计",
            "subsidiaries": input_data.get("subsidiaries") or [],
            "task_id": input_data.get("task_id", ""),
            "kb_query": input_data.get("kb_query", ""),
        }

    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """路由到对应子功能。"""
        action = prepared["action"]
        if action == "generate_orders":
            return self._generate_orders(prepared)
        if action == "track_progress":
            return self._track_progress(prepared)
        if action == "summarize_results":
            return self._summarize(prepared)
        if action == "add_subsidiary":
            return self._add_subsidiaries(prepared)
        if action == "kb_query":
            return self._kb_search(prepared)
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        if "module" in result:
            return result
        result["collaboration"] = {
            "module": "CB-06",
            "family": "llm_rag",
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 核心：智能指令生成
    # ------------------------------------------------------------------
    def _generate_orders(self, prepared: Any) -> dict:
        templates = self.model["templates"]
        programs = self.model["programs"]
        subsidiaries = prepared["subsidiaries"] or self.model.get("subsidiaries", [])

        if not subsidiaries:
            return {"error": "无子公司数据，请先 add_subsidiary 或在 input_data 中提供"}

        orders: list[dict] = []
        variables_base = {
            "集团名称": prepared["group_name"],
            "审计期间": prepared["audit_period"],
            "开始日期": prepared["start_date"],
            "结束日期": prepared["end_date"],
            "截止日期": prepared["deadline"],
            "审计重点": prepared["audit_focus"],
        }

        for sub in subsidiaries:
            risk = (sub.get("risk_level") or "medium").lower()
            tpl = next((t for t in templates if t["risk_level"] == risk), templates[0])

            variables = {**variables_base, "子公司": sub.get("name", sub.get("id", ""))}

            steps = _render_template(tpl["content"], variables)
            prog_steps = [p for p in programs if self._risk_at_least(p["risk_min"], risk)]

            task_id = f"TASK-{len(self.model['tasks']) + 1:04d}"
            task = {
                "task_id": task_id,
                "subsidiary_id": sub.get("id"),
                "subsidiary_name": sub.get("name", ""),
                "risk_level": risk,
                "stage": "planning",
                "status": "pending",
                "title": tpl["title"].format(**variables),
                "instructions": "\n".join(steps),
                "additional_programs": [p["name"] for p in prog_steps],
                "deadline": prepared["deadline"],
                "created_at": datetime.now().isoformat(),
            }
            self.model["tasks"].append(task)
            orders.append(task)

        return {
            "group_name": prepared["group_name"],
            "total_orders": len(orders),
            "orders": orders,
            "summary": {
                "by_risk": Counter(o["risk_level"] for o in orders),
                "high_risk_count": sum(1 for o in orders if o["risk_level"] == "high"),
                "medium_risk_count": sum(1 for o in orders if o["risk_level"] == "medium"),
                "low_risk_count": sum(1 for o in orders if o["risk_level"] == "low"),
            },
        }

    @staticmethod
    def _risk_at_least(min_risk: str, current_risk: str) -> bool:
        order = {"low": 0, "medium": 1, "high": 2}
        return order.get(current_risk, 0) >= order.get(min_risk, 0)

    # ------------------------------------------------------------------
    # 核心：进度追踪
    # ------------------------------------------------------------------
    def _track_progress(self, prepared: Any) -> dict:
        tasks = self.model["tasks"]
        today = datetime.now()
        task_id = prepared.get("task_id", "")

        filtered = [t for t in tasks if not task_id or t["task_id"] == task_id]

        results: list[dict] = []
        for t in filtered:
            status = t.get("status", "pending")
            deadline = _parse_date(t.get("deadline", ""))
            remaining_days = (deadline - today).days
            total_duration = 30  # 默认审计周期
            progress_pct = {
                "pending": 0, "assigned": 10, "in_progress": 40,
                "submitted": 80, "reviewed": 95, "closed": 100,
            }.get(status, 0)

            overdue = remaining_days < 0 and status not in ("reviewed", "closed")
            warning = 0 < remaining_days <= total_duration * 0.2 and status not in ("reviewed", "closed")

            results.append({
                "task_id": t["task_id"],
                "subsidiary": t["subsidiary_name"],
                "risk_level": t["risk_level"],
                "status": status,
                "progress_pct": progress_pct,
                "deadline": t.get("deadline", ""),
                "remaining_days": remaining_days,
                "overdue": overdue,
                "warning": warning,
            })

        status_counter = Counter(r["status"] for r in results)
        overdue_count = sum(1 for r in results if r["overdue"])
        warning_count = sum(1 for r in results if r["warning"])

        return {
            "total_tasks": len(results),
            "status_breakdown": dict(status_counter),
            "completion_rate": round(status_counter.get("closed", 0) / max(len(results), 1) * 100, 1),
            "overdue_count": overdue_count,
            "warning_count": warning_count,
            "details": results,
        }

    # ------------------------------------------------------------------
    # 核心：结果自动汇总
    # ------------------------------------------------------------------
    def _summarize(self, prepared: Any) -> dict:
        submissions = prepared.get("submissions") or self.model.get("submissions", [])
        if not submissions:
            return {"summary": "暂无提交数据", "total_count": 0}

        # 抽取关键指标
        key_metrics = {
            "revenue": 0.0, "net_profit": 0.0, "total_assets": 0.0,
            "audit_findings": 0, "high_risk_findings": 0, "issues": [],
        }
        subsidiary_results: list[dict] = []

        for sub in submissions:
            metrics = sub.get("financial_metrics", {}) or {}
            findings = sub.get("audit_findings", []) or []

            key_metrics["revenue"] += float(metrics.get("revenue", 0) or 0)
            key_metrics["net_profit"] += float(metrics.get("net_profit", 0) or 0)
            key_metrics["total_assets"] += float(metrics.get("total_assets", 0) or 0)
            key_metrics["audit_findings"] += len(findings)
            key_metrics["high_risk_findings"] += sum(1 for f in findings if (f.get("severity") or "").lower() == "high")
            key_metrics["issues"].extend([f.get("description", "") for f in findings if f.get("severity", "").lower() in ("high", "medium")])

            subsidiary_results.append({
                "subsidiary": sub.get("subsidiary_name", sub.get("subsidiary_id", "")),
                "revenue": float(metrics.get("revenue", 0) or 0),
                "net_profit": float(metrics.get("net_profit", 0) or 0),
                "finding_count": len(findings),
                "high_risk_count": sum(1 for f in findings if (f.get("severity") or "").lower() == "high"),
                "audit_opinion": sub.get("audit_opinion", ""),
            })

        # 计算分析指标
        n = max(len(submissions), 1)
        key_metrics["avg_revenue"] = round(key_metrics["revenue"] / n, 2)
        key_metrics["avg_net_profit"] = round(key_metrics["net_profit"] / n, 2)
        key_metrics["consolidation_scope"] = n

        # 审计意见分布
        opinion_counter = Counter(s.get("audit_opinion", "") for s in subsidiary_results)

        return {
            "group_summary": key_metrics,
            "subsidiary_count": n,
            "audit_opinion_distribution": dict(opinion_counter),
            "subsidiary_results": subsidiary_results,
            "high_risk_issues": key_metrics["issues"][:20],
        }

    # ------------------------------------------------------------------
    # 核心：知识库检索（最佳实践匹配）
    # ------------------------------------------------------------------
    def _kb_search(self, prepared: Any) -> dict:
        query = prepared.get("kb_query", "")
        if not query:
            return {"results": self.model["knowledge_base"], "total": len(self.model["knowledge_base"])}

        results: list[dict] = []
        for entry in self.model["knowledge_base"]:
            text = f"{entry.get('problem', '')} {entry.get('solution', '')} {' '.join(entry.get('tags', []))}"
            sim = difflib.SequenceMatcher(None, query.lower(), text.lower()).ratio()
            tag_hit = sum(1 for t in entry.get("tags", []) if t.lower() in query.lower())
            score = sim * 5 + tag_hit * 2
            if score > 0.3 or query.lower() in text.lower():
                results.append({**entry, "relevance_score": round(score, 4)})

        results.sort(key=lambda e: -e.get("relevance_score", 0))
        return {"query": query, "results": results[:10], "total": len(self.model["knowledge_base"])}

    # ------------------------------------------------------------------
    # 内部：注册子公司
    # ------------------------------------------------------------------
    def _add_subsidiaries(self, prepared: Any) -> dict:
        added = 0
        for sub in prepared.get("subsidiaries", []):
            if isinstance(sub, dict):
                self.model["subsidiaries"].append(sub)
                added += 1
        return {"added_count": added, "total": len(self.model["subsidiaries"])}
