"""自定义业务规则：在 engine 之后执行，可覆盖/补充 SAR 告警。

规则：
  1) 大额交易（金额超过报告阈值）→ 强制人工复核 need_review=True
  2) 跨境高风险地区交易 → 升级为 critical 并标记 cross_border=True
  3) 结构化分层模式（同一客户同时触发 Smurfing + Round-trip）→ 标记 organized_layering=True
"""
from __future__ import annotations

from typing import Any

_DEFAULT_REPORT_THRESHOLD = 50000.0


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：大额复核 / 跨境升级 / 结构化分层标记。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    report_threshold = float(
        rules_cfg.get("report_threshold", _DEFAULT_REPORT_THRESHOLD)
    )

    sars = result.get("sars", [])
    # 收集每个客户命中的模式集合（用于规则 3）
    customer_patterns: dict[str, set[str]] = {}
    for s in sars:
        cid = str(s.get("customer_id", "?"))
        pattern = s.get("pattern", "")
        customer_patterns.setdefault(cid, set()).add(pattern)

    review_count = 0
    escalated_count = 0
    organized_count = 0

    for s in sars:
        adjustments = s.setdefault("rule_adjustments", [])
        cid = str(s.get("customer_id", "?"))
        amt = float(s.get("amount", 0) or s.get("total_amount", 0) or 0)
        pattern = s.get("pattern", "")

        # 规则 1：大额交易强制人工复核
        if amt > report_threshold:
            s["need_review"] = True
            review_count += 1
            adjustments.append(f"金额>{report_threshold:.0f}强制人工复核")
        else:
            s.setdefault("need_review", False)

        # 规则 2：跨境高风险地区交易 → 升级为 critical
        if "高风险地区" in pattern:
            s["cross_border"] = True
            s["alert_level"] = "critical"
            escalated_count += 1
            adjustments.append("跨境高风险地区升级critical")
        else:
            s.setdefault("cross_border", False)

        # 规则 3：结构化分层模式（Smurfing + Round-trip 同时命中同一客户）
        patterns_hit = customer_patterns.get(cid, set())
        if ("结构化交易（Smurfing）" in patterns_hit
                and "快速往返（Round-trip）" in patterns_hit):
            s["organized_layering"] = True
            organized_count += 1
            adjustments.append("结构化分层模式(Smurfing+Round-trip)标记")
        else:
            s.setdefault("organized_layering", False)

    # 同步 summary
    summary = result.get("summary", {})
    summary["rule_adjustments"] = {
        "need_review": review_count,
        "cross_border_escalated": escalated_count,
        "organized_layering": organized_count,
    }
    result["summary"] = summary
    return result
