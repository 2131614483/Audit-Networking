"""自定义阈值分级：根据 config 阈值对勾稽差异进行严重度升级与置信度分级。

分级规则（可被 config.threshold 覆盖）：
  * diff_escalate (默认 100000)：差异金额 ≥ 此值的中等严重度项升级为 high
  * pass_rate_warning (默认 0.8)：通过率低于此值标记 confidence_level = warning
  * pass_rate_critical (默认 0.5)：通过率低于此值标记 confidence_level = critical
"""
from __future__ import annotations

from collections import Counter
from typing import Any

_DEFAULT_DIFF_ESCALATE = 100000.0
_DEFAULT_PASS_RATE_WARNING = 0.8
_DEFAULT_PASS_RATE_CRITICAL = 0.5


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值重新分级失败项，并计算整体置信度。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    diff_escalate = float(threshold.get("diff_escalate", _DEFAULT_DIFF_ESCALATE))
    pr_warning = float(threshold.get("pass_rate_warning", _DEFAULT_PASS_RATE_WARNING))
    pr_critical = float(threshold.get("pass_rate_critical", _DEFAULT_PASS_RATE_CRITICAL))

    items = result.get("items", [])
    # 严重度升级：medium 且 |diff_amount| ≥ 阈值 → high
    escalated = 0
    for item in items:
        if item.get("status") == "FAIL" and item.get("severity") == "medium":
            if abs(float(item.get("diff_amount", 0) or 0)) >= diff_escalate:
                item["severity"] = "high"
                item.setdefault("rule_adjustments", []).append(
                    f"差异金额≥{diff_escalate:.0f}升级为high"
                )
                escalated += 1

    # 重算 severity_distribution（仅 FAIL 项）
    fails = [i for i in items if i.get("status") == "FAIL"]
    summary = result.get("summary", {})
    summary["severity_distribution"] = dict(Counter(f["severity"] for f in fails))

    # 置信度分级
    pass_rate = float(summary.get("pass_rate", 1.0))
    if pass_rate < pr_critical:
        confidence = "critical"
    elif pass_rate < pr_warning:
        confidence = "warning"
    else:
        confidence = "ok"
    summary["confidence_level"] = confidence
    summary["thresholds"] = {
        "diff_escalate": diff_escalate,
        "pass_rate_warning": pr_warning,
        "pass_rate_critical": pr_critical,
    }
    summary["escalated_count"] = escalated
    result["summary"] = summary

    # 重算 critical_issues（升级后可能新增 high 项）
    result["critical_issues"] = [i for i in fails if i.get("severity") == "high"]
    return result
