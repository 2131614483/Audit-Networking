"""统一输出格式化：法规分析 + 差距分析 + 影响评分 + 整改方案。

输出结构（assess 模式）：
  {
    "status": "ok",
    "module": "CO-02",
    "executive_summary": { regulation, total_clauses_analyzed, overall_impact_level, ... },
    "regulation_analysis": { clause_count, structure, key_obligations, penalty_clauses },
    "gap_analysis": { total_obligations, gaps_by_type, gap_rate, critical_gaps },
    "impact_assessment": { impact_score, overall_level, cost_estimation, ... },
    "remediation_plan": [ {priority, action_type, responsible_team, ...}, ... ],
    "custom_rule_flags": [...],
  }

输出结构（parse 模式）：
  {
    "status": "ok",
    "module": "CO-02",
    "regulation_title": "...",
    "clauses": [ {clause_id, text, type, penalty, applicable_entities}, ... ],
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    # parse 模式（无 impact_assessment）
    if "clauses" in result and "impact_assessment" not in result:
        return _format_parse_output(result)
    # assess 模式
    return _format_assess_output(result)


def _format_parse_output(result: dict) -> dict:
    """parse 模式输出：条款结构化列表。"""
    clauses = result.get("clauses", []) or []
    return {
        "status": "ok",
        "module": "CO-02",
        "regulation_title": result.get("regulation_title", ""),
        "executive_summary": result.get("executive_summary", {}),
        "clause_count": len(clauses),
        "structure": _structure_summary(clauses),
        "clauses": [
            {
                "clause_id": c.get("clause_id"),
                "type": c.get("type"),
                "text": c.get("text"),
                "penalty": c.get("penalty", ""),
                "applicable_entities": c.get("applicable_entities", []),
            }
            for c in clauses
        ],
    }


def _format_assess_output(result: dict) -> dict:
    """assess 模式输出：影响评估报告。"""
    clauses = result.get("key_obligations", []) or []
    gaps = result.get("gap_analysis", {}) or {}
    impact = result.get("impact_assessment", {}) or {}
    recs = result.get("recommendations", []) or []

    # 法规分析
    structure = result.get("regulation_structure", {})
    if not isinstance(structure, dict):
        structure = dict(structure) if structure else {}
    penalty_clauses = [
        {
            "clause_id": pc.get("clause_id"),
            "text": pc.get("text"),
            "penalty": pc.get("penalty", ""),
            "high_penalty_risk": pc.get("high_penalty_risk", False),
        }
        for pc in (impact.get("penalty_clause_details", []) or [])
    ]

    # 差距分析
    details = gaps.get("details", []) or []
    critical_gaps = sum(1 for g in details if g.get("severity") == "critical")

    # 影响评估
    cost = impact.get("cost_estimation", {}) or {}

    # 整改方案
    remediation_plan = [
        {
            "priority": r.get("priority"),
            "clause_id": r.get("clause_id"),
            "action_type": r.get("action_type"),
            "action_detail": r.get("action_detail"),
            "responsible_team": r.get("responsible_team"),
            "estimated_effort": r.get("estimated_effort"),
        }
        for r in recs
    ]

    return {
        "status": "ok",
        "module": "CO-02",
        "executive_summary": result.get("executive_summary", {}),
        "regulation_analysis": {
            "title": result.get("regulation_title", ""),
            "clause_count": result.get("clause_count", 0),
            "structure": dict(structure),
            "key_obligations_count": len(clauses),
            "penalty_clauses": penalty_clauses,
        },
        "gap_analysis": {
            "total_obligations": gaps.get("total_obligations", 0),
            "gaps_by_type": gaps.get("gaps_by_type", {}),
            "gap_rate": gaps.get("gap_rate", 0.0),
            "critical_gaps": critical_gaps,
            "details": [
                {
                    "clause_id": g.get("clause_id"),
                    "gap_type": g.get("gap_type"),
                    "severity": g.get("severity", "normal"),
                    "confidence": g.get("confidence"),
                    "semantic_similarity": g.get("semantic_similarity"),
                    "keyword_coverage": g.get("keyword_coverage"),
                    "gap_detail": g.get("gap_detail"),
                }
                for g in details
            ],
        },
        "impact_assessment": {
            "impact_score": impact.get("impact_score"),
            "overall_level": impact.get("overall_level", "unknown"),
            "requires_immediate_action": impact.get("requires_immediate_action", False),
            "missing_clauses": impact.get("missing_clauses", 0),
            "partial_clauses": impact.get("partial_clauses", 0),
            "high_risk_clauses": impact.get("high_risk_clauses", 0),
            "critical_gap_count": impact.get("critical_gap_count", 0),
            "high_penalty_clause_count": impact.get("high_penalty_clause_count", 0),
            "level_escalated": impact.get("level_escalated", False),
            "cost_estimation": {
                "effort_months": cost.get("effort_months"),
                "required_team_size": cost.get("required_team_size"),
                "primary_systems_affected": cost.get("primary_systems_affected", []),
            },
            "thresholds": impact.get("thresholds", {}),
        },
        "remediation_plan": remediation_plan,
        "custom_rule_flags": result.get("custom_rule_flags", []),
    }


def _structure_summary(clauses: list[dict]) -> dict:
    """统计条款类型分布。"""
    counts: dict[str, int] = {}
    for c in clauses:
        t = c.get("type", "other")
        counts[t] = counts.get(t, 0) + 1
    return counts
