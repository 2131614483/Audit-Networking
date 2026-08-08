"""自定义阈值分级：基于 overall_risk_score 的告警分级（critical/high/medium/low/info）。

分级规则（可被 config.threshold 覆盖）：
  * critical : risk_score ≥ 0.8
  * high     : 0.6 ≤ risk_score < 0.8
  * medium   : 0.4 ≤ risk_score < 0.6
  * low      : 0.2 ≤ risk_score < 0.4
  * info     : risk_score < 0.2

注：engine 已内置中文 alert_level（紧急/高/中/低），本层补充英文 risk_tier
    并新增 info 档，便于与监控平台对接。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_CRITICAL = 0.8
_DEFAULT_HIGH = 0.6
_DEFAULT_MEDIUM = 0.4
_DEFAULT_LOW = 0.2

_TIERS = ("critical", "high", "medium", "low", "info")


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值为每个供应商分配 risk_tier，并统计分级分布。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    low = float(threshold.get("low", _DEFAULT_LOW))

    suppliers = result.get("suppliers", []) or []
    tier_distribution = {t: 0 for t in _TIERS}

    for s in suppliers:
        score = float(s.get("overall_risk_score", 0.0))
        if score >= critical:
            tier = "critical"
        elif score >= high:
            tier = "high"
        elif score >= medium:
            tier = "medium"
        elif score >= low:
            tier = "low"
        else:
            tier = "info"
        s["risk_tier"] = tier
        tier_distribution[tier] += 1
        # 高置信度复核标记
        s["confirmed_high_risk"] = score >= critical

    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    summary["risk_tier_distribution"] = tier_distribution
    summary["thresholds"] = {
        "critical": critical, "high": high,
        "medium": medium, "low": low,
    }
    result["summary"] = summary
    return result
