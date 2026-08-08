"""自定义业务规则：在 engine + thresholds 之后执行，补充 ESG 采集业务告警。

规则：
  1) 低可信度数据源 → 标记 verification_flag（建议人工复核）
     数据源权重 < low_credibility_threshold（默认 0.6，如新闻媒体/社交媒体）
  2) ESG 指标缺失 → data_gaps（与 GRI 指标标准库比对，未采集到的指标）
  3) 多源数据冲突 → conflict_alerts（同一指标跨源 CV > conflict_cv，默认 0.3）
"""
from __future__ import annotations

from typing import Any

from ..engine import _GRI_METRICS, _SOURCE_WEIGHTS

# 出厂默认阈值
_DEFAULT_LOW_CREDIBILITY = 0.6
_DEFAULT_CONFLICT_CV = 0.3


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用 ESG 采集业务规则：低可信度标记 / 指标缺口 / 多源冲突告警。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    low_cred_threshold = float(
        rules_cfg.get("low_credibility_threshold", _DEFAULT_LOW_CREDIBILITY)
    )
    conflict_cv = float(rules_cfg.get("conflict_cv", _DEFAULT_CONFLICT_CV))

    catalog = result.get("data_catalog", [])
    verification_flags = []
    conflict_alerts = []
    flagged_metrics = set()

    for m in catalog:
        mkey = m.get("metric_key", "")
        source_list = m.get("source_list", [])
        # 规则 1：低可信度数据源 → 标记复核
        low_sources = []
        for src in source_list:
            weight = _SOURCE_WEIGHTS.get(src, 0.6)
            if weight < low_cred_threshold:
                low_sources.append(src)
        if low_sources:
            m["verification_flag"] = True
            m["low_credibility_sources"] = sorted(low_sources)
            verification_flags.append({
                "metric_key": mkey,
                "metric_name": m.get("metric_name", mkey),
                "low_credibility_sources": sorted(low_sources),
            })
            flagged_metrics.add(mkey)
        else:
            m.setdefault("verification_flag", False)
            m.setdefault("low_credibility_sources", [])

        # 规则 3：多源数据冲突（CV 超阈值且来源 ≥2）
        cv = float(m.get("cv", 0.0) or 0.0)
        source_count = int(m.get("source_count", 0) or 0)
        if cv > conflict_cv and source_count >= 2:
            m["conflict_alert"] = True
            conflict_alerts.append({
                "metric_key": mkey,
                "metric_name": m.get("metric_name", mkey),
                "cv": cv,
                "range": m.get("range", [0, 0]),
                "source_count": source_count,
                "source_list": source_list,
            })
            flagged_metrics.add(mkey)
        else:
            m.setdefault("conflict_alert", False)

    # 规则 2：ESG 指标缺口（与标准库比对）
    collected_keys = {m.get("metric_key") for m in catalog}
    data_gaps = []
    for mkey, mdef in _GRI_METRICS.items():
        if mkey not in collected_keys:
            data_gaps.append({
                "metric_key": mkey,
                "metric_name": mdef.get("name", mkey),
                "dimension": mdef.get("dimension", ""),
            })

    result["data_gaps"] = data_gaps
    result["rule_alerts"] = {
        "verification_flags": verification_flags,
        "conflict_alerts": conflict_alerts,
        "data_gap_count": len(data_gaps),
        "verification_flag_count": len(verification_flags),
        "conflict_alert_count": len(conflict_alerts),
        "flagged_metric_keys": sorted(flagged_metrics),
    }
    return result
