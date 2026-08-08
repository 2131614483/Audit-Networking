"""自定义业务规则：在 engine + 阈值之后执行，覆盖/补充影响等级与推送建议。

业务规则：
  1) 数据安全类法规自动升级为高影响（impact_level = high）
  2) 企业所在国法规强制推送（country 命中企业 countries → push=True）
  3) 上市企业涉证监法规强制推送（enterprise.listed 且 is_securities → push=True）
  4) 被推送的法规影响等级不得低于 medium（兜底升级）
"""
from __future__ import annotations

from typing import Any

# 关键性分类：直接升级为高影响
_HIGH_IMPACT_CATEGORIES = {"data_security"}


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：升级影响等级 + 强制推送标记。"""
    if not isinstance(result, dict):
        return result

    enterprise = result.get("enterprise", {}) or {}
    ent_countries = {c.upper() for c in enterprise.get("countries", [])}
    ent_listed = bool(enterprise.get("listed", False))

    for r in result.get("regulations", []):
        reasons = r.setdefault("push_reasons", [])

        # 规则 1：数据安全类法规自动升级为高影响
        if r.get("category") in _HIGH_IMPACT_CATEGORIES:
            r["impact_level"] = "high"
            r["rule_upgraded"] = "data_security_high_impact"

        # 规则 2：企业所在国法规强制推送
        if r.get("country") and r["country"] in ent_countries:
            if not r.get("push"):
                r["push"] = True
            if "home_country" not in reasons:
                reasons.append("home_country")

        # 规则 3：上市企业涉证监法规强制推送
        if ent_listed and r.get("is_securities"):
            if not r.get("push"):
                r["push"] = True
            if "listed_securities" not in reasons:
                reasons.append("listed_securities")

        # 规则 4：被推送法规影响等级兜底不低于 medium
        if r.get("push"):
            if r.get("impact_level") == "low":
                r["impact_level"] = "medium"
                r["rule_upgraded"] = r.get("rule_upgraded", "push_floor_medium")

    # 重算推送数统计（custom_rules 可能新增推送）
    regs = result.get("regulations", [])
    stats = result.get("statistics", {})
    stats["push_count"] = sum(1 for r in regs if r.get("push"))
    # 重算各影响等级统计（影响等级可能被升级）
    by_impact: dict[str, int] = {}
    for r in regs:
        lvl = r.get("impact_level", "low")
        by_impact[lvl] = by_impact.get(lvl, 0) + 1
    stats["by_impact"] = by_impact
    result["statistics"] = stats
    return result
