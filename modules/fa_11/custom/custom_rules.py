"""自定义业务规则：在 engine 之后执行，标记转让定价风险与披露义务。

规则：
  1) 转让定价风险：|deviation_rate| > 30% → transfer_pricing_risk = True
     （触发税务机关特别纳税调整调查的常见门槛）
  2) 强制披露义务：关联方交易金额 > 1000 万 → mandatory_disclosure = True
     （《公开发行证券的公司信息披露内容与格式准则》关联交易披露阈值）
  3) 行业容忍度调整：按行业_bias 对偏离率做行业化修正，输出
     industry_adjusted_deviation，超容忍度则标记 industry_tolerance_breach
"""
from __future__ import annotations

from typing import Any

# 出厂默认值（与 engine._industry_bias 保持一致，可通过 config.rules 覆盖）
_TRANSFER_PRICING_THRESHOLD = 0.30
_MANDATORY_DISCLOSURE_AMOUNT = 10_000_000.0
_INDUSTRY_TOLERANCE = {
    "制造": 0.08,
    "贸易": 0.12,
    "金融": 0.05,
    "房地产": 0.15,
    "科技": 0.10,
    "医药": 0.09,
    "default": 0.10,
}


def apply_custom_rules(result: Any, config: Any) -> Any:
    """应用业务规则：转让定价风险 / 强制披露 / 行业容忍度调整。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    tp_threshold = float(
        rules_cfg.get("transfer_pricing_threshold", _TRANSFER_PRICING_THRESHOLD)
    )
    mandatory_amount = float(
        rules_cfg.get("mandatory_disclosure_amount", _MANDATORY_DISCLOSURE_AMOUNT)
    )
    tolerance = dict(_INDUSTRY_TOLERANCE)
    tolerance.update(rules_cfg.get("industry_tolerance", {}) or {})

    items = result.get("items", [])
    tp_risk_count = 0
    mandatory_count = 0
    tolerance_breach_count = 0

    for item in items:
        dev = float(item.get("deviation_rate", 0.0) or 0.0)
        abs_dev = abs(dev)
        amount = float(item.get("amount", 0.0) or 0.0)
        industry = str(item.get("industry", "default")) or "default"
        adjustments = item.setdefault("rule_adjustments", [])

        # 规则 1：转让定价风险
        item["transfer_pricing_risk"] = abs_dev > tp_threshold
        if item["transfer_pricing_risk"]:
            tp_risk_count += 1
            adjustments.append(
                f"偏离率{abs_dev:.1%}>{tp_threshold:.0%}触发转让定价风险"
            )

        # 规则 2：强制披露义务
        item["mandatory_disclosure"] = amount > mandatory_amount
        if item["mandatory_disclosure"]:
            mandatory_count += 1
            adjustments.append(
                f"金额{amount:,.0f}>{mandatory_amount:,.0f}需强制披露"
            )

        # 规则 3：行业容忍度调整
        bias = float(tolerance.get(industry, tolerance["default"]))
        adjusted = dev - bias
        item["industry_adjusted_deviation"] = round(adjusted, 4)
        item["industry_tolerance"] = bias
        breach = abs(adjusted) > bias
        item["industry_tolerance_breach"] = breach
        if breach:
            tolerance_breach_count += 1
            adjustments.append(
                f"行业({industry})容忍度{bias:.0%}超限"
            )

    summary = result.get("summary", {})
    summary["rule_adjustments"] = {
        "transfer_pricing_risk_count": tp_risk_count,
        "mandatory_disclosure_count": mandatory_count,
        "industry_tolerance_breach_count": tolerance_breach_count,
    }
    result["summary"] = summary
    return result
