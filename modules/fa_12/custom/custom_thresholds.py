"""自定义阈值分级：基于完整性评分对披露合规性进行风险分级。

分级规则（可被 config.threshold 覆盖）：
  * high   : completeness_score < high_threshold (默认 60.0)  → 高风险（监管行动）
  * medium : high_threshold ≤ completeness_score < low_threshold (默认 80.0) → 中风险
  * low    : completeness_score ≥ low_threshold (默认 80.0)  → 低风险（基本合规）

同时为每个条目补充 compliance_level，便于按条目统计。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_HIGH_THRESHOLD = 60.0
_DEFAULT_LOW_THRESHOLD = 80.0


def apply_thresholds(result: Any, config: Any) -> Any:
    """根据 config 阈值对披露完整性进行风险分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high_threshold = float(
        threshold.get("high_threshold", _DEFAULT_HIGH_THRESHOLD)
    )
    low_threshold = float(
        threshold.get("low_threshold", _DEFAULT_LOW_THRESHOLD)
    )

    summary = result.get("summary", {})
    score = float(summary.get("completeness_score", 100.0) or 100.0)
    if score < high_threshold:
        risk_level = "high"
    elif score < low_threshold:
        risk_level = "medium"
    else:
        risk_level = "low"
    summary["risk_level"] = risk_level

    # 按条目补充 compliance_level
    items = result.get("items", [])
    level_dist = {"high": 0, "medium": 0, "low": 0}
    for item in items:
        status = item.get("status", "OK")
        severity = item.get("severity", "low")
        if status == "OK":
            level = "low"
        elif status == "PARTIAL":
            level = "medium"
        else:  # UNDISCLOSED
            level = "high" if severity == "high" else "medium"
        item["compliance_level"] = level
        level_dist[level] += 1

    summary["compliance_level_distribution"] = dict(level_dist)
    summary["thresholds"] = {
        "high_threshold": high_threshold,
        "low_threshold": low_threshold,
    }
    result["summary"] = summary
    return result
