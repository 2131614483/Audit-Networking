"""自定义业务规则：跨境合规标记 + 敏感数据升级 + 审计触发。"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """3 条业务规则：
    1) 跨境 + L3+ 敏感数据 → 强制 needs_dpa（数据保护协议）
    2) 路径含 L4 敏感数据 → 自动升级为 critical
    3) 跨境流数量 > 阈值 → compliance_alert
    """
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    max_cross_border = int(rules_cfg.get("max_cross_border", 5))

    flows = result.get("flows", [])
    cross_border_flows = result.get("cross_border_flows", [])

    # 规则 1：跨境 + L3+ → needs_dpa
    for cb in cross_border_flows:
        level = cb.get("sensitive_level", "L0")
        if level in ("L3", "L4"):
            cb["needs_dpa"] = True
            cb["compliance_action"] = "require_data_protection_agreement"

    # 规则 2：路径含 L4 → 升级为 critical
    level_map = {"L0": 0, "L1": 10, "L2": 30, "L3": 60, "L4": 90}
    upgraded_count = 0
    for f in flows:
        max_level = f.get("max_sensitive_level", 0)
        if max_level >= level_map.get("L4", 90) and f.get("risk_level") != "critical":
            f["risk_level"] = "critical"
            f["rule_adjustments"] = f.get("rule_adjustments", [])
            f["rule_adjustments"].append("upgraded_to_critical: L4_sensitive_data_in_path")
            upgraded_count += 1

    # 规则 3：跨境流数量超阈值 → compliance_alert
    cb_count = len(cross_border_flows)
    if cb_count > max_cross_border:
        result["compliance_alert"] = {
            "type": "excessive_cross_border",
            "count": cb_count,
            "threshold": max_cross_border,
            "action": "review_cross_border_data_transfers",
        }

    # 汇总
    result["rule_summary"] = {
        "needs_dpa_count": sum(1 for cb in cross_border_flows if cb.get("needs_dpa")),
        "upgraded_to_critical": upgraded_count,
        "compliance_alert": "compliance_alert" in result,
    }

    return result
