"""统一输出格式化：披露完整性报告（评分 + 缺失清单 + 风险等级 + 补披露建议）。

输出结构：
  {
    "status": "ok",
    "module": "FA-12",
    "disclosure_items": [ {tx_id, related_party, relationship, tx_type,
                           amount, status, severity, compliance_level,
                           missing_fields, reason, suggestion, ...}, ... ],
    "completeness_summary": { completeness_score, risk_level, total_transactions,
                              fully_disclosed, partially_disclosed, undisclosed, ... },
    "missing_items": [ {tx_id, related_party, tx_type, amount, severity, reason,
                         suggestion}, ... ],
    "supplement_suggestions": [ {tx_id, suggestion, priority, owner}, ... ]
  }
"""
from __future__ import annotations

from typing import Any

# 对外输出的条目明细字段
_DETAIL_FIELDS = [
    "tx_id", "related_party", "relationship", "tx_type",
    "amount", "outstanding", "status", "severity", "compliance_level",
    "missing_fields", "reason", "suggestion", "critical_risk",
    "rule_adjustments",
]


def format_output(result: Any) -> Any:
    """把内部结果转为对外披露完整性报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    items = result.get("items", [])
    summary = result.get("summary", {})

    # 条目明细表
    details = []
    for item in items:
        detail = {k: item.get(k) for k in _DETAIL_FIELDS}
        detail["missing_fields"] = item.get("missing_fields", [])
        detail["rule_adjustments"] = item.get("rule_adjustments", [])
        detail["critical_risk"] = item.get("critical_risk", False)
        details.append(detail)

    # 完整性汇总
    completeness_summary = {
        "completeness_score": summary.get("completeness_score", 100.0),
        "risk_level": summary.get("risk_level", "low"),
        "total_transactions": summary.get("total_transactions", len(items)),
        "fully_disclosed": summary.get("fully_disclosed", 0),
        "partially_disclosed": summary.get("partially_disclosed", 0),
        "undisclosed": summary.get("undisclosed", 0),
        "total_transaction_amount": summary.get("total_transaction_amount", 0.0),
        "undisclosed_amount": summary.get("undisclosed_amount", 0.0),
        "compliance_level_distribution": summary.get(
            "compliance_level_distribution", {"high": 0, "medium": 0, "low": 0}
        ),
        "regulatory_action_required": summary.get(
            "regulatory_action_required", False
        ),
        "thresholds": summary.get("thresholds", {}),
    }

    # 缺失清单（仅未披露与部分披露）
    missing_items = [
        {
            "tx_id": i.get("tx_id"),
            "related_party": i.get("related_party"),
            "tx_type": i.get("tx_type"),
            "amount": i.get("amount"),
            "status": i.get("status"),
            "severity": i.get("severity"),
            "reason": i.get("reason") or i.get("missing_fields"),
            "suggestion": i.get("suggestion"),
        }
        for i in items if i.get("status") in ("UNDISCLOSED", "PARTIAL")
    ]

    # 补披露建议（从 remediation_plan 映射）
    suggestions = []
    for step in result.get("remediation_plan", []):
        suggestions.append({
            "action": step.get("action"),
            "priority": step.get("priority"),
            "owner": step.get("owner"),
        })

    return {
        "status": "ok",
        "module": "FA-12",
        "disclosure_items": details,
        "completeness_summary": completeness_summary,
        "missing_items": missing_items,
        "supplement_suggestions": suggestions,
    }
