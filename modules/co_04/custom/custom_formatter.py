"""统一输出格式化：AML 告警报告（SAR 明细 + 风险汇总）。

输出结构：
  {
    "status": "ok",
    "module": "CO-04",
    "alerts": [ {sar_id, pattern, customer_id, risk_score, alert_level,
                  transactions, need_review, cross_border, ...}, ... ],
    "summary": { total_sars, alert_levels, patterns, rule_adjustments, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外 AML 告警报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    sars = result.get("sars", [])
    summary = result.get("summary", {})

    # SAR 告警明细表
    alerts = []
    for s in sars:
        alerts.append({
            "sar_id": s.get("sar_id"),
            "pattern": s.get("pattern"),
            "customer_id": s.get("customer_id"),
            "risk_score": s.get("risk_score"),
            "alert_level": s.get("alert_level", "low"),
            "transactions": s.get("transactions", []),
            "amount": s.get("amount"),
            "total_amount": s.get("total_amount"),
            "transaction_count": s.get("transaction_count"),
            "jurisdiction": s.get("jurisdiction"),
            "counterparty": s.get("counterparty"),
            "need_review": s.get("need_review", False),
            "cross_border": s.get("cross_border", False),
            "organized_layering": s.get("organized_layering", False),
            "rule_adjustments": s.get("rule_adjustments", []),
        })

    # 汇总统计
    output_summary = {
        "total_transactions": result.get("total_transactions", 0),
        "total_sars": summary.get("total_sars", len(sars)),
        "alert_levels": summary.get("alert_levels", {
            "critical": 0, "high": 0, "medium": 0, "low": 0,
        }),
        "patterns": summary.get("patterns", []),
        "rule_adjustments": summary.get("rule_adjustments", {}),
        "thresholds": summary.get("thresholds", {}),
    }

    return {
        "status": "ok",
        "module": "CO-04",
        "alerts": alerts,
        "summary": output_summary,
    }
