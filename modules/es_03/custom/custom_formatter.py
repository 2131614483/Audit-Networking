"""统一输出格式化：环境监测报告（ROI 明细 + 告警 + 统计）。

输出结构：
  {
    "status": "ok",
    "module": "ES-03",
    "roi_reports": [ {roi_id, roi_name, impact_score, impact_level,
                      environmental_violation, pollution_alert,
                      changes, anomalies, rule_flags, ...}, ... ],
    "alerts": [ ... ],
    "rule_flags": [ {roi, rule}, ... ],
    "statistics": { roi_count, total_alerts, total_high_severity,
                    greenwashing_suspects, impact_distribution, rule_adjustments }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    roi_reports = result.get("roi_reports", [])
    alerts = result.get("alerts", [])
    summary = result.get("summary", {})

    roi_details = []
    for roi in roi_reports:
        changes = roi.get("changes", [])
        anomalies = roi.get("anomalies", [])
        gw = roi.get("greenwashing_check", {}) or {}
        roi_details.append({
            "roi_id": roi.get("roi_id"),
            "roi_name": roi.get("roi_name"),
            "area_ha": roi.get("area_ha"),
            "industry": roi.get("industry"),
            "impact_score": roi.get("impact_score", 0.0),
            "impact_level": roi.get("impact_level", "normal"),
            "environmental_violation": roi.get("environmental_violation", False),
            "pollution_alert": roi.get("pollution_alert", False),
            "land_use_timeline": [
                {"date": t.get("date"), "land_use": t.get("land_use"),
                 "indices": t.get("indices", {})}
                for t in roi.get("timeline", [])
            ],
            "change_count": len(changes),
            "high_severity_changes": sum(
                1 for c in changes if c.get("severity") == "高"
            ),
            "anomaly_count": len(anomalies),
            "greenwashing_verdict": gw.get("verdict", ""),
            "greenwashing_signal": gw.get("signal", ""),
            "greenwashing_score": gw.get("score", 0.0),
            "changes": changes,
            "anomalies": anomalies,
            "rule_flags": roi.get("rule_flags", []),
        })

    impact_dist = summary.get(
        "impact_distribution", {"normal": 0, "warning": 0, "critical": 0}
    )
    output_stats = {
        "roi_count": summary.get("roi_count", len(roi_reports)),
        "total_alerts": len(alerts),
        "total_high_severity": summary.get("total_high_severity", 0),
        "greenwashing_suspects": summary.get("greenwashing_suspects", 0),
        "impact_distribution": impact_dist,
        "rule_adjustments": summary.get("rule_adjustments", {}),
    }

    return {
        "status": "ok",
        "module": "ES-03",
        "roi_reports": roi_details,
        "alerts": alerts,
        "rule_flags": result.get("rule_flags", []),
        "statistics": output_stats,
    }
