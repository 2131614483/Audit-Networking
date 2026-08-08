"""自定义业务规则：在 engine 之后执行，标记关联方异常与风险。

规则：
  1) 3跳以内共享法人 → 自动标记关联方（rule_tag: auto_related_by_legal_rep）
  2) 循环持股 → 标记异常（rule_tag: circular_shareholding）
  3) 交叉担保 → 标记高风险（rule_tag: cross_guarantee）
  4) 派生共享关系（address_share/phone_share/account_share）关联方 → 标记共享类型
"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """对关联方应用业务规则标记。"""
    if not isinstance(result, dict):
        return result

    for net in result.get("networks", []):
        related = net.get("related_parties", [])
        cycles = net.get("cycles", [])

        # 环路标记集合：{entity_id: [cycle_type, ...]}
        cycle_tags: dict[str, list[str]] = {}
        for c in cycles:
            for eid in c["entities"]:
                cycle_tags.setdefault(eid, []).append(c["type"])

        for rp in related:
            eid = rp["entity_id"]
            tags = list(rp.get("rule_tags", []))
            hops = rp.get("hops", 0)
            rel_types = rp.get("relation_types", [])

            # 规则 1：3跳以内共享法人 → 自动标记关联方
            if hops <= 3 and "legal_rep" in rel_types:
                if "auto_related_by_legal_rep" not in tags:
                    tags.append("auto_related_by_legal_rep")

            # 规则 2：循环持股 → 标记异常
            if "circular_shareholding" in cycle_tags.get(eid, []):
                if "circular_shareholding" not in tags:
                    tags.append("circular_shareholding")

            # 规则 3：交叉担保 → 标记高风险
            if "cross_guarantee" in cycle_tags.get(eid, []):
                if "cross_guarantee" not in tags:
                    tags.append("cross_guarantee")

            # 规则 4：派生共享关系标记
            share_types = {"address_share", "phone_share", "account_share"}
            shared = set(rel_types) & share_types
            if "address_share" in shared:
                tags.append("shared_address")
            if "phone_share" in shared:
                tags.append("shared_phone")
            if "account_share" in shared:
                tags.append("shared_account")

            rp["rule_tags"] = tags

        # 统计有规则标记的关联方数
        net["statistics"]["tagged_count"] = sum(
            1 for rp in related if rp.get("rule_tags")
        )

    return result
