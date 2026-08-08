"""自定义阈值分级：基于网络中心性与社区风险的舞弊风险分级。

分级规则（可被 config.threshold 覆盖）：
  * 根据 risk_scores.total 与 pagerank 综合判定每个实体的 network_risk_grade：
      - critical : total >= 0.7  → 关键节点
      - high     : 0.45 <= total < 0.7 → 重点嫌疑人
      - medium   : 0.3 <= total < 0.45 → 关注对象
      - low      : total < 0.3        → 一般对象
  * 标记 key_persons_of_interest（高中心性 + 高风险实体）
  * 计算社区风险：高风险实体占比 → community_risk_level
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

_DEFAULT_CRITICAL = 0.7
_DEFAULT_HIGH = 0.45
_DEFAULT_MEDIUM = 0.3
_DEFAULT_PAGERANK_TOP = 0.15  # PageRank 前 15% 视为高中心性


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对实体进行网络风险分级与关键人物标记。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    pr_top = float(threshold.get("pagerank_top", _DEFAULT_PAGERANK_TOP))

    risk_scores = result.get("risk_scores", {}) or {}
    entities = result.get("entities", {}) or {}
    communities = result.get("communities", {}) or {}
    n = len(risk_scores)

    # 按 pagerank 排序，取前 pr_top 比例为高中心性
    pr_sorted = sorted(risk_scores.items(), key=lambda kv: kv[1].get("pagerank", 0), reverse=True)
    pr_top_count = max(1, int(n * pr_top)) if n else 0
    high_centrality_ids = {eid for eid, _ in pr_sorted[:pr_top_count]}

    grade_counts = Counter()
    key_persons = []
    for eid, rs in risk_scores.items():
        total = float(rs.get("total", 0) or 0)
        if total >= critical:
            grade = "critical"
            grade_label = "关键节点"
        elif total >= high:
            grade = "high"
            grade_label = "重点嫌疑人"
        elif total >= medium:
            grade = "medium"
            grade_label = "关注对象"
        else:
            grade = "low"
            grade_label = "一般对象"
        rs["network_risk_grade"] = grade
        rs["network_risk_grade_label"] = grade_label
        grade_counts[grade] += 1

        # 关键人物：高中心性 + (critical 或 high)
        if eid in high_centrality_ids and grade in ("critical", "high"):
            key_persons.append({
                "entity_id": eid,
                "name": entities.get(eid, {}).get("name", eid),
                "total": round(total, 4),
                "pagerank": rs.get("pagerank", 0),
                "grade": grade,
            })

    # 社区风险：统计每个社区的高风险实体占比
    comm_members = defaultdict(list)
    for eid, cid in communities.items():
        comm_members[cid].append(eid)
    community_risk = {}
    for cid, members in comm_members.items():
        high_risk_in_comm = sum(
            1 for m in members
            if risk_scores.get(m, {}).get("network_risk_grade") in ("critical", "high")
        )
        ratio = high_risk_in_comm / max(len(members), 1)
        if ratio >= 0.5:
            level = "高风险社区"
        elif ratio >= 0.25:
            level = "中风险社区"
        else:
            level = "低风险社区"
        community_risk[cid] = {
            "member_count": len(members),
            "high_risk_count": high_risk_in_comm,
            "high_risk_ratio": round(ratio, 3),
            "level": level,
        }

    result["network_risk_grades"] = dict(grade_counts)
    result["key_persons_of_interest"] = key_persons
    result["high_centrality_entities"] = sorted(high_centrality_ids)
    result["community_risk"] = community_risk
    result["applied_thresholds"] = {
        "critical": critical, "high": high, "medium": medium,
        "pagerank_top": pr_top,
    }
    return result
