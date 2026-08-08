"""自定义阈值分级：根据 SAR 风险评分进行告警分级。

分级规则（可被 config.threshold 覆盖）：
  * critical : risk_score >= 90  → 紧急告警（立即上报）
  * high     : 80 <= risk_score < 90 → 高风险告警
  * medium   : 60 <= risk_score < 80 → 中风险告警
  * low      : risk_score < 60  → 低风险告警
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_CRITICAL = 90
_DEFAULT_HIGH = 80
_DEFAULT_MEDIUM = 60


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对每个 SAR 进行告警分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))

    sars = result.get("sars", [])
    critical_count = high_count = medium_count = low_count = 0
    for s in sars:
        score = float(s.get("risk_score", 0.0))
        if score >= critical:
            s["alert_level"] = "critical"
            critical_count += 1
        elif score >= high:
            s["alert_level"] = "high"
            high_count += 1
        elif score >= medium:
            s["alert_level"] = "medium"
            medium_count += 1
        else:
            s["alert_level"] = "low"
            low_count += 1

    # 同步 summary
    summary = result.get("summary", {})
    summary["alert_levels"] = {
        "critical": critical_count,
        "high": high_count,
        "medium": medium_count,
        "low": low_count,
    }
    summary["thresholds"] = {
        "critical": critical, "high": high, "medium": medium,
    }
    result["summary"] = summary
    return result
