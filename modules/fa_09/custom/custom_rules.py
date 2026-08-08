"""自定义业务规则：在 engine + thresholds 之后执行。

规则：
  1) overall_score < 60 → force_revise = True（强制返工）
  2) 任意维度评分 < 50 → has_critical_dimension = True（维度严重不足）
  3) compliance 维度 < 50 → escalate = True（合规升级处理）
"""
from __future__ import annotations

from typing import Any

_FORCE_REVISE_SCORE = 60.0
_CRITICAL_DIM_SCORE = 50.0
_COMPLIANCE_ESCALATE = 50.0


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：强制返工 / 维度严重不足 / 合规升级。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    force_revise_score = float(rules_cfg.get("force_revise_score", _FORCE_REVISE_SCORE))
    critical_dim = float(rules_cfg.get("critical_dim_score", _CRITICAL_DIM_SCORE))
    compliance_escalate = float(rules_cfg.get("compliance_escalate", _COMPLIANCE_ESCALATE))

    items = result.get("items", [])
    summary = result.get("summary", {})
    force_revise_count = 0
    critical_dim_count = 0
    escalation_count = 0

    for item in items:
        score = float(item.get("overall_score", 0))
        dim_scores = item.get("dimension_scores", {})

        # 规则 1：总分 < 60 → 强制返工
        if score < force_revise_score:
            item["force_revise"] = True
            force_revise_count += 1
        else:
            item["force_revise"] = False

        # 规则 2：任意维度 < 50 → 维度严重不足
        has_critical = any(
            float(s) < critical_dim for s in dim_scores.values()
        )
        item["has_critical_dimension"] = has_critical
        if has_critical:
            critical_dim_count += 1

        # 规则 3：合规维度 ≤ 50 → 升级处理（0 命中时 compliance=50）
        compliance_score = float(dim_scores.get("compliance", 100))
        if compliance_score <= compliance_escalate:
            item["escalate"] = True
            escalation_count += 1
        else:
            item["escalate"] = False

    summary["force_revise_count"] = force_revise_count
    summary["critical_dimension_count"] = critical_dim_count
    summary["escalation_count"] = escalation_count
    result["summary"] = summary
    return result
