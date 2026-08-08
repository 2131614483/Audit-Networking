"""自定义业务规则：在 engine 之后执行，可覆盖/补充影响评估。

规则：
  1) 缺失强制义务条款 → 标记 severity=critical（必须立即整改）
  2) 处罚金额/比例超过阈值 → 标记 high_penalty_risk
  3) 差距率超过阈值或缺失义务数过多 → 整体影响等级升级为 high
"""
from __future__ import annotations

import re
from typing import Any

_LARGE_PENALTY = 1_000_000.0   # 处罚金额阈值：100万元
_HIGH_PENALTY_RATIO = 10.0     # 处罚比例阈值：10%
_GAP_RATE_ESCALATE = 60.0      # 差距率阈值：60%
_MISSING_ESCALATE = 3          # 缺失义务数阈值


def _parse_penalty_amount(text: str) -> float:
    """从处罚文本中估算金额（元），取最大值。"""
    if not text:
        return 0.0
    amount = 0.0
    for m in re.finditer(r"(\d+[\.,]?\d*)\s*(万|亿|元)", text):
        v = float(m.group(1).replace(",", ""))
        unit = m.group(2)
        if unit == "万":
            amount = max(amount, v * 10000)
        elif unit == "亿":
            amount = max(amount, v * 100000000)
        else:
            amount = max(amount, v)
    return amount


def _parse_penalty_ratio(text: str) -> float:
    """从处罚文本中估算比例（%），取最大值。"""
    if not text:
        return 0.0
    ratio = 0.0
    for m in re.finditer(r"(\d+[\.,]?\d*)\s*%", text):
        ratio = max(ratio, float(m.group(1).replace(",", "")))
    return ratio


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：缺失义务升级 / 处罚风险标记 / 差距率整体升级。"""
    if not isinstance(result, dict):
        return result

    # parse 模式无差距/影响数据，直接返回
    if "impact_assessment" not in result:
        return result

    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    large_penalty = float(rules_cfg.get("large_penalty", _LARGE_PENALTY))
    high_ratio = float(rules_cfg.get("high_penalty_ratio", _HIGH_PENALTY_RATIO))
    gap_rate_escalate = float(rules_cfg.get("gap_rate_escalate", _GAP_RATE_ESCALATE))
    missing_escalate = int(rules_cfg.get("missing_escalate", _MISSING_ESCALATE))

    gaps = result.get("gap_analysis", {}) or {}
    impact = result.get("impact_assessment", {}) or {}
    details = gaps.get("details", []) or []
    rule_flags: list[str] = []

    # 规则 1：缺失强制义务 → critical
    critical_gaps = 0
    for g in details:
        if g.get("gap_type") == "missing":
            g["severity"] = "critical"
            critical_gaps += 1
        else:
            g.setdefault("severity", "normal")
    if critical_gaps:
        rule_flags.append(f"发现{critical_gaps}项缺失强制义务→critical")

    # 规则 2：处罚金额/比例超阈值 → high_penalty_risk
    penalty_details = impact.get("penalty_clause_details", []) or []
    high_penalty_clauses = 0
    for pc in penalty_details:
        pen_text = pc.get("penalty", "") or ""
        amt = _parse_penalty_amount(pen_text)
        ratio = _parse_penalty_ratio(pen_text)
        if amt >= large_penalty or ratio >= high_ratio:
            pc["high_penalty_risk"] = True
            if amt >= large_penalty:
                pc["estimated_penalty_amount"] = amt
            if ratio >= high_ratio:
                pc["estimated_penalty_ratio"] = ratio
            high_penalty_clauses += 1
            rule_flags.append(
                f"处罚金额{amt:.0f}元/比例{ratio}%超阈值→high_penalty_risk"
            )
        else:
            pc.setdefault("high_penalty_risk", False)

    # 规则 3：差距率过高 / 缺失过多 → 整体升级
    gap_rate = float(gaps.get("gap_rate", 0) or 0)
    missing_count = int(gaps.get("gaps_by_type", {}).get("missing", 0) or 0)
    escalated = False
    if gap_rate >= gap_rate_escalate or missing_count >= missing_escalate:
        if impact.get("overall_level") != "high":
            impact["overall_level"] = "high"
            impact["impact_score"] = max(
                float(impact.get("impact_score", 0) or 0), 75.0
            )
            escalated = True
            rule_flags.append(
                f"差距率{gap_rate}%/缺失{missing_count}项→整体影响升级high"
            )

    impact["critical_gap_count"] = critical_gaps
    impact["high_penalty_clause_count"] = high_penalty_clauses
    impact["level_escalated"] = escalated
    result["impact_assessment"] = impact

    # 同步执行摘要
    summary = result.get("executive_summary", {})
    if isinstance(summary, dict):
        summary["overall_impact_level"] = impact.get("overall_level", "unknown")
        summary["critical_gap_count"] = critical_gaps
        result["executive_summary"] = summary

    result["custom_rule_flags"] = rule_flags
    return result
