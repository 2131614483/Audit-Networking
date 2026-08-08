"""统一输出格式化：舞弊网络报告（实体 / 关系 / 社区 / 关键发现 / 可视化数据）。

输出结构：
  {
    "status": "ok",
    "module": "FO-02",
    "summary": {entity/transaction/community/anomaly/pattern counts, network_risk_level},
    "key_findings": {fraud_ring, organized_fraud, key_persons, anomaly_entities},
    "entities": [{entity_id, name, type, risk...}, ...],
    "relationships": [{src, dst, amount, time, txn_type}, ...],
    "communities": [{community_id, members, member_count, risk_level}, ...],
    "anomalies": [...],
    "patterns": [...],
    "visualization": {nodes, edges, communities}
  }
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _build_entities_list(result: dict) -> list[dict]:
    """构造实体列表（含风险评分）。"""
    entities = result.get("entities", {}) or {}
    risk_scores = result.get("risk_scores", {}) or {}
    out = []
    for eid, ent in entities.items():
        rs = risk_scores.get(eid, {}) or {}
        out.append({
            "entity_id": eid,
            "name": ent.get("name", eid),
            "type": ent.get("type", ""),
            "industry": ent.get("industry", ""),
            "country": ent.get("country", ""),
            "risk_score": rs.get("total"),
            "risk_level": rs.get("level"),
            "network_risk_grade": rs.get("network_risk_grade"),
            "pagerank": rs.get("pagerank"),
        })
    return out


def _build_communities_list(result: dict) -> list[dict]:
    """构造社区列表。"""
    communities = result.get("communities", {}) or {}
    entities = result.get("entities", {}) or {}
    community_risk = result.get("community_risk", {}) or {}
    members_by_cid = defaultdict(list)
    for eid, cid in communities.items():
        members_by_cid[cid].append({
            "entity_id": eid,
            "name": entities.get(eid, {}).get("name", eid),
        })
    out = []
    for cid, members in members_by_cid.items():
        cr = community_risk.get(cid, {}) or {}
        out.append({
            "community_id": cid,
            "member_count": len(members),
            "members": members,
            "risk_level": cr.get("level", ""),
            "high_risk_ratio": cr.get("high_risk_ratio", 0),
        })
    return out


def _build_visualization(result: dict) -> dict:
    """构造可视化数据（nodes / edges / communities 着色映射）。"""
    entities = result.get("entities", {}) or {}
    risk_scores = result.get("risk_scores", {}) or {}
    communities = result.get("communities", {}) or {}
    nodes = [
        {
            "id": eid,
            "label": ent.get("name", eid),
            "type": ent.get("type", ""),
            "risk_level": risk_scores.get(eid, {}).get("level", ""),
            "community": communities.get(eid, ""),
        }
        for eid, ent in entities.items()
    ]
    edges = [
        {
            "source": e.get("src"),
            "target": e.get("dst"),
            "amount": e.get("amount"),
            "time": e.get("time"),
            "txn_type": e.get("txn_type"),
        }
        for e in result.get("edges", []) or []
    ]
    return {"nodes": nodes, "edges": edges, "community_map": dict(communities)}


def format_output(result: Any) -> Any:
    """把内部结果转为对外舞弊网络报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    summary = result.get("summary", {}) or {}

    key_findings = {
        "fraud_ring_flag": result.get("fraud_ring_flag", False),
        "fraud_ring_entities": result.get("fraud_ring_entities", []),
        "organized_fraud_suspicion": result.get("organized_fraud_suspicion", False),
        "key_persons_of_interest": result.get("key_persons_of_interest", []),
        "key_persons_flagged": result.get("key_persons_flagged", []),
        "anomaly_entities": result.get("anomaly_entities", []),
        "network_risk_grades": result.get("network_risk_grades", {}),
        "rule_flags": result.get("rule_flags", []),
    }

    return {
        "status": "ok",
        "module": "FO-02",
        "summary": {
            "entity_count": summary.get("entity_count", 0),
            "transaction_count": summary.get("transaction_count", 0),
            "community_count": summary.get("community_count", 0),
            "anomaly_count": summary.get("anomaly_count", 0),
            "pattern_count": summary.get("pattern_count", 0),
            "high_risk_entities": summary.get("high_risk_entities", 0),
            "total_volume": summary.get("total_volume", 0),
            "network_risk_level": summary.get("network_risk_level", ""),
        },
        "key_findings": key_findings,
        "entities": _build_entities_list(result),
        "relationships": [
            {"src": e.get("src"), "dst": e.get("dst"), "amount": e.get("amount"),
             "time": e.get("time"), "txn_type": e.get("txn_type"), "note": e.get("note")}
            for e in result.get("edges", []) or []
        ],
        "communities": _build_communities_list(result),
        "anomalies": result.get("anomalies", []),
        "patterns": result.get("patterns", []),
        "visualization": _build_visualization(result),
    }
