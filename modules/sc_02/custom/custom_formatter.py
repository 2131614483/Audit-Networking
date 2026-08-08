"""统一输出格式化：供应链网络报告（节点 / 边 / 风险热点 / 依赖分析 / 建议）。

输出结构：
  {
    "status": "ok",
    "module": "SC-02",
    "network": {"nodes": [...], "edges": [...]},
    "risk_hotspots": [...],
    "dependency_analysis": { single_source / monopoly / deep_dependency },
    "risk_paths": [...],
    "recommendations": [...],
    "statistics": {...}
  }
"""
from __future__ import annotations

from typing import Any

_HOTSPOT_LEVELS = ("critical", "high")


def format_output(result: Any) -> Any:
    """把内部结果转为对外供应链网络报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    nodes = result.get("nodes", []) or []
    edges = result.get("edges", []) or []
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}

    network_nodes = [
        {
            "supplier_id": n.get("supplier_id"),
            "name": n.get("name"),
            "node_type": n.get("node_type"),
            "pagerank": n.get("pagerank"),
            "community_id": n.get("community_id"),
            "risk_score": n.get("risk_score"),
            "risk_level": n.get("risk_level"),
            "concentration_ratio": n.get("concentration_ratio"),
            "dependency_depth": n.get("dependency_depth"),
            "rule_flags": n.get("rule_flags", []),
        }
        for n in nodes
    ]
    network_edges = [
        {
            "source": e.get("source"),
            "target": e.get("target"),
            "relation_type": e.get("relation_type"),
            "weight": e.get("weight"),
        }
        for e in edges
    ]

    risk_hotspots = [
        {
            "supplier_id": n.get("supplier_id"),
            "name": n.get("name"),
            "risk_score": n.get("risk_score"),
            "risk_level": n.get("risk_level"),
            "pagerank": n.get("pagerank"),
            "community_id": n.get("community_id"),
            "rule_flags": n.get("rule_flags", []),
        }
        for n in nodes if n.get("risk_level") in _HOTSPOT_LEVELS
    ]

    dependency_analysis = {
        "single_source_nodes": [
            {"supplier_id": n.get("supplier_id"), "name": n.get("name")}
            for n in nodes if n.get("single_source_dependency")
        ],
        "monopoly_risk_nodes": [
            {
                "supplier_id": n.get("supplier_id"),
                "name": n.get("name"),
                "concentration_ratio": n.get("concentration_ratio"),
            }
            for n in nodes if n.get("monopoly_risk")
        ],
        "deep_dependency_nodes": [
            {
                "supplier_id": n.get("supplier_id"),
                "name": n.get("name"),
                "dependency_depth": n.get("dependency_depth"),
            }
            for n in nodes if n.get("visibility_risk")
        ],
    }

    recommendations = _build_recommendations(nodes, dependency_analysis, summary)

    statistics = {
        "node_count": summary.get("node_count", len(nodes)),
        "edge_count": summary.get("edge_count", len(edges)),
        "community_count": summary.get("community_count", 0),
        "avg_degree": summary.get("avg_degree", 0),
        "risk_distribution": summary.get("risk_distribution", {}),
        "high_risk_count": summary.get("high_risk_count", 0),
        "monopoly_risk_count": summary.get("monopoly_risk_count", 0),
        "rule_flags": summary.get("rule_flags", {}),
        "community_distribution": summary.get("community_distribution", {}),
        "thresholds": summary.get("thresholds", {}),
    }

    return {
        "status": "ok",
        "module": "SC-02",
        "network": {"nodes": network_nodes, "edges": network_edges},
        "risk_hotspots": risk_hotspots,
        "dependency_analysis": dependency_analysis,
        "risk_paths": result.get("paths", []),
        "recommendations": recommendations,
        "statistics": statistics,
    }


def _build_recommendations(nodes, dependency_analysis, summary) -> list[str]:
    """根据分析结果生成审计建议。"""
    recs: list[str] = []
    single = dependency_analysis.get("single_source_nodes", [])
    monopoly = dependency_analysis.get("monopoly_risk_nodes", [])
    deep = dependency_analysis.get("deep_dependency_nodes", [])

    if single:
        recs.append(
            f"识别到 {len(single)} 个单一来源依赖节点，建议引入备选供应商以降低断供风险"
        )
    if monopoly:
        recs.append(
            f"识别到 {len(monopoly)} 个供应商集中度超 70% 的节点，"
            "建议分散采购份额以避免垄断依赖"
        )
    if deep:
        recs.append(
            f"识别到 {len(deep)} 个多层级依赖过深（>5 层）的节点，"
            "建议建立 N+1 级供应商可见性机制"
        )
    high_risk = summary.get("high_risk_count", 0)
    if high_risk:
        recs.append(
            f"共 {high_risk} 个高风险节点，建议优先开展现场审计与风险缓释"
        )
    comm_count = summary.get("community_count", 0)
    if comm_count > 1:
        recs.append(
            f"网络划分为 {comm_count} 个供应社区，建议按社区制定差异化监控策略"
        )
    if not recs:
        recs.append("供应链网络整体风险可控，建议维持常规监控节奏")
    return recs
