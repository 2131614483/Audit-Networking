"""自定义阈值分级：按文档舞弊风险评分进行风险分级。

分级规则（可被 config.threshold 覆盖）：
  * high   : risk_score >= high_threshold（默认 0.6）  → 高风险文档
  * medium : medium_threshold <= risk_score < high_threshold（默认 0.3） → 中风险
  * low    : risk_score < medium_threshold              → 低风险
"""
from __future__ import annotations

from typing import Any

_DEFAULT_HIGH = 0.6
_DEFAULT_MEDIUM = 0.3


def apply_thresholds(result: Any, config: Any) -> Any:
    """根据 config 阈值对每个文档进行风险分级（high/medium/low）。"""
    if not isinstance(result, dict):
        return result
    cfg = config if isinstance(config, dict) else {}
    threshold = cfg.get("threshold", {}) if isinstance(cfg.get("threshold", {}), dict) else {}
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))

    detections = result.get("detections", [])
    grade_counts = {"high": 0, "medium": 0, "low": 0}

    for det in detections:
        score = float(det.get("risk_score", 0.0) or 0.0)
        if score >= high:
            grade = "high"
        elif score >= medium:
            grade = "medium"
        else:
            grade = "low"
        det["risk_grade"] = grade
        grade_counts[grade] += 1

    # 同步统计
    summary = result.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    summary["risk_grade_distribution"] = dict(grade_counts)
    summary["thresholds"] = {"high": high, "medium": medium}
    result["summary"] = summary
    return result
