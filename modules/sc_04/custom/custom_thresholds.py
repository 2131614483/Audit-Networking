"""自定义阈值分级：根据 anomaly_score 进行四级分级（critical/high/medium/low）。

分级规则（可被 config.threshold 覆盖）：
  * critical : anomaly_score ≥ 0.85  → 严重异常，优先专项审计
  * high     : 0.70 ≤ score < 0.85  → 高异常
  * medium   : 0.40 ≤ score < 0.70  → 中异常
  * low      : score < 0.40          → 低异常
  * confirmed_anomaly：score ≥ critical 阈值时标记为已确认异常
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_CRITICAL = 0.85
_DEFAULT_HIGH = 0.70
_DEFAULT_MEDIUM = 0.40


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对 anomaly_score 重新分级，并标记 confirmed_anomaly。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))

    results = result.get("results", [])
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    confirmed_count = 0
    for r in results:
        score = float(r.get("anomaly_score", 0.0))
        if score >= critical:
            r["severity"] = "critical"
            counts["critical"] += 1
        elif score >= high:
            r["severity"] = "high"
            counts["high"] += 1
        elif score >= medium:
            r["severity"] = "medium"
            counts["medium"] += 1
        else:
            r["severity"] = "low"
            counts["low"] += 1
        # 严重异常确认标记（用于优先复核排序）
        r["confirmed_anomaly"] = score >= critical
        if r["confirmed_anomaly"]:
            confirmed_count += 1

    # 同步统计
    summary = result.get("summary", {})
    summary["severity_distribution"] = counts
    summary["confirmed_anomaly_count"] = confirmed_count
    summary["thresholds"] = {
        "critical": critical, "high": high, "medium": medium,
    }
    result["summary"] = summary
    return result
