"""自定义阈值分级：基于网络结构指标对供应链节点进行风险分级。

分级维度：
  * risk_score（风险传导得分，0~1）→ critical / high / medium / low
  * concentration_ratio（单一供应商集中度）→ monopoly_risk 标记

分级规则（可被 config.threshold 覆盖）：
  * critical : risk_score ≥ 0.8
  * high     : 0.5 ≤ risk_score < 0.8
  * medium   : 0.3 ≤ risk_score < 0.5
  * low      : risk_score < 0.3
  * concentration_ratio > 0.7 → monopoly_risk = True
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_CRITICAL = 0.8
_DEFAULT_HIGH = 0.5
_DEFAULT_MEDIUM = 0.3
_DEFAULT_CONCENTRATION = 0.7

_VALID_LEVELS = ("critical", "high", "medium", "low")


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对节点风险分级，并计算供应商集中度。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    concentration_limit = float(
        threshold.get("concentration", _DEFAULT_CONCENTRATION)
    )

    edges = result.get("edges", []) or []
    nodes = result.get("nodes", []) or []

    # 构建每个节点的入向供应边（relation_type == supplies）
    incoming: dict[str, list[tuple[str, float]]] = {}
    for e in edges:
        if e.get("relation_type") == "supplies":
            tgt = e.get("target")
            if tgt is None:
                continue
            incoming.setdefault(tgt, []).append(
                (e.get("source"), float(e.get("weight", 1.0)))
            )

    risk_distribution = {lv: 0 for lv in _VALID_LEVELS}
    concentration_ratios: dict[str, float] = {}
    monopoly_count = 0

    for n in nodes:
        sid = n.get("supplier_id")
        score = float(n.get("risk_score", 0.0))
        if score >= critical:
            level = "critical"
        elif score >= high:
            level = "high"
        elif score >= medium:
            level = "medium"
        else:
            level = "low"
        n["risk_level"] = level
        risk_distribution[level] += 1

        # 集中度：该节点入向供应中最大单一供应商的权重占比
        ins = incoming.get(sid, [])
        if ins:
            total_w = sum(w for _, w in ins)
            max_w = max(w for _, w in ins) if ins else 0.0
            ratio = max_w / total_w if total_w > 0 else 0.0
        else:
            ratio = 0.0
        ratio = round(ratio, 4)
        concentration_ratios[sid] = ratio
        n["concentration_ratio"] = ratio
        n["monopoly_risk"] = ratio > concentration_limit
        if n["monopoly_risk"]:
            monopoly_count += 1

    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    summary["risk_distribution"] = risk_distribution
    summary["concentration_threshold"] = concentration_limit
    summary["monopoly_risk_count"] = monopoly_count
    summary["avg_concentration"] = round(
        sum(concentration_ratios.values()) / max(len(concentration_ratios), 1), 4
    )
    summary["thresholds"] = {
        "critical": critical, "high": high, "medium": medium,
        "concentration": concentration_limit,
    }
    result["summary"] = summary
    result["concentration_ratios"] = concentration_ratios
    return result
