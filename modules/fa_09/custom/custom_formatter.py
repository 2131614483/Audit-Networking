"""统一输出格式化：质量复核报告（维度评分 + 总体等级 + 问题 + 建议）。

输出结构：
  {
    "status": "ok",
    "module": "FA-09",
    "module_name": "AI底稿质量复核助手",
    "summary": { total_workpapers, average_score, grade_distribution, ... },
    "items": [ {wp_id, wp_type, title, dimension_scores, overall_score, grade, ...}, ... ],
    "critical_issues": [...],
    "improvement_tips": [...],
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

    # 底稿质量明细
    details = []
    for item in items:
        details.append({
            "wp_id": item.get("wp_id"),
            "wp_type": item.get("wp_type"),
            "title": item.get("title"),
            "dimension_scores": item.get("dimension_scores", {}),
            "overall_score": item.get("overall_score"),
            "grade": item.get("grade"),
            "passed": item.get("passed"),
            "force_revise": item.get("force_revise", False),
            "has_critical_dimension": item.get("has_critical_dimension", False),
            "escalate": item.get("escalate", False),
            "issues": item.get("issues", []),
            "compliance_hits": item.get("compliance_hits", []),
            "compliance_rate": item.get("compliance_rate"),
        })

    # 关键问题
    critical = []
    for c in result.get("critical_issues", []):
        critical.append({
            "wp_id": c.get("wp_id"),
            "dimension": c.get("dimension"),
            "dimension_cn": c.get("dimension_cn"),
            "severity": c.get("severity"),
            "score": c.get("score"),
            "issue": c.get("issue"),
            "suggestion": c.get("suggestion"),
        })

    return {
        "status": "ok",
        "module": "FA-09",
        "module_name": "AI底稿质量复核助手",
        "summary": summary,
        "items": details,
        "critical_issues": critical,
        "improvement_tips": result.get("improvement_tips", []),
    }
