"""自定义业务规则：在 engine 之后执行，可覆盖/补充分类结果。

规则：
  1) PII/医疗敏感数据未加密 → 标记 needs_encryption + 升级为 L4（critical 告警）
  2) 未分类资产（L0/L1）但检测到敏感类型 → 自动重分类
  3) 敏感数据位于公开区域（location/source_type 含 public/web/cdn 标记）→ 高危告警
"""
from __future__ import annotations

from typing import Any

# L4 受限类型（PII / 医疗）
_HIGH_RISK_TYPES = {"pii", "health"}
# 公开区域标记
_PUBLIC_ZONE_MARKERS = ("public", "公开", "internet", "web", "cdn", "外网")

# 等级顺序
_LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4"]


def _level_index(level: str) -> int:
    try:
        return _LEVEL_ORDER.index(level)
    except ValueError:
        return 0


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：PII 未加密告警 / 未分类自动重分类 / 公开区域暴露告警。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}

    assets = result.get("assets", [])
    alerts: list[dict] = result.setdefault("alerts", [])
    pii_unencrypted = 0
    auto_classified = 0
    public_zone_alerts = 0

    for a in assets:
        stypes = set(a.get("sensitive_types", []))
        level = a.get("sensitivity_level", "L0")
        location = str(a.get("location", "")).lower()
        source_type = str(a.get("source_type", "")).lower()
        zone_text = f"{location} {source_type}"
        rule_flags = a.setdefault("rule_flags", [])

        # 规则 1：PII/医疗敏感数据未加密 → critical
        has_high_risk = bool(stypes & _HIGH_RISK_TYPES)
        encrypted = bool(a.get("encrypted", False))
        if has_high_risk and not encrypted:
            a["needs_encryption"] = True
            if _level_index(level) < _level_index("L4"):
                a["sensitivity_level"] = "L4"
            pii_unencrypted += 1
            rule_flags.append("pii_without_encryption")
            alerts.append({
                "asset_id": a.get("asset_id"),
                "rule": "pii_without_encryption",
                "severity": "critical",
                "message": f"资产 {a.get('name')} 含 PII/医疗敏感数据但未加密",
            })
        else:
            a.setdefault("needs_encryption", False)

        # 规则 2：未分类资产（L0/L1）但有敏感类型 → 自动重分类
        if _level_index(level) <= _level_index("L1") and stypes:
            new_level = "L4" if (stypes & _HIGH_RISK_TYPES) else "L2"
            a["sensitivity_level"] = new_level
            a["auto_classified"] = True
            auto_classified += 1
            rule_flags.append("auto_classified")
        else:
            a.setdefault("auto_classified", False)

        # 规则 3：敏感数据位于公开区域 → 高危告警
        in_public_zone = any(m in zone_text for m in _PUBLIC_ZONE_MARKERS)
        if stypes and in_public_zone:
            public_zone_alerts += 1
            a["public_zone_exposure"] = True
            rule_flags.append("sensitive_in_public_zone")
            alerts.append({
                "asset_id": a.get("asset_id"),
                "rule": "sensitive_in_public_zone",
                "severity": "high",
                "message": f"资产 {a.get('name')} 含敏感数据但位于公开区域",
            })
        else:
            a.setdefault("public_zone_exposure", False)

    # 重新统计等级分布（规则可能改了 level）
    level_counts = {"L0": 0, "L1": 0, "L2": 0, "L3": 0, "L4": 0}
    for a in assets:
        lv = a.get("sensitivity_level", "L0")
        level_counts[lv] = level_counts.get(lv, 0) + 1

    stats = result.get("statistics", {})
    stats["by_level"] = level_counts
    stats["l3_l4_count"] = level_counts.get("L3", 0) + level_counts.get("L4", 0)
    stats["rule_summary"] = {
        "pii_without_encryption": pii_unencrypted,
        "auto_classified": auto_classified,
        "sensitive_in_public_zone": public_zone_alerts,
        "total_alerts": len(alerts),
    }
    result["statistics"] = stats
    return result
