"""自定义阈值：证据链完整度分级。"""
from __future__ import annotations

from typing import Any

_DEFAULT_EXCELLENT = 85.0
_DEFAULT_GOOD = 70.0
_DEFAULT_PASS = 50.0


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对证据链完整度进行分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    excellent_t = float(threshold.get("excellent", _DEFAULT_EXCELLENT))
    good_t = float(threshold.get("good", _DEFAULT_GOOD))
    pass_t = float(threshold.get("pass", _DEFAULT_PASS))

    chains = result.get("chains", [])
    for c in chains:
        score = float(c.get("completeness_score", 0))
        if score >= excellent_t:
            c["quality_grade"] = "excellent"
        elif score >= good_t:
            c["quality_grade"] = "good"
        elif score >= pass_t:
            c["quality_grade"] = "pass"
        else:
            c["quality_grade"] = "fail"

    return result
