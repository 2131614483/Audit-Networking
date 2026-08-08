"""统一输出格式化：勾稽检查结果明细表 + 摘要统计。

输出结构：
  {
    "status": "ok",
    "module": "FA-08",
    "module_name": "底稿自动勾稽检查",
    "summary": { total_checks, pass_count, fail_count, pass_rate,
                 severity_distribution, total_diff_amount, ... },
    "items": [ {check_id, type, description, severity, diff_amount, status, suggestion}, ... ],
    "critical_issues": [...],
    "adjustment_suggestions": [...],
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    items = result.get("items", [])
    summary = result.get("summary", {})

    # 明细表
    details = []
    for item in items:
        details.append({
            "check_id": item.get("check_id"),
            "type": item.get("type"),
            "description": item.get("description"),
            "severity": item.get("severity"),
            "diff_amount": item.get("diff_amount"),
            "status": item.get("status"),
            "suggestion": item.get("suggestion", ""),
            "change_pct": item.get("change_pct"),
            "rule_adjustments": item.get("rule_adjustments", []),
        })

    # 关键问题
    critical = []
    for c in result.get("critical_issues", []):
        critical.append({
            "check_id": c.get("check_id"),
            "type": c.get("type"),
            "description": c.get("description"),
            "severity": c.get("severity"),
            "diff_amount": c.get("diff_amount"),
            "suggestion": c.get("suggestion", ""),
        })

    # 调整建议
    suggestions = []
    for s in result.get("adjustment_suggestions", []):
        suggestions.append({
            "issue": s.get("issue"),
            "action": s.get("action"),
            "expected_diff": s.get("expected_diff"),
        })

    return {
        "status": "ok",
        "module": "FA-08",
        "module_name": "底稿自动勾稽检查",
        "summary": summary,
        "items": details,
        "critical_issues": critical,
        "adjustment_suggestions": suggestions,
    }
