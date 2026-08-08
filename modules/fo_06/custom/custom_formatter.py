"""统一输出格式化：证据链构建报告。"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    chains = result.get("chains", [])
    summary = result.get("summary", {})
    all_entities = result.get("all_entities", {})

    chain_reports = []
    for c in chains:
        chain_reports.append({
            "case_id": c.get("case_id"),
            "case_name": c.get("case_name"),
            "evidence_count": len(c.get("evidence", [])),
            "entity_count": c.get("entity_count", 0),
            "connection_count": c.get("connection_count", 0),
            "chain_complete": c.get("chain_complete", False),
            "completeness_score": c.get("completeness_score", 0),
            "quality_grade": c.get("quality_grade", ""),
            "missing_elements": c.get("missing_elements", []),
            "alert": c.get("alert"),
            "evidence_alert": c.get("evidence_alert"),
            "entities": c.get("entities", []),
            "connections": c.get("connections", []),
        })

    return {
        "status": "ok",
        "module": "FO-06",
        "module_name": "证据链智能构建",
        "chains": chain_reports,
        "all_entities": list(all_entities.values()) if isinstance(all_entities, dict) else [],
        "cross_case_entities": result.get("cross_case_entities", []),
        "summary": {
            "total_evidence": summary.get("total_evidence", 0),
            "total_chains": summary.get("total_chains", 0),
            "total_entities": summary.get("total_entities", 0),
            "avg_evidence_per_chain": summary.get("avg_evidence_per_chain", 0),
            "complete_chains": summary.get("complete_chains", 0),
            "chain_quality": summary.get("chain_quality", ""),
        },
    }
