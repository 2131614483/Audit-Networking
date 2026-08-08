"""自定义业务规则：在 engine 之后执行，标记舞弊团伙 / 关键人物 / 有组织舞弊嫌疑。

规则：
  1) 循环交易检测 → fraud_ring_flag（舞弊环标记）
  2) 高中心性高风险实体 → key_person_of_interest（关键嫌疑人）
  3) 社区规模 > 阈值且含高风险实体 → organized_fraud_suspicion（有组织舞弊嫌疑）
  4) 异常交易（z-score）关联实体 → anomaly_entity_flag（异常交易关联标记）
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

_COMMUNITY_SIZE_THRESHOLD = 3  # 社区成员数阈值


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：舞弊环 / 关键人物 / 有组织舞弊 / 异常交易关联标记。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    comm_threshold = int(rules_cfg.get("community_size_threshold", _COMMUNITY_SIZE_THRESHOLD))

    patterns = result.get("patterns", []) or []
    risk_scores = result.get("risk_scores", {}) or {}
    communities = result.get("communities", {}) or {}
    anomalies = result.get("anomalies", []) or []

    rule_flags = []

    # 规则 1：循环交易 → 舞弊环标记
    cycle_patterns = [p for p in patterns if isinstance(p, dict) and p.get("type") == "循环交易"]
    fraud_ring_entities = set()
    for p in cycle_patterns:
        for eid in p.get("entities_involved", []):
            fraud_ring_entities.add(eid)
    fraud_ring_flag = len(cycle_patterns) > 0
    if fraud_ring_flag:
        rule_flags.append({
            "rule": "fraud_ring_detected",
            "detail": f"检测到 {len(cycle_patterns)} 个循环交易，涉及实体 {sorted(fraud_ring_entities)}",
        })

    # 规则 2：高中心性高风险实体 → 关键嫌疑人
    key_entities = [
        eid for eid, rs in risk_scores.items()
        if isinstance(rs, dict)
        and rs.get("network_risk_grade") in ("critical", "high")
        and eid in (result.get("high_centrality_entities") or [])
    ]
    if key_entities:
        rule_flags.append({
            "rule": "key_person_of_interest",
            "detail": f"高中心性高风险实体 {sorted(key_entities)} 标记为关键嫌疑人",
        })

    # 规则 3：社区规模超阈值且含高风险 → 有组织舞弊嫌疑
    comm_members = defaultdict(list)
    for eid, cid in communities.items():
        comm_members[cid].append(eid)
    organized_communities = []
    for cid, members in comm_members.items():
        if len(members) >= comm_threshold:
            high_risk = [
                m for m in members
                if risk_scores.get(m, {}).get("network_risk_grade") in ("critical", "high")
            ]
            if high_risk:
                organized_communities.append({
                    "community_id": cid,
                    "member_count": len(members),
                    "high_risk_members": sorted(high_risk),
                })
    organized_fraud = len(organized_communities) > 0
    if organized_fraud:
        rule_flags.append({
            "rule": "organized_fraud_suspicion",
            "detail": f"{len(organized_communities)} 个社区规模>={comm_threshold} 且含高风险实体，疑似有组织舞弊",
        })

    # 规则 4：异常交易关联实体标记
    anomaly_entities = set()
    for a in anomalies:
        if isinstance(a, dict):
            anomaly_entities.add(a.get("src"))
            anomaly_entities.add(a.get("dst"))
    anomaly_entities.discard(None)
    if anomaly_entities:
        rule_flags.append({
            "rule": "anomaly_entity_flag",
            "detail": f"异常交易关联实体 {sorted(anomaly_entities)} 需重点核查",
        })

    result["fraud_ring_flag"] = fraud_ring_flag
    result["fraud_ring_entities"] = sorted(fraud_ring_entities)
    result["key_persons_flagged"] = sorted(key_entities)
    result["organized_fraud_suspicion"] = organized_fraud
    result["organized_communities"] = organized_communities
    result["anomaly_entities"] = sorted(anomaly_entities)
    result["rule_flags"] = rule_flags
    return result
