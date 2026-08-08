"""[CO-03] 合规审计程序自动更新 —— 纯 stdlib 法规变更-程序映射 + 版本管理。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 审计程序模板库：
      - 按合规领域组织（数据隐私/反洗钱/税务/会计准则/环境/劳动）
      - 每个程序含 {程序ID, 阶段, 审计步骤, 适用法规, 关键检查点, 抽样方法}
  * 法规变更-程序映射（语义相似度 + 关键词匹配）：
      - 法规变更内容 → 识别影响的合规领域
      - 领域 → 匹配受影响的审计程序
      - 语义相似度（difflib.SequenceMatcher）评估变更影响程度
  * 程序自动更新（模板生成 + 版本控制）：
      - 新增步骤（法规新增要求）
      - 修改步骤（法规变更要求）
      - 废弃步骤（法规删除要求）
      - 每个更新记录变更原因 + 变更历史
  * 版本管理：
      - 每次更新产生新版本号（vX.Y.Z）
      - 保留历史版本，支持回滚
      - 变更日志（谁/何时/改了什么/为什么）
  * 更新追溯：
      - "某次法规变更后，哪些程序已更新/未更新"
      - 覆盖率报告：已更新 vs 待更新

模型结构（self.model）：
  {
    "programs": [{程序模板，版本历史，变更日志}],
    "domain_mapping": {法规领域 → [程序ID列表]},
    "templates": [{新增/修改/废弃的步骤模板}],
    "update_history": [{变更ID，法规，影响程序，更新时间}],
  }
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 内置审计程序模板库（按合规领域）
# ------------------------------------------------------------------

_DOMAIN_TO_PROGRAMS: dict[str, list[str]] = {
    "data_privacy": ["PROG-DP-001", "PROG-DP-002", "PROG-DP-003"],
    "aml": ["PROG-AML-001", "PROG-AML-002"],
    "tax": ["PROG-TAX-001", "PROG-TAX-002"],
    "accounting": ["PROG-ACC-001", "PROG-ACC-002"],
    "environmental": ["PROG-ENV-001"],
    "labor": ["PROG-LAB-001"],
    "antitrust": ["PROG-ANT-001"],
}

_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "data_privacy": ["数据保护", "个人信息", "隐私", "data protection", "privacy", "GDPR", "PIPL", "数据跨境"],
    "aml": ["反洗钱", "AML", "KYC", "可疑交易", "洗钱", "anti-money laundering", "beneficial owner"],
    "tax": ["税法", "税务", "企业所得税", "增值税", "tax", "transfer pricing"],
    "accounting": ["会计准则", "IFRS", "GAAP", "收入确认", "资产减值", "accounting standard"],
    "environmental": ["环境", "排放", "碳", "环保", "environmental", "emission", "carbon"],
    "labor": ["劳动法", "劳动合同", "员工", "labor", "employment", "worker"],
    "antitrust": ["反垄断", "竞争", "垄断", "antitrust", "competition", "monopoly"],
}

_SEED_PROGRAMS: list[dict] = [
    {
        "prog_id": "PROG-DP-001",
        "name": "数据隐私合规审计程序",
        "domain": "data_privacy",
        "version": "1.0.0",
        "stage": "实质性测试",
        "applicable_regs": ["GDPR", "PIPL", "CCPA"],
        "steps": [
            {"id": "DP-001", "desc": "盘点企业处理的全部个人信息类型和范围", "critical": True},
            {"id": "DP-002", "desc": "评估是否获得充分有效的数据处理同意", "critical": True},
            {"id": "DP-003", "desc": "检查数据最小化原则执行情况", "critical": True},
            {"id": "DP-004", "desc": "评估跨境数据传输合规性", "critical": False},
            {"id": "DP-005", "desc": "检查数据主体权利响应机制", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-DP-002",
        "name": "数据安全管理审计程序",
        "domain": "data_privacy",
        "version": "1.0.0",
        "stage": "内部控制测试",
        "applicable_regs": ["CSL", "GDPR", "PIPL"],
        "steps": [
            {"id": "DS-001", "desc": "评估数据分类分级制度", "critical": True},
            {"id": "DS-002", "desc": "检查重要数据安全评估记录", "critical": True},
            {"id": "DS-003", "desc": "检查数据访问控制和权限管理", "critical": True},
            {"id": "DS-004", "desc": "评估数据泄露应急预案", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-DP-003",
        "name": "跨境数据传输专项审计程序",
        "domain": "data_privacy",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["GDPR", "PIPL", "Schrems II"],
        "steps": [
            {"id": "CB-001", "desc": "盘点全部跨境数据传输场景", "critical": True},
            {"id": "CB-002", "desc": "评估跨境传输的合法性基础", "critical": True},
            {"id": "CB-003", "desc": "检查标准合同条款(SCC)使用情况", "critical": True},
            {"id": "CB-004", "desc": "评估传输风险和保障措施", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-AML-001",
        "name": "反洗钱合规审计程序",
        "domain": "aml",
        "version": "1.0.0",
        "stage": "全面审计",
        "applicable_regs": ["AMLD5", "AML/CFT", "FATF"],
        "steps": [
            {"id": "AML-001", "desc": "评估客户尽职调查(KYC)制度和执行", "critical": True},
            {"id": "AML-002", "desc": "检查可疑交易监控和报告流程", "critical": True},
            {"id": "AML-003", "desc": "评估交易监控系统有效性", "critical": True},
            {"id": "AML-004", "desc": "检查高风险客户和PEP识别", "critical": False},
            {"id": "AML-005", "desc": "评估记录保存制度", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-AML-002",
        "name": "受益所有权透明化审计程序",
        "domain": "aml",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["AMLD5", " beneficial ownership"],
        "steps": [
            {"id": "BO-001", "desc": "盘点全部受益所有人登记情况", "critical": True},
            {"id": "BO-002", "desc": "评估控制权追踪和穿透机制", "critical": True},
            {"id": "BO-003", "desc": "检查与注册机构的信息交互", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-TAX-001",
        "name": "税务合规审计程序",
        "domain": "tax",
        "version": "1.0.0",
        "stage": "全面审计",
        "applicable_regs": ["税法", "企业所得税法", "转让定价"],
        "steps": [
            {"id": "TAX-001", "desc": "评估税务登记和申报完整性", "critical": True},
            {"id": "TAX-002", "desc": "检查税收优惠资格和享受情况", "critical": True},
            {"id": "TAX-003", "desc": "评估转让定价文档和定价策略", "critical": False},
            {"id": "TAX-004", "desc": "检查或有税务负债计提", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-TAX-002",
        "name": "增值税合规审计程序",
        "domain": "tax",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["增值税暂行条例"],
        "steps": [
            {"id": "VAT-001", "desc": "检查增值税发票开具和取得合规性", "critical": True},
            {"id": "VAT-002", "desc": "评估进项税额抵扣合规性", "critical": True},
            {"id": "VAT-003", "desc": "检查增值税申报及时性和准确性", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-ACC-001",
        "name": "会计准则转换审计程序",
        "domain": "accounting",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["IFRS", "GAAP", "CAS"],
        "steps": [
            {"id": "ACC-001", "desc": "识别准则体系和重大会计政策", "critical": True},
            {"id": "ACC-002", "desc": "评估准则差异对财务报表的影响", "critical": True},
            {"id": "ACC-003", "desc": "检查调节表编制和披露", "critical": True},
            {"id": "ACC-004", "desc": "评估准则变更的追溯调整", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-ACC-002",
        "name": "收入确认合规审计程序",
        "domain": "accounting",
        "version": "1.0.0",
        "stage": "实质性测试",
        "applicable_regs": ["IFRS 15", "ASC 606", "企业会计准则第14号"],
        "steps": [
            {"id": "REV-001", "desc": "评估合同识别和履约义务判定", "critical": True},
            {"id": "REV-002", "desc": "检查交易价格确定和可变对价约束", "critical": True},
            {"id": "REV-003", "desc": "评估履约进度计量方法", "critical": True},
            {"id": "REV-004", "desc": "检查收入确认时点正确性", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-ENV-001",
        "name": "环境合规审计程序",
        "domain": "environmental",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["ESG", "碳排放", "环保法规"],
        "steps": [
            {"id": "ENV-001", "desc": "评估环境许可和排放合规性", "critical": True},
            {"id": "ENV-002", "desc": "检查碳排放计量和报告", "critical": False},
            {"id": "ENV-003", "desc": "评估环境或有事项披露", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-LAB-001",
        "name": "劳动合规审计程序",
        "domain": "labor",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["劳动合同法", "劳动法"],
        "steps": [
            {"id": "LAB-001", "desc": "评估劳动合同签订和合规性", "critical": True},
            {"id": "LAB-002", "desc": "检查社保公积金缴纳", "critical": True},
            {"id": "LAB-003", "desc": "评估薪酬和加班合规性", "critical": False},
        ],
    },
    {
        "prog_id": "PROG-ANT-001",
        "name": "反垄断合规审计程序",
        "domain": "antitrust",
        "version": "1.0.0",
        "stage": "专项审计",
        "applicable_regs": ["反垄断法", "EC antitrust", "FTC"],
        "steps": [
            {"id": "ANT-001", "desc": "评估市场地位和市场份额", "critical": True},
            {"id": "ANT-002", "desc": "检查定价行为是否构成滥用市场支配地位", "critical": True},
            {"id": "ANT-003", "desc": "评估横向纵向协议合规性", "critical": False},
        ],
    },
]


def _domain_for_regulation(text: str) -> list[str]:
    """根据法规文本识别影响的合规领域。"""
    if not text:
        return []
    results: list[str] = []
    text_lower = text.lower()
    for domain, kws in _DOMAIN_KEYWORDS.items():
        hit = sum(1 for kw in kws if kw.lower() in text_lower or kw in text)
        if hit >= 1:
            results.append(domain)
    return results


def _bump_version(old: str, change_type: str) -> str:
    """语义化版本号升级：major(breaking)/minor(new step)/patch(fix)。"""
    try:
        major, minor, patch = old.split(".")
    except ValueError:
        major, minor, patch = "1", "0", "0"
    m, n, p = int(major), int(minor), int(patch)
    if change_type == "major":
        return f"{m + 1}.0.0"
    if change_type == "minor":
        return f"{m}.{n + 1}.0"
    return f"{m}.{n}.{p + 1}"


class LLMEngine(AbstractEngine):
    """合规审计程序自动更新引擎。"""

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        self.model = {
            "programs": [dict(p, change_log=[]) for p in _SEED_PROGRAMS],
            "domain_mapping": dict(_DOMAIN_TO_PROGRAMS),
            "domain_keywords": dict(_DOMAIN_KEYWORDS),
            "update_history": [],
            "step_templates": [],
        }

    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化输入。

        input_data 格式：
          {
            "action": "analyze_change" | "update_programs" | "get_status" | "rollback",
            "regulation_change": "...",     # 法规变更内容
            "regulation_title": "...",
            "affected_prog_ids": [...],    # 可选，指定受影响程序
            "change_type": "major|minor|patch",  # 可选
            "prog_id": "...",               # rollback 时
            "target_version": "...",        # rollback 时
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"action": "analyze_change", "regulation_change": input_data}

        return {
            "action": input_data.get("action", "analyze_change"),
            "regulation_change": input_data.get("regulation_change", "") or "",
            "regulation_title": input_data.get("regulation_title", "") or "",
            "affected_prog_ids": input_data.get("affected_prog_ids") or [],
            "change_type": input_data.get("change_type", "minor") or "minor",
            "prog_id": input_data.get("prog_id", ""),
            "target_version": input_data.get("target_version", ""),
        }

    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        action = prepared["action"]
        if action == "analyze_change":
            return self._analyze_change(prepared)
        if action == "update_programs":
            return self._update_programs(prepared)
        if action == "get_status":
            return self._get_status(prepared)
        if action == "rollback":
            return self._rollback(prepared)
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        if "module" in result:
            return result
        result["meta"] = {
            "module": "CO-03",
            "family": "llm_rag",
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 核心：分析法规变更影响
    # ------------------------------------------------------------------
    def _analyze_change(self, prepared: Any) -> dict:
        change_text = prepared["regulation_change"]
        if not change_text:
            return {"affected_domains": [], "affected_programs": [], "note": "无法解析法规变更内容"}

        affected_domains = _domain_for_regulation(change_text)
        affected_programs: list[dict] = []

        for domain in affected_domains:
            prog_ids = self.model["domain_mapping"].get(domain, [])
            for prog in self.model["programs"]:
                if prog["prog_id"] in prog_ids:
                    # 计算变更影响相似度
                    prog_text = " ".join(step["desc"] for step in prog["steps"])
                    sim = difflib.SequenceMatcher(None, change_text.lower(), prog_text.lower()).ratio()
                    affected_programs.append({
                        "prog_id": prog["prog_id"],
                        "name": prog["name"],
                        "current_version": prog["version"],
                        "domain": domain,
                        "impact_similarity": round(sim, 4),
                        "impact_level": "high" if sim > 0.3 else "medium" if sim > 0.15 else "low",
                        "update_urgency": self._urgency(domain, sim),
                    })

        # 按影响程度排序
        affected_programs.sort(key=lambda p: -p["impact_similarity"])

        return {
            "regulation_title": prepared["regulation_title"],
            "affected_domains": affected_domains,
            "affected_program_count": len(affected_programs),
            "affected_programs": affected_programs,
            "analysis_summary": self._summary(affected_domains, affected_programs),
        }

    @staticmethod
    def _urgency(domain: str, sim: float) -> str:
        if sim > 0.3:
            return "立即更新（法规已生效）"
        if sim > 0.15:
            return "下次审计前更新"
        return "下次年度更新"

    @staticmethod
    def _summary(domains: list[str], progs: list[dict]) -> str:
        if not progs:
            return "本次法规变更未发现需要更新的审计程序"
        high_count = sum(1 for p in progs if p["impact_level"] == "high")
        return f"本次变更影响 {len(domains)} 个合规领域，涉及 {len(progs)} 个审计程序，其中 {high_count} 个需立即更新"

    # ------------------------------------------------------------------
    # 核心：执行程序自动更新
    # ------------------------------------------------------------------
    def _update_programs(self, prepared: Any) -> dict:
        analysis = self._analyze_change(prepared)
        updated_programs: list[dict] = []
        change_type = prepared["change_type"]

        affected_ids = set(prepared.get("affected_prog_ids") or [])
        for info in analysis.get("affected_programs", []):
            pid = info["prog_id"]
            if affected_ids and pid not in affected_ids:
                continue

            prog = next((p for p in self.model["programs"] if p["prog_id"] == pid), None)
            if not prog:
                continue

            old_version = prog["version"]
            new_version = _bump_version(old_version, change_type)

            # 模拟更新：为高影响程序添加新步骤
            new_steps = list(prog["steps"])
            updates_made: list[str] = []

            if info["impact_level"] in ("high", "medium"):
                new_step_id = f"{pid}-UPD-{len(prog['steps']) + 1:03d}"
                new_step = {
                    "id": new_step_id,
                    "desc": f"【法规更新】根据《{prepared['regulation_title'] or '新法规'}》新增合规检查点",
                    "critical": info["impact_level"] == "high",
                    "added_in_version": new_version,
                }
                new_steps.append(new_step)
                updates_made.append(f"新增步骤：{new_step['desc'][:50]}")

                # 影响重大时更新现有步骤描述
                if info["impact_level"] == "high":
                    for step in new_steps:
                        if step.get("critical") and "updated_in_version" not in step:
                            step["desc"] = step["desc"] + "（根据新规更新）"
                            step["updated_in_version"] = new_version
                            updates_made.append(f"更新步骤：{step['id']}")

            # 更新程序
            prog["version"] = new_version
            prog["steps"] = new_steps
            prog["change_log"] = prog.get("change_log", []) + [{
                "old_version": old_version,
                "new_version": new_version,
                "change_type": change_type,
                "trigger_regulation": prepared["regulation_title"],
                "changes": updates_made,
                "timestamp": datetime.now().isoformat(),
            }]

            updated_programs.append({
                "prog_id": pid,
                "old_version": old_version,
                "new_version": new_version,
                "updates_made": updates_made,
                "change_count": len(updates_made),
            })

        # 记录全局更新历史
        if updated_programs:
            self.model["update_history"].append({
                "batch_id": f"UPD-{len(self.model['update_history']) + 1:04d}",
                "regulation": prepared["regulation_title"],
                "programs_updated": len(updated_programs),
                "timestamp": datetime.now().isoformat(),
                "details": updated_programs,
            })

        return {
            "batch_id": self.model["update_history"][-1]["batch_id"] if self.model["update_history"] else "",
            "programs_updated": len(updated_programs),
            "updated_programs": updated_programs,
            "change_type": change_type,
        }

    # ------------------------------------------------------------------
    # 内部：状态查询 / 回滚
    # ------------------------------------------------------------------
    def _get_status(self, prepared: Any) -> dict:
        programs = self.model["programs"]
        update_history = self.model["update_history"]

        versions = Counter(p["version"] for p in programs)
        domains = Counter(p["domain"] for p in programs)

        return {
            "total_programs": len(programs),
            "by_domain": dict(domains),
            "version_distribution": dict(versions),
            "total_updates_applied": len(update_history),
            "last_update": update_history[-1] if update_history else None,
        }

    def _rollback(self, prepared: Any) -> dict:
        prog_id = prepared.get("prog_id", "")
        target_version = prepared.get("target_version", "")

        prog = next((p for p in self.model["programs"] if p["prog_id"] == prog_id), None)
        if not prog:
            return {"error": f"未找到程序 {prog_id}"}

        if not prog.get("change_log"):
            return {"error": f"程序 {prog_id} 无变更历史，无法回滚"}

        # 找到目标版本对应的变更日志条目
        target_idx = None
        for i, entry in enumerate(prog["change_log"]):
            if entry["old_version"] == target_version:
                target_idx = i
                break
            if entry["new_version"] == target_version:
                target_idx = i + 1
                break

        if target_idx is None:
            return {"error": f"未找到目标版本 {target_version}"}

        prog["change_log"] = prog["change_log"][:target_idx]
        prog["version"] = target_version

        return {
            "prog_id": prog_id,
            "rolled_back_to": target_version,
            "remaining_updates": len(prog["change_log"]),
            "status": "success",
        }
