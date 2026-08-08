"""自定义业务规则：在 engine 之后执行，标记关键披露风险与监管行动。

规则：
  1) 关键风险标识缺失：未披露条目缺少关联方名称（identifier）→ 升级为 critical_risk
     （关联方名称是披露的基础标识，缺失即构成重大违规）
  2) 多重必填字段缺失：单条 PARTIAL 条目缺失 ≥ 2 个必填字段 → severity 升级为 high
     （多重缺失表明披露流程系统性缺陷）
  3) 完整性低于 60%：触发监管行动要求（regulatory_action_required = True）
     （触发交易所问询函与证监会监管措施的常见门槛）
"""
from __future__ import annotations

from typing import Any

_REGULATORY_ACTION_THRESHOLD = 60.0


def apply_custom_rules(result: Any, config: Any) -> Any:
    """应用业务规则：关键标识缺失 / 多重字段缺失升级 / 监管行动触发。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    reg_threshold = float(
        rules_cfg.get("regulatory_action_threshold", _REGULATORY_ACTION_THRESHOLD)
    )

    items = result.get("items", [])
    critical_count = 0
    escalated_count = 0

    for item in items:
        adjustments = item.setdefault("rule_adjustments", [])
        status = item.get("status", "OK")

        # 规则 1：未披露且缺少关联方名称 → critical_risk
        is_critical = False
        if status == "UNDISCLOSED":
            reason = str(item.get("reason", ""))
            if "未声明关联方名称" in reason or not item.get("related_party"):
                is_critical = True
                critical_count += 1
                item["critical_risk"] = True
                adjustments.append("关键标识缺失(关联方名称)→critical_risk")
            else:
                item["critical_risk"] = False
        else:
            item["critical_risk"] = False

        # 规则 2：PARTIAL 条目缺失 ≥2 个必填字段 → severity 升级为 high
        if status == "PARTIAL":
            missing = item.get("missing_fields", []) or []
            if len(missing) >= 2 and item.get("severity") != "high":
                item["severity"] = "high"
                escalated_count += 1
                adjustments.append(f"多重字段缺失({len(missing)}项)→severity升级high")

    # 规则 3：完整性低于阈值 → 监管行动
    summary = result.get("summary", {})
    completeness = float(summary.get("completeness_score", 100.0) or 100.0)
    regulatory_required = completeness < reg_threshold
    summary["regulatory_action_required"] = regulatory_required
    if regulatory_required:
        summary["regulatory_action_note"] = (
            f"完整性{completeness:.1f}%<{reg_threshold:.0f}%，建议立即启动监管整改"
        )

    summary["rule_adjustments"] = {
        "critical_risk_count": critical_count,
        "severity_escalated_count": escalated_count,
        "regulatory_action_required": regulatory_required,
    }
    result["summary"] = summary

    # 同步 high_risk_items（含升级后的 high + critical）
    result["high_risk_items"] = [
        i for i in items
        if i.get("severity") == "high" and i.get("status") != "OK"
    ]
    return result
