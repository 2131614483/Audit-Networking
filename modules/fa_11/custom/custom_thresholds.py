"""自定义阈值分级：基于偏离率对关联交易定价公允性进行分级。

分级规则（可被 config.threshold 覆盖）：
  * fair                : |deviation_rate| < deviation_fair (默认 0.05)  → 公允
  * deviated            : deviation_fair ≤ |deviation_rate| < deviation_significant (默认 0.15) → 偏离
  * significantly_deviated : |deviation_rate| ≥ deviation_significant (默认 0.15) → 重大偏离
  * needs_adjustment    : |deviation_rate| ≥ adjustment_threshold (默认 0.10) → 需调整

同时保留引擎原始 fairness_level，补充 deviation_grade 与 needs_adjustment 标记。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值（与引擎 TOLERANCE_DEFAULT / _industry_bias 量级匹配）
_DEFAULT_DEVIATION_FAIR = 0.05
_DEFAULT_DEVIATION_SIGNIFICANT = 0.15
_DEFAULT_ADJUSTMENT_THRESHOLD = 0.10


def apply_thresholds(result: Any, config: Any) -> Any:
    """根据 config 阈值对每笔交易按偏离率重新分级，并标记 needs_adjustment。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    dev_fair = float(threshold.get("deviation_fair", _DEFAULT_DEVIATION_FAIR))
    dev_significant = float(
        threshold.get("deviation_significant", _DEFAULT_DEVIATION_SIGNIFICANT)
    )
    adj_threshold = float(
        threshold.get("adjustment_threshold", _DEFAULT_ADJUSTMENT_THRESHOLD)
    )

    items = result.get("items", [])
    grade_dist = {"fair": 0, "deviated": 0, "significantly_deviated": 0}
    needs_adjustment_count = 0

    for item in items:
        dev = abs(float(item.get("deviation_rate", 0.0) or 0.0))
        if dev < dev_fair:
            grade = "fair"
        elif dev < dev_significant:
            grade = "deviated"
        else:
            grade = "significantly_deviated"
        item["deviation_grade"] = grade
        grade_dist[grade] += 1

        needs_adj = dev >= adj_threshold
        item["needs_adjustment"] = needs_adj
        if needs_adj:
            needs_adjustment_count += 1

    summary = result.get("summary", {})
    summary["deviation_grade_distribution"] = dict(grade_dist)
    summary["needs_adjustment_count"] = needs_adjustment_count
    summary["thresholds"] = {
        "deviation_fair": dev_fair,
        "deviation_significant": dev_significant,
        "adjustment_threshold": adj_threshold,
    }
    result["summary"] = summary
    return result
