"""自定义阈值分级：合规率 → compliant / warning / non_compliant。

分级规则（可被 config.threshold 覆盖，阈值基于 0~1 的 compliance_rate）：
  * compliant      : compliance_rate >= 0.90  → 合规
  * warning        : 0.70 <= compliance_rate < 0.90 → 告警
  * non_compliant  : compliance_rate < 0.70  → 不合规

严重违规（高风险主机）会被 custom_rules 进一步降级为 non_compliant。
"""
from __future__ import annotations

from typing import Any

_DEFAULT_COMPLIANT = 0.90
_DEFAULT_WARNING = 0.70


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对每台主机的合规率分级，写入 compliance_level。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    compliant_t = float(threshold.get("compliant", _DEFAULT_COMPLIANT))
    warning_t = float(threshold.get("warning", _DEFAULT_WARNING))

    host_reports = result.get("host_reports", [])
    counts = {"compliant": 0, "warning": 0, "non_compliant": 0}
    for host in host_reports:
        rate = float(host.get("compliance_rate", 0.0))
        if rate >= compliant_t:
            level = "compliant"
        elif rate >= warning_t:
            level = "warning"
        else:
            level = "non_compliant"
        host["compliance_level"] = level
        counts[level] += 1

    summary = result.get("scan_summary", {})
    summary["compliance_levels"] = counts
    summary["thresholds"] = {"compliant": compliant_t, "warning": warning_t}
    result["scan_summary"] = summary
    return result
