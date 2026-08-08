"""统一输出格式化：供应商持续风险监控报告（风险评分 / 趋势 / 预警 / 建议）。

输出结构：
  {
    "status": "ok",
    "module": "SC-03",
    "suppliers": [ {supplier_id, name, overall_risk_score, alert_level,
                    risk_tier, metric_analyses, alerts, ...}, ... ],
    "recommendations": [...],
    "statistics": { supplier_count, avg_risk_score, alerts_by_level,
                    risk_tier_distribution, high_risk_suppliers, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外监控报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    suppliers = result.get("suppliers", []) or []
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}

    supplier_reports = []
    for s in suppliers:
        supplier_reports.append({
            "supplier_id": s.get("supplier_id"),
            "name": s.get("name"),
            "overall_risk_score": s.get("overall_risk_score"),
            "alert_level": s.get("alert_level"),
            "risk_tier": s.get("risk_tier"),
            "confirmed_high_risk": s.get("confirmed_high_risk", False),
            "needs_immediate_review": s.get("needs_immediate_review", False),
            "trend_escalated": s.get("trend_escalated", False),
            "critical_alert": s.get("critical_alert", False),
            "metric_analyses": s.get("metric_analyses", {}),
            "alerts": s.get("alerts", []),
            "rule_adjustments": s.get("rule_adjustments", []),
        })

    recommendations = _build_recommendations(suppliers, summary)

    statistics = {
        "supplier_count": summary.get("supplier_count", len(suppliers)),
        "avg_risk_score": summary.get("avg_risk_score", 0.0),
        "alerts_by_level": summary.get("alerts_by_level", {}),
        "risk_tier_distribution": summary.get("risk_tier_distribution", {}),
        "high_risk_suppliers": summary.get("high_risk_suppliers", []),
        "rule_summary": summary.get("rule_summary", {}),
        "thresholds": summary.get("thresholds", {}),
    }

    return {
        "status": "ok",
        "module": "SC-03",
        "suppliers": supplier_reports,
        "recommendations": recommendations,
        "statistics": statistics,
    }


def _build_recommendations(suppliers, summary) -> list[str]:
    """根据监控结果生成审计建议。"""
    recs: list[str] = []
    rule_summary = summary.get("rule_summary", {})
    immediate = rule_summary.get("immediate_review", 0)
    critical = rule_summary.get("critical_alert_triggered", 0)
    trend = rule_summary.get("trend_escalated", 0)

    critical_sups = [s for s in suppliers if s.get("critical_alert")]
    if critical_sups:
        recs.append(
            f"识别到 {len(critical_sups)} 个触发关键告警的供应商，"
            "建议立即启动现场核查与风险处置"
        )
    if immediate:
        recs.append(
            f"识别到 {immediate} 个财务类指标异常供应商，"
            "建议安排专项财务复核"
        )
    if trend:
        recs.append(
            f"识别到 {trend} 个多指标上升趋势供应商，"
            "建议提高监控频率并预制备选供应商"
        )
    high_risk = summary.get("high_risk_suppliers", [])
    if high_risk:
        recs.append(
            f"共 {len(high_risk)} 个高/紧急风险供应商，"
            "建议纳入重点监控名单并设置自动预警阈值"
        )
    avg = summary.get("avg_risk_score", 0.0)
    if avg >= 0.4:
        recs.append(
            f"供应商平均风险得分 {avg} 偏高，建议整体复盘供应商准入与考核机制"
        )
    if not recs:
        recs.append("供应商整体风险可控，建议维持常规监控节奏")
    return recs
