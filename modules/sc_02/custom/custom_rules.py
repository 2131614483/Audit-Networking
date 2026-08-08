"""自定义业务规则：在 engine/threshold 之后执行，覆盖/补充供应链风险标记。

规则：
  1) 单一来源依赖（single_source_dependency）：节点仅有 1 个入向 supplies 边
     → 高依赖风险，风险等级升级为 high
  2) 供应商集中度超标（monopoly_concentration）：单一供应商占比 > 70%
     → 垄断风险标记
  3) 多层级依赖过深（visibility_depth_exceeded）：上游供应链深度 > 5
     → 可见性风险标记，风险等级升级
"""
from __future__ import annotations

from typing import Any

_DEFAULT_SINGLE_SOURCE_COUNT = 1
_DEFAULT_CONCENTRATION = 0.7
_DEFAULT_VISIBILITY_DEPTH = 5
_MAX_DEPTH_SEARCH = 12

# 风险等级升级顺序（low → high）
_LEVEL_ORDER = ["low", "medium", "high", "critical"]


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用供应链业务规则：单一来源 / 集中度 / 多层级深度。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    single_source_count = int(
        rules_cfg.get("single_source_count", _DEFAULT_SINGLE_SOURCE_COUNT)
    )
    concentration_limit = float(
        rules_cfg.get("concentration", _DEFAULT_CONCENTRATION)
    )
    visibility_depth = int(
        rules_cfg.get("visibility_depth", _DEFAULT_VISIBILITY_DEPTH)
    )

    edges = result.get("edges", []) or []
    nodes = result.get("nodes", []) or []

    # 构建供应关系上游邻接表（target → [source]），用于深度计算
    supply_upstream: dict[str, list[str]] = {}
    supply_incoming: dict[str, list[tuple[str, float]]] = {}
    for e in edges:
        if e.get("relation_type") == "supplies":
            src = e.get("source")
            tgt = e.get("target")
            if src is None or tgt is None:
                continue
            supply_upstream.setdefault(tgt, []).append(src)
            supply_incoming.setdefault(tgt, []).append(
                (src, float(e.get("weight", 1.0)))
            )

    rule_flags = {
        "single_source_dependency": 0,
        "monopoly_concentration": 0,
        "visibility_depth_exceeded": 0,
    }

    for n in nodes:
        sid = n.get("supplier_id")
        flags = n.setdefault("rule_flags", [])

        # 规则 1：单一来源依赖
        suppliers_list = supply_incoming.get(sid, [])
        if 0 < len(suppliers_list) <= single_source_count:
            n["single_source_dependency"] = True
            flags.append("single_source_dependency")
            rule_flags["single_source_dependency"] += 1
            _escalate(n, target="high")
        else:
            n["single_source_dependency"] = False

        # 规则 2：供应商集中度超标（monopoly_risk 由 thresholds 计算）
        if n.get("monopoly_risk"):
            flags.append("monopoly_concentration")
            rule_flags["monopoly_concentration"] += 1

        # 规则 3：多层级依赖深度过深
        depth = _max_supply_depth(sid, supply_upstream)
        n["dependency_depth"] = depth
        if depth > visibility_depth:
            n["visibility_risk"] = True
            flags.append("visibility_depth_exceeded")
            rule_flags["visibility_depth_exceeded"] += 1
            _escalate(n, target="high")
        else:
            n["visibility_risk"] = False

    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    summary["rule_flags"] = rule_flags
    result["summary"] = summary
    return result


def _escalate(node: dict, target: str) -> None:
    """把节点风险等级升级到至少 target 级别。"""
    cur = node.get("risk_level", "low")
    if cur not in _LEVEL_ORDER or target not in _LEVEL_ORDER:
        return
    if _LEVEL_ORDER.index(cur) < _LEVEL_ORDER.index(target):
        node["risk_level"] = target


def _max_supply_depth(start: str, supply_upstream: dict) -> int:
    """从 start 节点沿上游供应链计算最大依赖深度（迭代 DFS，含环保护）。"""
    if start is None:
        return 0
    visited: set[str] = set()
    stack: list[tuple[str, int]] = [(start, 0)]
    max_d = 0
    while stack:
        cur, d = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        if d > max_d:
            max_d = d
        if d >= _MAX_DEPTH_SEARCH:
            continue
        for src in supply_upstream.get(cur, []):
            if src not in visited:
                stack.append((src, d + 1))
    return max_d
