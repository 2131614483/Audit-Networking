"""自定义阈值分级：基于数据质量评分对采集结果进行置信度分级。

分级规则（可被 config.threshold 覆盖）：
  * high      : overall ≥ 0.8         → 高置信度（数据可信，可直接采信）
  * medium    : 0.5 ≤ overall < 0.8   → 中置信度（建议人工抽检）
  * low       : overall < 0.5         → 低置信度（需补充权威数据源）

同时对每个融合指标按 confidence 做单项分级（high / medium / low）。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_HIGH = 0.8
_DEFAULT_MEDIUM = 0.5
_DEFAULT_METRIC_HIGH = 0.8
_DEFAULT_METRIC_MEDIUM = 0.6


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对整体质量评分与单项指标置信度分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    metric_high = float(threshold.get("metric_high", _DEFAULT_METRIC_HIGH))
    metric_medium = float(threshold.get("metric_medium", _DEFAULT_METRIC_MEDIUM))

    quality = result.get("quality_report", {}) if isinstance(result.get("quality_report"), dict) else {}
    overall = float(quality.get("overall", 0.0) or 0.0)

    if overall >= high:
        confidence_level = "high"
    elif overall >= medium:
        confidence_level = "medium"
    else:
        confidence_level = "low"
    result["confidence_level"] = confidence_level

    high_count = medium_count = low_count = 0
    for m in result.get("data_catalog", []):
        conf = float(m.get("confidence", 0.0) or 0.0)
        if conf >= metric_high:
            m["confidence_grade"] = "high"
            high_count += 1
        elif conf >= metric_medium:
            m["confidence_grade"] = "medium"
            medium_count += 1
        else:
            m["confidence_grade"] = "low"
            low_count += 1

    quality["thresholds"] = {
        "overall_high": high,
        "overall_medium": medium,
        "metric_high": metric_high,
        "metric_medium": metric_medium,
    }
    quality["confidence_level"] = confidence_level
    quality["metric_grade_distribution"] = {
        "high": high_count, "medium": medium_count, "low": low_count,
    }
    result["quality_report"] = quality
    return result
