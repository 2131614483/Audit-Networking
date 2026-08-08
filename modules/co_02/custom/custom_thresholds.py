"""自定义阈值分级：根据 config 阈值对影响分进行等级划分。

分级规则（可被 config.threshold 覆盖）：
  * high     : impact_score >= 70  → 高影响
  * medium   : 40 <= impact_score < 70 → 中影响
  * low      : impact_score < 40  → 低影响
  * critical_threshold (默认 90)：超高影响，标记 requires_immediate_action

engine._quantify_impact 已内置分级，本模块允许通过 config 不改代码调参，
并补充 requires_immediate_action / thresholds 元信息。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_HIGH = 70.0
_DEFAULT_MEDIUM = 40.0
_DEFAULT_CRITICAL = 90.0


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值重新分级影响评估，并标记 requires_immediate_action。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high = float(threshold.get("impact_high", _DEFAULT_HIGH))
    medium = float(threshold.get("impact_medium", _DEFAULT_MEDIUM))
    critical = float(threshold.get("impact_critical", _DEFAULT_CRITICAL))

    impact = result.get("impact_assessment", {})
    if not isinstance(impact, dict) or "impact_score" not in impact:
        return result

    score = float(impact.get("impact_score", 0.0) or 0.0)
    if score >= high:
        level = "high"
    elif score >= medium:
        level = "medium"
    else:
        level = "low"

    impact["overall_level"] = level
    impact["requires_immediate_action"] = score >= critical
    impact["thresholds"] = {
        "impact_high": high,
        "impact_medium": medium,
        "impact_critical": critical,
    }
    result["impact_assessment"] = impact

    # 同步执行摘要的整体影响等级
    summary = result.get("executive_summary", {})
    if isinstance(summary, dict):
        summary["overall_impact_level"] = level
        result["executive_summary"] = summary
    return result
