"""统一输出格式化：关联方网络图数据 + 路径列表 + 隐藏关联清单 + 统计。"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。

    输出结构：
      {
        "status": "ok",
        "networks": [
          {
            "target_entity_id", "target_name",
            "related_parties": [ {entity_id, name, entity_type, hops, strength,
                                  path, relation_types, tier, is_hidden, rule_tags}, ... ],
            "hidden_links": [ ... ],       # 隐藏关联清单（hops >= 3）
            "cycles": [ ... ],            # 环路检测异常
            "statistics": { total_entities, total_relations, related_count,
                            hidden_count, strong_count, max_hops, cycle_count,
                            tagged_count }
          }, ...
        ],
        "summary": { total_targets, total_related, total_hidden, total_strong,
                     total_cycles, max_hops }
      }
    """
    networks_raw = result.get("networks", []) if isinstance(result, dict) else []

    networks = []
    total_related = 0
    total_hidden = 0
    total_strong = 0
    total_cycles = 0
    global_max_hops = 0

    for net in networks_raw:
        related = net.get("related_parties", [])
        hidden = net.get("hidden_links", [])
        cycles = net.get("cycles", [])
        stats = net.get("statistics", {})

        # 关联方精简输出（保留路径+强度+关系类型+分级+标记）
        related_out = []
        for rp in related:
            related_out.append({
                "entity_id": rp.get("entity_id"),
                "name": rp.get("name"),
                "entity_type": rp.get("entity_type"),
                "hops": rp.get("hops"),
                "strength": rp.get("strength"),
                "path": rp.get("path"),
                "relation_types": rp.get("relation_types"),
                "tier": rp.get("tier"),
                "is_hidden": rp.get("is_hidden", False),
                "rule_tags": rp.get("rule_tags", []),
            })

        # 隐藏关联清单（路径列表）
        hidden_out = []
        for h in hidden:
            hidden_out.append({
                "entity_id": h.get("entity_id"),
                "name": h.get("name"),
                "hops": h.get("hops"),
                "strength": h.get("strength"),
                "path": h.get("path"),
                "relation_types": h.get("relation_types"),
                "rule_tags": h.get("rule_tags", []),
            })

        networks.append({
            "target_entity_id": net.get("target_entity_id"),
            "target_name": net.get("target_name"),
            "related_parties": related_out,
            "hidden_links": hidden_out,
            "cycles": cycles,
            "statistics": stats,
        })

        total_related += stats.get("related_count", 0)
        total_hidden += stats.get("hidden_count", 0)
        total_strong += stats.get("strong_count", 0)
        total_cycles += stats.get("cycle_count", 0)
        global_max_hops = max(global_max_hops, stats.get("max_hops", 0))

    return {
        "status": "ok",
        "networks": networks,
        "summary": {
            "total_targets": len(networks),
            "total_related": total_related,
            "total_hidden": total_hidden,
            "total_strong": total_strong,
            "total_cycles": total_cycles,
            "max_hops": global_max_hops,
        },
    }
