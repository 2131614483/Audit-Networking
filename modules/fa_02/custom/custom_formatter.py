"""统一输出格式化：标准化字段汇总表 + 统计。"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。

    输出结构：
      {
        "status": "ok",
        "standardized_fields": [
          {
            "raw_name", "standard_name", "confidence", "subject_code",
            "tier", "need_review", "unmapped", "top3_candidates"
          }, ...
        ],
        "statistics": {"total", "mapped", "need_review", "unmapped"}
      }
    """
    fields = result.get("fields", []) if isinstance(result, dict) else []
    total = len(fields)
    mapped = sum(1 for f in fields if not f.get("unmapped"))
    unmapped = sum(1 for f in fields if f.get("unmapped"))
    need_review = sum(1 for f in fields if f.get("need_review"))

    summary = []
    for f in fields:
        summary.append({
            "raw_name": f.get("raw_name"),
            "standard_name": f.get("standard_name") or f.get("best_match"),
            "confidence": f.get("confidence", 0.0),
            "subject_code": f.get("subject_code"),
            "tier": f.get("tier"),
            "need_review": f.get("need_review", False),
            "unmapped": f.get("unmapped", False),
            "top3_candidates": f.get("top3_candidates", []),
        })

    return {
        "status": "ok",
        "standardized_fields": summary,
        "statistics": {
            "total": total,
            "mapped": mapped,
            "need_review": need_review,
            "unmapped": unmapped,
        },
    }
