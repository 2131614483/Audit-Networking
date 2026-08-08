"""自定义业务规则：在 engine 之后执行，可覆盖/补充风险分级。

规则：
  1) 金额 > 100万 → 自动升级为 high（无论评分多少）
  2) 关联方交易 → 强制 need_review = True
  3) 非营业时间（hour < 8 或 hour >= 20）→ 标记 off_hours 并升级一档
"""
from __future__ import annotations

from typing import Any

_LARGE_AMOUNT = 1_000_000.0  # 100万
_OFF_HOURS_LOW = 8           # 营业时间下界（含）
_OFF_HOURS_HIGH = 20         # 营业时间上界（不含）


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：金额升级 / 关联方强制复核 / 非营业时间标记。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    large_amount = float(rules_cfg.get("large_amount", _LARGE_AMOUNT))
    off_low = int(rules_cfg.get("off_hours_low", _OFF_HOURS_LOW))
    off_high = int(rules_cfg.get("off_hours_high", _OFF_HOURS_HIGH))

    suspicious = result.get("suspicious_transactions", [])
    upgraded_to_high = 0
    forced_review = 0
    off_hours_marked = 0

    for s in suspicious:
        amt = float(s.get("amount", 0) or 0)
        hour = s.get("hour")
        is_related = bool(s.get("is_related_party", False))
        adjustments = s.setdefault("rule_adjustments", [])

        # 规则 1：大额自动升级为 high
        if amt > large_amount and s.get("risk_level") != "high":
            s["risk_level"] = "high"
            upgraded_to_high += 1
            adjustments.append(f"金额>{large_amount:.0f}自动升级high")

        # 规则 2：关联方强制复核
        if is_related:
            s["need_review"] = True
            forced_review += 1
            adjustments.append("关联方交易强制复核")
        else:
            s.setdefault("need_review", False)

        # 规则 3：非营业时间标记 + 升级一档
        if hour is not None and (hour < off_low or hour >= off_high):
            s["off_hours"] = True
            off_hours_marked += 1
            adjustments.append(f"非营业时间({hour}时)")
            if s.get("risk_level") == "low":
                s["risk_level"] = "medium"
            elif s.get("risk_level") == "medium":
                s["risk_level"] = "high"
        else:
            s["off_hours"] = False

    # 同步风险分布统计
    stats = result.get("statistics", {})
    stats["risk_distribution"] = {
        "high": sum(1 for s in suspicious if s.get("risk_level") == "high"),
        "medium": sum(1 for s in suspicious if s.get("risk_level") == "medium"),
        "low": sum(1 for s in suspicious if s.get("risk_level") == "low"),
    }
    stats["rule_adjustments"] = {
        "upgraded_to_high": upgraded_to_high,
        "forced_review": forced_review,
        "off_hours_marked": off_hours_marked,
    }
    result["statistics"] = stats
    return result
