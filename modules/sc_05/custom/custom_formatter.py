"""统一输出格式化：品类基准 + 价格对标 + 趋势分析 + 业务建议。

输出结构：
  {
    "status": "ok",
    "module": "SC-05",
    "category_benchmarks": [ {category, baseline_price, low_bound, high_bound,
                             percentiles, trend_direction, ...}, ... ],
    "price_comparisons": [ {benchmark_id, category, test_price, baseline_price,
                            deviation_pct, position, grade, rule_flags, ...}, ... ],
    "trend_analysis": { stable_categories, unstable_categories, declining_categories },
    "recommendations": [ ... ],
    "statistics": { category_count, query_count, grade_distribution,
                    benchmark_coverage, data_gap_alert, rule_flags }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    summary = result.get("summary", {})
    baselines = result.get("baselines", {})
    results = result.get("results", [])

    # 品类基准表
    category_benchmarks = []
    for cat, bl in baselines.items():
        category_benchmarks.append({
            "category": cat,
            "sample_count": bl.get("sample_count", 0),
            "mean": bl.get("mean"),
            "median": bl.get("median"),
            "std": bl.get("std"),
            "baseline_price": bl.get("baseline_price"),
            "low_bound": bl.get("low_bound"),
            "high_bound": bl.get("high_bound"),
            "percentiles": bl.get("percentiles", {}),
            "trend_slope": bl.get("trend_slope"),
            "trend_r2": bl.get("trend_r2"),
            "trend_stable": bl.get("trend_stable"),
            "trend_direction": bl.get("trend_direction"),
        })

    # 价格对标明细
    price_comparisons = []
    for r in results:
        price_comparisons.append({
            "benchmark_id": r.get("benchmark_id"),
            "category": r.get("category"),
            "test_price": r.get("test_price"),
            "baseline_price": r.get("baseline_price"),
            "deviation_pct": r.get("deviation_pct"),
            "position": r.get("position") or r.get("status"),
            "grade": r.get("grade", "no_data"),
            "assessment": r.get("assessment", ""),
            "confirmed_deviation": r.get("confirmed_deviation", False),
            "expensive_p90": r.get("expensive_p90", False),
            "renegotiate_opportunity": r.get("renegotiate_opportunity", False),
            "rule_flags": r.get("rule_flags", []),
        })

    # 趋势分析
    trend_analysis = _build_trend_analysis(baselines)

    # 业务建议
    recommendations = _build_recommendations(summary, baselines, results)

    return {
        "status": "ok",
        "module": "SC-05",
        "category_benchmarks": category_benchmarks,
        "price_comparisons": price_comparisons,
        "trend_analysis": trend_analysis,
        "recommendations": recommendations,
        "statistics": {
            "category_count": summary.get("category_count", 0),
            "query_count": summary.get("query_count", 0),
            "assessments": summary.get("assessments", {}),
            "grade_distribution": summary.get("grade_distribution", {}),
            "benchmark_coverage": summary.get("benchmark_coverage", 0.0),
            "data_gap_alert": summary.get("data_gap_alert", False),
            "rule_flags": summary.get("rule_flags", {}),
            "thresholds": summary.get("thresholds", {}),
        },
    }


def _build_trend_analysis(baselines: dict) -> dict:
    """汇总趋势分析：稳定/不稳定/下降品类。"""
    stable = []
    unstable = []
    declining = []
    for cat, bl in baselines.items():
        if bl.get("trend_stable"):
            stable.append(cat)
        else:
            unstable.append(cat)
        if bl.get("trend_direction") == "下降":
            declining.append(cat)
    return {
        "stable_categories": stable,
        "unstable_categories": unstable,
        "declining_categories": declining,
        "stable_count": len(stable),
        "unstable_count": len(unstable),
    }


def _build_recommendations(summary: dict, baselines: dict, results: list) -> list:
    """根据对标与趋势情况生成业务建议。"""
    recs: list[str] = []
    if summary.get("data_gap_alert"):
        recs.append(
            f"基准覆盖率仅{summary.get('benchmark_coverage', 0) * 100:.0f}%,"
            "存在数据缺口,建议补充历史采购价与市场参考价以完善品类基准"
        )
    rule_flags = summary.get("rule_flags", {}) or {}
    if rule_flags.get("expensive_p90", 0) > 0:
        recs.append(
            f"发现{rule_flags['expensive_p90']}笔采购价高于品类P90,"
            "建议引入竞争性报价或重新议价"
        )
    if rule_flags.get("renegotiate_opportunity", 0) > 0:
        recs.append(
            "部分品类历史价格呈下降趋势,建议抓住议价机会与供应商重新谈判长期合约"
        )
    grade_dist = summary.get("grade_distribution", {}) or {}
    if grade_dist.get("expensive", 0) > 0:
        recs.append(
            f"{grade_dist['expensive']}笔采购偏离基准超25%,建议重点核查单价构成与采购审批"
        )
    declining = [c for c, b in baselines.items()
                 if b.get("trend_direction") == "下降"]
    if declining:
        recs.append(
            f"品类{','.join(declining)}历史价格下降,可考虑在续约时下调基准价"
        )
    if not recs:
        recs.append("采购价格整体处于合理区间,建议保持常规基准监控")
    return recs
