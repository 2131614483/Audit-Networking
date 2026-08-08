"""统一输出格式化：数据血缘分析报告。"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    flows = result.get("flows", [])
    cross_border = result.get("cross_border_flows", [])
    stats = result.get("statistics", {})
    upstream = result.get("upstream_impact", {})
    downstream = result.get("downstream_impact", {})
    entities = result.get("entities", {})
    rule_summary = result.get("rule_summary", {})

    # 流详情
    flow_details = []
    for f in flows:
        flow_details.append({
            "src_id": f.get("src_id"),
            "dst_id": f.get("dst_id"),
            "path": f.get("path"),
            "hops": f.get("hops"),
            "is_cross_border": bool(f.get("is_cross_border", 0)),
            "max_sensitive_level": f.get("max_sensitive_level"),
            "risk_score": f.get("risk_score"),
            "risk_level": f.get("risk_level"),
            "compliance_tags": f.get("compliance_tags", []),
            "rule_adjustments": f.get("rule_adjustments", []),
        })

    # 跨境流详情
    cb_details = []
    for cb in cross_border:
        cb_details.append({
            "src_id": cb.get("src_id"),
            "dst_id": cb.get("dst_id"),
            "edge_type": cb.get("edge_type"),
            "src_country": cb.get("src_country"),
            "dst_country": cb.get("dst_country"),
            "sensitive_level": cb.get("sensitive_level"),
            "needs_dpa": cb.get("needs_dpa", False),
            "compliance_action": cb.get("compliance_action", ""),
        })

    return {
        "status": "ok",
        "module": "CO-08",
        "module_name": "知识图谱数据流分析",
        "entities": list(entities.values()) if isinstance(entities, dict) else [],
        "flows": flow_details,
        "cross_border_flows": cb_details,
        "upstream_impact": upstream,
        "downstream_impact": downstream,
        "statistics": {
            "total_entities": stats.get("total_entities", 0),
            "total_flows": stats.get("total_flows", 0),
            "cross_border_count": stats.get("cross_border_count", 0),
            "by_risk_level": stats.get("by_risk_level", {}),
            "high_risk_flows": stats.get("high_risk_flows", 0),
        },
        "rule_summary": rule_summary,
        "compliance_alert": result.get("compliance_alert"),
    }
