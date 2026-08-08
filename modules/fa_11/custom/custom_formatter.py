"""统一输出格式化：交易明细 + 公允性评估 + 偏离分析 + 调整建议。

输出结构：
  {
    "status": "ok",
    "module": "FA-11",
    "transactions": [ {tx_id, subject, related_party, amount, unit_price,
                       fairness_level, fairness_score, deviation_rate,
                       deviation_grade, peer_zscore, hist_zscore,
                       tax_risk_level, needs_adjustment, ...}, ... ],
    "fairness_summary": { total_transactions, fairness_distribution,
                          deviation_grade_distribution, fair_rate, ... },
    "deviation_analysis": { biased_amount, critical_biased_amount,
                            transfer_pricing_risk_count, ... },
    "adjustment_suggestions": [ {tx_id, suggestion}, ... ]
  }
"""
from __future__ import annotations

from typing import Any

# 对外输出的交易明细字段
_DETAIL_FIELDS = [
    "tx_id", "subject", "related_party", "amount", "unit_price",
    "ownership_pct", "industry", "direction",
    "fairness_level", "fairness_score", "deviation_rate", "deviation_grade",
    "peer_zscore", "hist_zscore", "assessment_methods",
    "tax_risk_level", "needs_adjustment",
    "transfer_pricing_risk", "mandatory_disclosure",
    "industry_adjusted_deviation", "industry_tolerance", "industry_tolerance_breach",
    "suggestion", "rule_adjustments",
]


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    items = result.get("items", [])
    summary = result.get("summary", {})

    # 交易明细表
    details = []
    for item in items:
        detail = {k: item.get(k) for k in _DETAIL_FIELDS}
        detail["assessment_methods"] = item.get("assessment_methods", {})
        detail["rule_adjustments"] = item.get("rule_adjustments", [])
        details.append(detail)

    # 公允性汇总
    fairness_summary = {
        "total_transactions": summary.get("total_transactions", len(items)),
        "total_amount": summary.get("total_amount", 0.0),
        "fairness_distribution": summary.get(
            "fairness_distribution", {"fair": 0, "slightly_biased": 0,
                                      "significantly_biased": 0}
        ),
        "deviation_grade_distribution": summary.get(
            "deviation_grade_distribution",
            {"fair": 0, "deviated": 0, "significantly_deviated": 0},
        ),
        "tax_risk_distribution": summary.get(
            "tax_risk_distribution", {"high": 0, "medium": 0, "low": 0}
        ),
        "fair_rate": summary.get("fair_rate", 0.0),
        "needs_adjustment_count": summary.get("needs_adjustment_count", 0),
        "thresholds": summary.get("thresholds", {}),
    }

    # 偏离分析
    rule_adj = summary.get("rule_adjustments", {})
    deviation_analysis = {
        "biased_amount": summary.get("biased_amount", 0.0),
        "critical_biased_amount": summary.get("critical_biased_amount", 0.0),
        "transfer_pricing_risk_count": rule_adj.get(
            "transfer_pricing_risk_count", 0
        ),
        "mandatory_disclosure_count": rule_adj.get(
            "mandatory_disclosure_count", 0
        ),
        "industry_tolerance_breach_count": rule_adj.get(
            "industry_tolerance_breach_count", 0
        ),
    }

    # 调整建议
    suggestions = result.get("adjustment_suggestions", [])

    return {
        "status": "ok",
        "module": "FA-11",
        "transactions": details,
        "fairness_summary": fairness_summary,
        "deviation_analysis": deviation_analysis,
        "adjustment_suggestions": suggestions,
    }
