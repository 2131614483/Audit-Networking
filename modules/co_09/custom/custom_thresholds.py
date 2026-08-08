"""自定义阈值分级：合规评分 → compliant / partial / non_compliant。

分级规则（可被 config.threshold 覆盖）：
  * compliant      : overall_score >= 80  → 合规
  * partial        : 50 <= overall_score < 80 → 部分合规
  * non_compliant  : overall_score < 50  → 不合规
"""
from __future__ import annotations

from typing import Any

_DEFAULT_COMPLIANT = 80.0
_DEFAULT_PARTIAL = 50.0


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对合规评分进行分级，并写入 compliance_level。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    compliant_t = float(threshold.get("compliant", _DEFAULT_COMPLIANT))
    partial_t = float(threshold.get("partial", _DEFAULT_PARTIAL))

    policies = result.get("policies", [])
    counts = {"compliant": 0, "partial": 0, "non_compliant": 0}
    for p in policies:
        score = float(p.get("overall_score", 0.0))
        if score >= compliant_t:
            level = "compliant"
        elif score >= partial_t:
            level = "partial"
        else:
            level = "non_compliant"
        p["compliance_level"] = level
        counts[level] += 1

    summary = result.get("summary", {})
    summary["compliance_levels"] = counts
    summary["thresholds"] = {"compliant": compliant_t, "partial": partial_t}
    result["summary"] = summary
    return result
