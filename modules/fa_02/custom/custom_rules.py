"""自定义业务规则：低置信度标记复核 + 未映射字段保留原值。

规则：
  1) 低置信度字段（confidence < threshold.confidence）→ 打 need_review 标记
  2) 未映射字段（best_match is None）→ standard_name 回退为 raw_name，标记 unmapped
"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """对低置信度字段打复核标记，对未映射字段保留原值。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    review_threshold = float(threshold.get("confidence", 0.85))

    for f in result.get("fields", []):
        conf = float(f.get("confidence", 0.0))
        is_unmapped = f.get("best_match") is None

        # 规则 1：低置信度或未映射 → 需人工复核
        f["need_review"] = is_unmapped or (conf < review_threshold)

        # 规则 2：未映射 → standard_name 回退为 raw_name，并保留 unmapped 标记
        if is_unmapped:
            f["standard_name"] = f.get("raw_name")
            f["unmapped"] = True
            f["review_reason"] = "no_match"
        else:
            f["standard_name"] = f["best_match"]
            if f.get("need_review"):
                f["review_reason"] = "low_confidence"
            else:
                f.pop("review_reason", None)
    return result
