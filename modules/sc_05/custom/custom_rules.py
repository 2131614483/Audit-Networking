"""自定义业务规则：在 engine 之后执行，补充基准对标业务标记。

规则：
  1) 基准覆盖率 < 60% → data_gap_alert（数据缺口告警，summary 级）
  2) 当前价 > 品类 P90 → expensive_p90（偏贵标记）
  3) 历史趋势下降且累计降幅 > 10% → renegotiate_opportunity（议价机会）
"""
from __future__ import annotations

from typing import Any

_COVERAGE_THRESHOLD = 0.60   # 基准覆盖率下限
_DECLINE_THRESHOLD = 0.10    # 累计降幅阈值


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：数据缺口告警 / P90偏贵 / 下降趋势议价。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    coverage_min = float(rules_cfg.get("coverage_min", _COVERAGE_THRESHOLD))
    decline_min = float(rules_cfg.get("decline_min", _DECLINE_THRESHOLD))

    results = result.get("results", [])

    # 规则 1：基准覆盖率 < coverage_min → 数据缺口告警
    total = len(results)
    with_baseline = sum(
        1 for r in results if r.get("deviation_pct") is not None
    )
    coverage = with_baseline / total if total > 0 else 0.0
    data_gap_alert = (total > 0 and coverage < coverage_min)

    expensive_p90_count = 0
    renegotiate_count = 0
    for r in results:
        adjustments = r.setdefault("rule_flags", [])
        r.setdefault("expensive_p90", False)
        r.setdefault("renegotiate_opportunity", False)
        bl = r.get("baseline")
        if not isinstance(bl, dict):
            continue

        # 规则 2：当前价 > P90 → 偏贵
        pcts = bl.get("percentiles", {}) or {}
        p90 = pcts.get("90") or pcts.get(90)
        test_price = float(r.get("test_price", 0) or 0)
        if p90 is not None and test_price > float(p90):
            r["expensive_p90"] = True
            expensive_p90_count += 1
            adjustments.append(f"价格高于品类P90({p90})")

        # 规则 3：历史趋势下降且累计降幅 > decline_min → 议价机会
        if bl.get("trend_direction") == "下降":
            slope = float(bl.get("trend_slope", 0) or 0)
            mean = float(bl.get("mean", 0) or 0)
            n = int(bl.get("sample_count", 0) or 0)
            if mean > 0 and n > 1:
                relative_decline = abs(slope) * (n - 1) / mean
                if relative_decline > decline_min:
                    r["renegotiate_opportunity"] = True
                    renegotiate_count += 1
                    adjustments.append(
                        f"历史价格下降趋势累计降幅"
                        f"{relative_decline * 100:.1f}%(>{decline_min * 100:.0f}%),建议议价"
                    )

    # 同步统计
    summary = result.get("summary", {})
    summary["benchmark_coverage"] = round(coverage, 4)
    summary["data_gap_alert"] = data_gap_alert
    summary["rule_flags"] = {
        "expensive_p90": expensive_p90_count,
        "renegotiate_opportunity": renegotiate_count,
    }
    result["summary"] = summary
    return result
