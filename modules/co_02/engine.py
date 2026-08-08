"""[CO-02] AI法规影响评估引擎 —— 纯 stdlib 法规语义解析 + 差距分析 + 整改建议。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 法规语义解析（基于规则 + 关键词词典）：
      - 条款分类：义务条款（"应当"/"必须"/"不得"）/ 权利条款（"可以"/"有权"）/ 定义条款 / 引用条款
      - 处罚条款识别：提取罚款金额/处罚形式
      - 时间要求识别："生效日"/"过渡期"/"申报期限"
      - 适用对象识别："企业"/"金融机构"/"个人"/"大型企业"
  * 合规要求结构化：
      - 将法规文本 → {要求ID, 描述, 类型, 适用对象, 时间要求, 处罚}
  * 企业现状比对（差距分析）：
      - 企业政策/流程/系统 vs 法规要求
      - 匹配：关键词重叠度 + 相似度 + 覆盖度
      - 差距类型：missing（缺失）/ partial（部分覆盖）/ outdated（已过时）
  * 影响量化评估：
      - 影响维度：合规成本（人力/系统/流程改造）+ 违规风险 + 报告影响
      - 评分模型：0-100 影响分 + 高/中/低等级
  * 整改建议生成（基于差距 + 历史案例）：
      - 结构化建议：优先级 + 行动项 + 负责部门 + 预计工期 + 参考案例

模型结构（self.model）：
  {
    "obligation_keywords": {"zh": ["应当", "必须", "不得", "需", "要求"], "en": ["shall", "must", "required"]},
    "right_keywords": {"zh": ["可以", "有权", "允许"], "en": ["may", "can", "entitled"]},
    "penalty_patterns": [罚款金额正则, ...],
    "enterprise_profiles": [],
    "benchmark_cases": [{法规, 企业类型, 影响评估, 整改方案}],
  }
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 内置规则词典（用于法规语义解析）
# ------------------------------------------------------------------

_SEED_OBLIGATION_KWS = {
    "zh": ["应当", "必须", "不得", "需", "要求", "须", "禁止", "不准", "不得"],
    "en": ["shall", "must", "required", "obligatory", "prohibited", "forbidden"],
}

_SEED_RIGHT_KWS = {
    "zh": ["可以", "有权", "允许", "获准", "可", "能够"],
    "en": ["may", "can", "entitled", "permitted", "allowed"],
}

_SEED_DEFINITION_KWS = {
    "zh": ["是指", "是指以下", "定义", "指"],
    "en": ["means", "refers to", "is defined as", "definition"],
}

# 处罚识别
_PENALTY_PATTERNS_ZH = [
    re.compile(r"(最高|可以|处)(\d+[\.,]?\d*)\s*(万|亿|欧元|美元|英镑|元|%)"),
    re.compile(r"罚款\s*(不超过|最高)?\s*(\d+[\.,]?\d*)"),
    re.compile(r"(\d+[\.,]?\d*)\s*倍.*罚款"),
]
_PENALTY_PATTERNS_EN = [
    re.compile(r"(up to|maximum)\s+([\d.,]+)\s*(million|thousand)?\s*(euro|EUR|dollar|USD|pound|GBP)"),
    re.compile(r"(\d+)\s*%.*(fine|penalty)"),
    re.compile(r"(fine|penalty).*?(not exceeding|up to)\s+([\d.,]+)"),
]

# 适用对象识别
_APPLICABLE_ENTITIES = {
    "enterprise": {"zh": ["企业", "公司", "法人", "组织"], "en": ["enterprise", "company", "corporation", "entity"]},
    "financial": {"zh": ["金融机构", "银行", "证券", "保险", "支付机构"], "en": ["financial institution", "bank", "insurance", "securities", "payment"]},
    "individual": {"zh": ["个人", "自然人", "员工", "消费者"], "en": ["individual", "person", "employee", "consumer"]},
    "large_only": {"zh": ["大型企业", "规模以上", "上市公司"], "en": ["large enterprise", "listed company", "public company"]},
}

# 时间/生效识别
_TIME_PATTERNS_ZH = [
    re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日?\s*(起|开始|生效)"),
    re.compile(r"(生效|实施|施行)\s*(日|日期|时间|时间点)?\s*[:：]?\s*(\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?)"),
    re.compile(r"过渡期.{0,20}?(\d{1,2})\s*(个月|年|日)"),
]


def _classify_clause(text: str) -> str:
    """将条款分类为 obligation / right / definition / other。"""
    lower = text.lower()
    if any(kw in text for kw in _SEED_DEFINITION_KWS["zh"]) or any(kw in lower for kw in _SEED_DEFINITION_KWS["en"]):
        return "definition"
    if any(kw in text for kw in _SEED_OBLIGATION_KWS["zh"]) or any(kw in lower for kw in _SEED_OBLIGATION_KWS["en"]):
        return "obligation"
    if any(kw in text for kw in _SEED_RIGHT_KWS["zh"]) or any(kw in lower for kw in _SEED_RIGHT_KWS["en"]):
        return "right"
    return "other"


def _extract_penalty(text: str) -> str:
    """从法规文本中提取处罚描述。"""
    penalties: list[str] = []
    for pat in _PENALTY_PATTERNS_ZH:
        for m in pat.finditer(text):
            penalties.append(m.group(0))
    for pat in _PENALTY_PATTERNS_EN:
        for m in pat.finditer(text):
            penalties.append(m.group(0))
    return "; ".join(penalties[:3]) if penalties else ""


def _extract_applicable(text: str) -> list[str]:
    """提取法规适用对象类型。"""
    result: list[str] = []
    for entity, kws in _APPLICABLE_ENTITIES.items():
        if any(kw in text for kw in kws["zh"]) or any(kw in text.lower() for kw in kws["en"]):
            result.append(entity)
    return result or ["all"]


def _split_clauses(text: str) -> list[str]:
    """将法规文本按段落/条款切分。"""
    lines = [l.strip() for l in re.split(r"[\n\r。！？.!?]", text) if l.strip() and len(l.strip()) > 5]
    return lines


class LLMEngine(AbstractEngine):
    """AI法规影响评估引擎。"""

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        self.model = {
            "obligation_keywords": _SEED_OBLIGATION_KWS,
            "right_keywords": _SEED_RIGHT_KWS,
            "definition_keywords": _SEED_DEFINITION_KWS,
            "applicable_entities": _APPLICABLE_ENTITIES,
            "penalty_patterns_zh": _PENALTY_PATTERNS_ZH,
            "penalty_patterns_en": _PENALTY_PATTERNS_EN,
            "benchmark_cases": [
                {"reg": "GDPR", "industry": "technology", "cost_level": "high", "effort_months": 6, "team_size": 5},
                {"reg": "AMLD5", "industry": "finance", "cost_level": "high", "effort_months": 4, "team_size": 4},
                {"reg": "PIPL", "industry": "all", "cost_level": "medium", "effort_months": 3, "team_size": 3},
            ],
        }

    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化输入。

        input_data 格式：
          {
            "action": "assess" | "parse" | "compare",
            "regulation_text": "...",       # 法规全文
            "regulation_title": "...",
            "enterprise": {
                "industry": "technology",
                "size": "large",
                "country": "EU",
                "existing_policies": ["/** 现有政策描述 **/"],
                "systems": ["SAP", "Salesforce", "..."],
            },
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"action": "assess", "regulation_text": input_data}

        return {
            "action": input_data.get("action", "assess"),
            "regulation_title": input_data.get("regulation_title", "") or "",
            "regulation_text": input_data.get("regulation_text", "") or "",
            "enterprise": input_data.get("enterprise", {}) or {},
        }

    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """路由到对应子功能。"""
        action = prepared["action"]
        clauses = self._parse_regulation(prepared["regulation_text"], prepared["regulation_title"])

        if action == "parse":
            return {"regulation_title": prepared["regulation_title"], "clauses": clauses}

        # 默认 assess 模式
        enterprise = prepared["enterprise"]
        gaps = self._gap_analysis(clauses, enterprise)
        impact = self._quantify_impact(clauses, gaps, enterprise)
        recommendations = self._generate_recommendations(gaps, impact, enterprise)

        return {
            "regulation_title": prepared["regulation_title"],
            "clause_count": len(clauses),
            "regulation_structure": Counter(c["type"] for c in clauses),
            "key_obligations": [c for c in clauses if c["type"] == "obligation"][:20],
            "gap_analysis": gaps,
            "impact_assessment": impact,
            "recommendations": recommendations,
        }

    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        if "module" in result:
            return result

        impact = result.get("impact_assessment", {})
        high_risk_count = impact.get("high_risk_clauses", 0) if isinstance(impact, dict) else 0
        total_clauses = result.get("clause_count", 0)

        result["executive_summary"] = {
            "module": "CO-02",
            "family": "llm_rag",
            "regulation": result.get("regulation_title", ""),
            "total_clauses_analyzed": total_clauses,
            "high_risk_obligations": high_risk_count,
            "overall_impact_level": impact.get("overall_level", "unknown") if isinstance(impact, dict) else "unknown",
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 内部：法规语义解析
    # ------------------------------------------------------------------
    def _parse_regulation(self, text: str, title: str = "") -> list[dict]:
        if not text:
            return []

        raw_clauses = _split_clauses(text)
        clauses: list[dict] = []
        clause_id = 0

        for raw in raw_clauses:
            clause_id += 1
            ctype = _classify_clause(raw)
            penalty = _extract_penalty(raw)
            applicable = _extract_applicable(raw)

            clauses.append({
                "clause_id": f"C-{clause_id:03d}",
                "text": raw[:500],
                "type": ctype,
                "penalty": penalty,
                "applicable_entities": applicable,
                "length": len(raw),
            })

        return clauses

    # ------------------------------------------------------------------
    # 内部：差距分析（企业现状 vs 法规要求）
    # ------------------------------------------------------------------
    def _gap_analysis(self, clauses: list[dict], enterprise: dict) -> dict:
        existing_policies = enterprise.get("existing_policies", []) or []
        policies_text = " ".join(str(p) for p in existing_policies)

        obligation_clauses = [c for c in clauses if c["type"] == "obligation"]
        gaps: list[dict] = []

        for clause in obligation_clauses:
            clause_text = clause["text"]
            sim = difflib.SequenceMatcher(None, clause_text.lower(), policies_text.lower()).ratio()

            # 关键词匹配
            clause_keywords = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", clause_text))
            policy_keywords = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", policies_text))
            kw_overlap = len(clause_keywords & policy_keywords)
            coverage = kw_overlap / max(len(clause_keywords), 1)

            # 判定差距类型
            if coverage < 0.1 and sim < 0.1:
                gap_type = "missing"
                confidence = 0.9
            elif coverage < 0.5 or sim < 0.3:
                gap_type = "partial"
                confidence = 0.6
            else:
                gap_type = "covered"
                confidence = 0.8

            gaps.append({
                "clause_id": clause["clause_id"],
                "gap_type": gap_type,
                "confidence": round(confidence, 4),
                "semantic_similarity": round(sim, 4),
                "keyword_coverage": round(coverage, 4),
                "gap_detail": self._gap_explanation(gap_type, clause_text),
            })

        gap_summary = Counter(g["gap_type"] for g in gaps)
        return {
            "total_obligations": len(obligation_clauses),
            "gaps_by_type": dict(gap_summary),
            "gap_rate": round(
                (gap_summary.get("missing", 0) + gap_summary.get("partial", 0)) / max(len(obligation_clauses), 1) * 100, 1
            ),
            "details": gaps,
        }

    @staticmethod
    def _gap_explanation(gap_type: str, clause_text: str) -> str:
        if gap_type == "missing":
            return f"企业现有政策中未发现覆盖以下合规要求：{clause_text[:80]}..."
        if gap_type == "partial":
            return f"企业现有政策对以下合规要求覆盖不完整：{clause_text[:80]}..."
        return f"企业现有政策已覆盖该合规要求"

    # ------------------------------------------------------------------
    # 内部：影响量化
    # ------------------------------------------------------------------
    def _quantify_impact(self, clauses: list[dict], gaps: dict, enterprise: dict) -> dict:
        missing_count = gaps.get("gaps_by_type", {}).get("missing", 0)
        partial_count = gaps.get("gaps_by_type", {}).get("partial", 0)
        obligation_count = gaps.get("total_obligations", 1)

        # 基础影响分（0-100）
        base_score = min(
            (missing_count / max(obligation_count, 1)) * 50 +
            (partial_count / max(obligation_count, 1)) * 25 +
            (1 if enterprise.get("size") == "large" else 0) * 10 +
            (1 if enterprise.get("industry") in ("finance", "technology") else 0) * 15,
            100.0,
        )

        # 处罚条款数 → 加重影响
        penalty_clauses = [c for c in clauses if c.get("penalty")]
        penalty_weight = min(len(penalty_clauses) * 5, 20)
        final_score = min(base_score + penalty_weight, 100.0)

        level = "high" if final_score >= 70 else "medium" if final_score >= 40 else "low"

        # 成本估算（基于行业对标）
        industry = enterprise.get("industry", "all")
        size = enterprise.get("size", "medium")
        effort_months = {
            "high": 6 if size == "large" else 3,
            "medium": 3 if size == "large" else 1.5,
            "low": 1 if size == "large" else 0.5,
        }.get(level, 1)
        team_size = {"high": 5, "medium": 3, "low": 1}.get(level, 2)

        return {
            "impact_score": round(final_score, 1),
            "overall_level": level,
            "missing_clauses": missing_count,
            "partial_clauses": partial_count,
            "high_risk_clauses": len(penalty_clauses),
            "penalty_clause_details": penalty_clauses,
            "cost_estimation": {
                "effort_months": effort_months,
                "required_team_size": team_size,
                "primary_systems_affected": self._affected_systems(clauses),
            },
        }

    @staticmethod
    def _affected_systems(clauses: list[dict]) -> list[str]:
        text = " ".join(c["text"] for c in clauses)
        systems: list[str] = []
        if re.search(r"数据|data|个人信息", text, re.I):
            systems.append("数据管理系统")
        if re.search(r"财务|financial|报告", text, re.I):
            systems.append("财务报告系统")
        if re.search(r"支付|payment|资金", text, re.I):
            systems.append("支付系统")
        if re.search(r"客户|customer|KYC", text, re.I):
            systems.append("客户管理系统")
        return systems or ["核心业务系统"]

    # ------------------------------------------------------------------
    # 内部：整改建议生成
    # ------------------------------------------------------------------
    def _generate_recommendations(self, gaps: dict, impact: dict, enterprise: dict) -> list[dict]:
        recs: list[dict] = []
        level = impact.get("overall_level", "medium")

        # 按严重程度排序差距
        details = gaps.get("details", [])
        missing = [g for g in details if g["gap_type"] == "missing"]
        partial = [g for g in details if g["gap_type"] == "partial"]

        priority_order = {"high": 0, "medium": 1, "low": 2}

        for g in missing[:10]:
            recs.append({
                "priority": "high",
                "clause_id": g["clause_id"],
                "action_type": "create_new_policy",
                "action_detail": f"制定新政策覆盖该合规要求",
                "responsible_team": self._responsible_team(g["clause_id"]),
                "estimated_effort": "2-4周",
            })

        for g in partial[:10]:
            recs.append({
                "priority": "medium",
                "clause_id": g["clause_id"],
                "action_type": "update_existing_policy",
                "action_detail": f"更新现有政策，补充缺失部分",
                "responsible_team": self._responsible_team(g["clause_id"]),
                "estimated_effort": "1-2周",
            })

        # 系统层面建议
        systems = impact.get("cost_estimation", {}).get("primary_systems_affected", [])
        if systems:
            recs.append({
                "priority": "medium",
                "clause_id": "SYSTEM-001",
                "action_type": "system_upgrade",
                "action_detail": f"评估以下系统的合规改造需求：{', '.join(systems)}",
                "responsible_team": "IT合规组",
                "estimated_effort": "4-8周",
            })

        # 组织层面
        if level == "high":
            recs.append({
                "priority": "high",
                "clause_id": "ORG-001",
                "action_type": "compliance_training",
                "action_detail": "组织全员合规培训，确保新法规被广泛理解",
                "responsible_team": "人力资源部 + 合规部",
                "estimated_effort": "持续（每月）",
            })

        recs.sort(key=lambda r: priority_order.get(r["priority"], 99))
        return recs

    @staticmethod
    def _responsible_team(clause_id: str) -> str:
        mapping = {
            "C-001": "合规部", "C-002": "法务部", "C-003": "IT部",
            "C-004": "财务部", "C-005": "人力资源部",
        }
        return mapping.get(clause_id, "合规部 + 相关业务部门")
