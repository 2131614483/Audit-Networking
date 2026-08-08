"""统一输出格式化：底稿目录 + 每份摘要 + 交叉引用图 + 统计。

输出结构：
  {
    "status": "ok",
    "workpaper_directory": [ {workpaper_id, template_name, subject_name, tier, completeness, conclusion}, ... ],
    "workpapers": [ ...完整底稿... ],
    "cross_reference_graph": { "nodes": [...], "edges": [...] },
    "statistics": { ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构：底稿目录 + 摘要 + 交叉引用图 + 统计。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    workpapers = result.get("workpapers", []) or []
    cross_refs = result.get("cross_references", []) or []
    statistics = result.get("statistics", {}) or {}

    # 1. 底稿目录（每份摘要）
    directory = []
    for wp in workpapers:
        directory.append({
            "workpaper_id": wp.get("workpaper_id"),
            "template_id": wp.get("template_id"),
            "template_name": wp.get("template_name"),
            "subject_code": wp.get("subject_code"),
            "subject_name": wp.get("subject_name"),
            "audit_procedure": wp.get("audit_procedure"),
            "tier": wp.get("tier"),
            "completeness": wp.get("completeness", 0.0),
            "conclusion_severity": wp.get("conclusion_severity"),
            "conclusion": wp.get("conclusion"),
            "needs_review": wp.get("needs_review", False),
            "review_reasons": wp.get("review_reasons", []),
            "warnings": wp.get("warnings", []),
            "placeholders_missing": wp.get("placeholders_missing", []),
        })

    # 2. 交叉引用图（节点 = 底稿，边 = 引用关系）
    nodes = [
        {
            "id": wp.get("workpaper_id"),
            "label": wp.get("template_name"),
            "subject": wp.get("subject_name"),
            "tier": wp.get("tier"),
        }
        for wp in workpapers
    ]
    edges = [
        {
            "from": r.get("from_workpaper_id"),
            "to": r.get("to_workpaper_id"),
            "to_template": r.get("to_template_name"),
            "status": r.get("status"),
        }
        for r in cross_refs
    ]

    return {
        "status": "ok",
        "workpaper_directory": directory,
        "workpapers": workpapers,
        "cross_reference_graph": {"nodes": nodes, "edges": edges},
        "statistics": statistics,
    }
