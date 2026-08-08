"""自定义业务规则：在 engine 之后执行，可覆盖/补充舞弊信号检测结果。

规则：
  1) 高严重度欺骗指标 ≥ 3 个 → high_risk_flag（多重舞弊信号叠加）
  2) 模糊用语 + 高严重度财务舞弊关键词并存 → investigate（需重点调查）
  3) 模糊用语关键词命中次数 ≥ 3 → suspicious_hedging（过度模糊用词）
"""
from __future__ import annotations

from typing import Any

_HEDGE_CATEGORY = "模糊用语"
_HEDGE_COUNT_THRESHOLD = 3
_DECEPTION_COUNT_THRESHOLD = 3


def apply_custom_rules(result: Any, config: Any) -> Any:
    """应用业务规则：多重欺骗指标 / 模糊+财务关键词 / 过度模糊用词。"""
    if not isinstance(result, dict):
        return result
    cfg = config if isinstance(config, dict) else {}
    rules_cfg = cfg.get("rules", {}) if isinstance(cfg.get("rules", {}), dict) else {}
    deception_threshold = int(
        rules_cfg.get("deception_count", _DECEPTION_COUNT_THRESHOLD)
    )
    hedge_threshold = int(rules_cfg.get("hedge_count", _HEDGE_COUNT_THRESHOLD))

    detections = result.get("detections", [])
    high_risk_count = 0
    investigate_count = 0
    hedging_count = 0

    for det in detections:
        findings = det.get("findings", []) or []
        high_sev = [f for f in findings if f.get("severity") == "high"]
        hedge_findings = [f for f in findings if f.get("category") == _HEDGE_CATEGORY]
        hedge_hits = sum(f.get("count", 0) for f in hedge_findings)
        has_financial_fraud = bool(high_sev)

        recommendations = det.setdefault("recommendations", [])

        # 规则 1：高严重度欺骗指标 ≥ 3 → high_risk_flag
        if len(high_sev) >= deception_threshold:
            det["high_risk_flag"] = True
            high_risk_count += 1
            recommendations.append("多重舞弊信号叠加，建议立即启动专项核查")
        else:
            det["high_risk_flag"] = False

        # 规则 2：模糊用语 + 财务舞弊关键词 → investigate
        if hedge_findings and has_financial_fraud:
            det["investigate"] = True
            investigate_count += 1
            recommendations.append("模糊用语与财务舞弊关键词并存，建议重点调查")
        else:
            det["investigate"] = False

        # 规则 3：模糊用词命中 ≥ 3 → suspicious_hedging
        if hedge_hits >= hedge_threshold:
            det["suspicious_hedging"] = True
            hedging_count += 1
            recommendations.append("过度使用模糊用词，建议要求对方书面澄清")
        else:
            det["suspicious_hedging"] = False

    # 同步统计
    summary = result.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    summary["rule_flags"] = {
        "high_risk_flagged": high_risk_count,
        "investigate_flagged": investigate_count,
        "hedging_flagged": hedging_count,
    }
    result["summary"] = summary
    return result
