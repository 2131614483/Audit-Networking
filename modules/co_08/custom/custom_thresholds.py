"""自定义阈值：风险等级分级 + 跨境合规阈值。"""
from __future__ import annotations

from typing import Any

_DEFAULT_CRITICAL = 80
_DEFAULT_HIGH = 60
_DEFAULT_MEDIUM = 40


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值重新分级 flow 风险等级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical_t = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high_t = float(threshold.get("high", _DEFAULT_HIGH))
    medium_t = float(threshold.get("medium", _DEFAULT_MEDIUM))

    flows = result.get("flows", [])
    for f in flows:
        score = float(f.get("risk_score", 0))
        if score >= critical_t:
            f["risk_level"] = "critical"
        elif score >= high_t:
            f["risk_level"] = "high"
        elif score >= medium_t:
            f["risk_level"] = "medium"
        else:
            f["risk_level"] = "low"

    # 重算统计
    from collections import Counter
    level_counts = Counter(f["risk_level"] for f in flows)
    stats = result.get("statistics", {})
    stats["by_risk_level"] = dict(level_counts)
    stats["high_risk_flows"] = sum(1 for f in flows if f["risk_level"] in ("high", "critical"))
    result["statistics"] = stats

    return result
