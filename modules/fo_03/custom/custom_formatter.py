"""统一输出格式化：舞弊信号检测明细 + 检测汇总。

输出结构：
  {
    "status": "ok",
    "module": "FO-03",
    "detections": [ {doc_id, title, doc_type, risk_score, risk_grade,
                      signal_count, findings, high_risk_flag, investigate,
                      suspicious_hedging, recommendations}, ... ],
    "summary": { document_count, total_signals, high_risk_docs,
                 avg_risk_score, overall_risk_level, risk_grade_distribution,
                 category_counts, rule_flags, thresholds }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    detections = result.get("detections", [])
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}

    # 检测明细表
    details = []
    for det in detections:
        findings = det.get("findings", []) or []
        details.append({
            "doc_id": det.get("doc_id"),
            "title": det.get("title"),
            "doc_type": det.get("doc_type"),
            "risk_score": det.get("risk_score"),
            "risk_grade": det.get("risk_grade", "low"),
            "signal_count": len(findings),
            "findings": findings,
            "high_risk_flag": det.get("high_risk_flag", False),
            "investigate": det.get("investigate", False),
            "suspicious_hedging": det.get("suspicious_hedging", False),
            "recommendations": det.get("recommendations", []),
        })

    # 汇总统计
    output_summary = {
        "document_count": summary.get("document_count", len(detections)),
        "total_signals": summary.get("total_signals", 0),
        "high_risk_docs": summary.get("high_risk_docs", 0),
        "avg_risk_score": summary.get("avg_risk_score", 0.0),
        "overall_risk_level": summary.get("overall_risk_level", "低风险"),
        "risk_grade_distribution": summary.get(
            "risk_grade_distribution", {"high": 0, "medium": 0, "low": 0}
        ),
        "category_counts": summary.get("category_counts", {}),
        "rule_flags": summary.get(
            "rule_flags",
            {"high_risk_flagged": 0, "investigate_flagged": 0, "hedging_flagged": 0},
        ),
        "thresholds": summary.get("thresholds", {}),
    }

    return {
        "status": "ok",
        "module": "FO-03",
        "detections": details,
        "summary": output_summary,
    }
