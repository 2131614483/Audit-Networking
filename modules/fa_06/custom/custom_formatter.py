"""统一输出格式化：差异分析明细表 + 差异汇总 + 底稿取证清单。

输出结构：
  {
    "status": "ok",
    "module": "FA-06",
    "difference_items": [ {item_id, subject, book_amount, reply_amount, diff,
                           diff_pct, category, severity, materiality_grade,
                           confidence, reasons, tolerance_pct, audit_advice,
                           forensics, is_material, systemic_issue, aged_item,
                           rule_adjustments}, ... ],
    "summary": { total_items, has_diff_count, category_distribution,
                 severity_distribution, materiality_distribution,
                 total_abs_diff_amount, high_risk_count, high_risk_ids,
                 rule_flags, thresholds },
    "workpaper_todo": [ {item_id, todo, priority, advice}, ... ]
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    items = result.get("items", [])
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}

    # 差异明细表
    details = []
    for it in items:
        details.append({
            "item_id": it.get("item_id"),
            "subject": it.get("subject"),
            "book_amount": it.get("book_amount"),
            "reply_amount": it.get("reply_amount"),
            "diff": it.get("diff"),
            "diff_pct": it.get("diff_pct"),
            "category": it.get("category"),
            "severity": it.get("severity"),
            "materiality_grade": it.get("materiality_grade", "immaterial"),
            "confidence": it.get("confidence"),
            "reasons": it.get("reasons", []),
            "tolerance_pct": it.get("tolerance_pct"),
            "audit_advice": it.get("audit_advice", []),
            "forensics": it.get("forensics", []),
            "is_material": it.get("is_material", False),
            "systemic_issue": it.get("systemic_issue", False),
            "aged_item": it.get("aged_item", False),
            "rule_adjustments": it.get("rule_adjustments", []),
        })

    # 汇总统计
    output_summary = {
        "total_items": summary.get("total_items", len(items)),
        "has_diff_count": summary.get("has_diff_count", 0),
        "category_distribution": summary.get(
            "category_distribution", {}
        ),
        "severity_distribution": summary.get(
            "severity_distribution", {}
        ),
        "materiality_distribution": summary.get(
            "materiality_distribution",
            {"material": 0, "immaterial": 0, "de_minimis": 0},
        ),
        "total_abs_diff_amount": summary.get(
            "total_abs_diff_amount", 0.0
        ),
        "high_risk_count": summary.get("high_risk_count", 0),
        "high_risk_ids": summary.get("high_risk_ids", []),
        "rule_flags": summary.get(
            "rule_flags",
            {"material_flagged": 0, "systemic_flagged": 0, "aged_flagged": 0},
        ),
        "thresholds": summary.get("thresholds", {}),
    }

    return {
        "status": "ok",
        "module": "FA-06",
        "difference_items": details,
        "summary": output_summary,
        "workpaper_todo": result.get("workpaper_todo", []),
    }
