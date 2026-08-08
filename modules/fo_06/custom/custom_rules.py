"""自定义业务规则：证据链质量标记 + 缺失补全建议 + 风险升级。"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """3 条业务规则：
    1) 完整度 < 50 且缺失元素 ≥ 3 → critical_gap（严重证据缺失）
    2) 证据条数 < 3 → insufficient_evidence（证据不足）
    3) 跨案件实体重复 → cross_case_entity（跨案件关联标记）
    """
    if not isinstance(result, dict):
        return result

    chains = result.get("chains", [])
    all_entities = result.get("all_entities", {})

    for c in chains:
        # 规则 1
        if c.get("completeness_score", 0) < 50 and len(c.get("missing_elements", [])) >= 3:
            c["alert"] = {"type": "critical_gap", "action": "需补充关键证据"}
        # 规则 2
        if len(c.get("evidence", [])) < 3:
            c["evidence_alert"] = {"type": "insufficient_evidence", "action": "证据不足，需进一步收集"}

    # 规则 3：跨案件实体
    cross_case = []
    for key, ent in all_entities.items():
        if len(ent.get("cases", [])) >= 2:
            cross_case.append({
                "entity": key,
                "cases": ent["cases"],
                "evidence_count": ent["evidence_count"],
            })
    if cross_case:
        result["cross_case_entities"] = cross_case

    return result
