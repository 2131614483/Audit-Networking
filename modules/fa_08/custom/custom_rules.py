"""自定义业务规则：在 engine + thresholds 之后执行，可覆盖/补充结果。

规则：
  1) 存在 high 严重度 FAIL → 标记 partner_review_required = True（合伙人复核）
  2) total_diff_amount > 阈值 → 标记 escalation = True（升级处理）
  3) pass_rate < 80% → 标记 warning = True（整体告警）
"""
from __future__ import annotations

from typing import Any

_DEFAULT_ESCALATE_AMOUNT = 500000.0
_DEFAULT_PASS_RATE_WARN = 0.8


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：合伙人复核 / 升级处理 / 整体告警。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    escalate_amount = float(rules_cfg.get("escalate_amount", _DEFAULT_ESCALATE_AMOUNT))
    pr_warn = float(rules_cfg.get("pass_rate_warn", _DEFAULT_PASS_RATE_WARN))

    summary = result.get("summary", {})
    items = result.get("items", [])
    fails = [i for i in items if i.get("status") == "FAIL"]

    # 规则 1：存在 high 严重度失败 → 合伙人复核
    has_high = any(f.get("severity") == "high" for f in fails)
    summary["partner_review_required"] = has_high
    if has_high:
        high_count = sum(1 for f in fails if f.get("severity") == "high")
        summary["partner_review_reason"] = f"存在{high_count}项high严重度勾稽差异"

    # 规则 2：总差异金额超阈值 → 升级处理
    total_diff = float(summary.get("total_diff_amount", 0) or 0)
    if total_diff > escalate_amount:
        summary["escalation"] = True
        summary["escalation_reason"] = (
            f"总差异金额{total_diff:.2f}超过阈值{escalate_amount:.0f}"
        )
    else:
        summary["escalation"] = False

    # 规则 3：通过率 < 阈值 → 整体告警
    pass_rate = float(summary.get("pass_rate", 1.0))
    if pass_rate < pr_warn:
        summary["warning"] = True
        summary["warning_message"] = f"通过率{pass_rate:.1%}低于{pr_warn:.0%}"
    else:
        summary["warning"] = False

    result["summary"] = summary
    return result
