"""自定义阈值分级：网络风险分级（基于严重度 + 置信度）。

分级规则（可被 config.threshold 覆盖）：
  * critical : severity=high AND confidence >= 0.85 → 紧急
  * high     : severity=high → 高风险
  * medium   : severity=medium → 中风险
  * low      : severity=low 或其他 → 低风险
"""
from __future__ import annotations

from typing import Any

_DEFAULT_CRITICAL_CONFIDENCE = 0.85


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对每个检测进行网络风险分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical_conf = float(
        threshold.get("critical_confidence", _DEFAULT_CRITICAL_CONFIDENCE)
    )

    detections = result.get("patterns_detected", [])
    if not detections:
        return result

    critical_count = high_count = medium_count = low_count = 0
    for d in detections:
        severity = d.get("severity", "low")
        confidence = float(d.get("confidence", 0.0))
        if severity == "high" and confidence >= critical_conf:
            d["risk_grade"] = "critical"
            critical_count += 1
        elif severity == "high":
            d["risk_grade"] = "high"
            high_count += 1
        elif severity == "medium":
            d["risk_grade"] = "medium"
            medium_count += 1
        else:
            d["risk_grade"] = "low"
            low_count += 1

    result["risk_grading"] = {
        "critical": critical_count,
        "high": high_count,
        "medium": medium_count,
        "low": low_count,
    }
    result["thresholds"] = {"critical_confidence": critical_conf}
    return result
