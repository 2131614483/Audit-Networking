"""统一输出格式化：异常交易明细表 + 统计详情 + 业务建议。

输出结构：
  {
    "status": "ok",
    "module": "SC-04",
    "flagged_transactions": [ {order_id, supplier_id, category, unit_price,
                              anomaly_score, anomaly_level, severity,
                              indicators, rule_flags, ...}, ... ],
    "statistical_details": { order_count, benford_statistic, benford_flagged,
                            anomaly_distribution, severity_distribution,
                            category_stats, thresholds },
    "rule_summary": { price_outlier, sole_source_investigate, overcharge },
    "recommendations": [ ... ],
    "statistics": { order_count, anomaly_count, confirmed_anomaly_count,
                    severity_distribution }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    summary = result.get("summary", {})
    results = result.get("results", [])

    # 标记的交易：severity != low 或 命中任一业务规则
    flagged = []
    for r in results:
        sev = r.get("severity", "low")
        has_flag = (
            r.get("price_outlier")
            or r.get("sole_source_investigate")
            or r.get("overcharge")
        )
        if sev != "low" or has_flag:
            flagged.append({
                "order_id": r.get("order_id"),
                "supplier_id": r.get("supplier_id"),
                "category": r.get("category"),
                "unit_price": r.get("unit_price"),
                "total_amount": r.get("total_amount"),
                "anomaly_score": r.get("anomaly_score"),
                "anomaly_level": r.get("anomaly_level"),
                "severity": sev,
                "confirmed_anomaly": r.get("confirmed_anomaly", False),
                "indicators": r.get("indicators", {}),
                "rule_flags": r.get("rule_flags", []),
                "price_outlier": r.get("price_outlier", False),
                "sole_source_investigate": r.get("sole_source_investigate", False),
                "overcharge": r.get("overcharge", False),
            })

    # 统计详情
    statistical_details = {
        "order_count": summary.get("order_count", 0),
        "benford_statistic": summary.get("benford_statistic", 0),
        "benford_flagged": summary.get("benford_flagged", False),
        "anomaly_distribution": summary.get("anomaly_distribution", {}),
        "severity_distribution": summary.get("severity_distribution", {}),
        "category_stats": summary.get("category_stats", {}),
        "thresholds": summary.get("thresholds", {}),
    }

    # 业务建议
    recommendations = _build_recommendations(summary, flagged)

    return {
        "status": "ok",
        "module": "SC-04",
        "flagged_transactions": flagged,
        "statistical_details": statistical_details,
        "rule_summary": summary.get("rule_flags", {}),
        "recommendations": recommendations,
        "statistics": {
            "order_count": summary.get("order_count", 0),
            "anomaly_count": summary.get("anomaly_count", 0),
            "confirmed_anomaly_count": summary.get("confirmed_anomaly_count", 0),
            "severity_distribution": summary.get("severity_distribution", {}),
        },
    }


def _build_recommendations(summary: dict, flagged: list) -> list:
    """根据统计与规则命中情况生成业务建议。"""
    recs: list[str] = []
    if summary.get("benford_flagged"):
        recs.append(
            "Benford检验异常:金额首位数字分布显著偏离,建议核查采购金额真实性与录入完整性"
        )
    rule_flags = summary.get("rule_flags", {}) or {}
    if rule_flags.get("overcharge", 0) > 0:
        recs.append(
            f"发现{rule_flags['overcharge']}笔高于品类基准中位数的采购,"
            "建议引入竞争性报价或重新议价"
        )
    if rule_flags.get("sole_source_investigate", 0) > 0:
        recs.append(
            "存在单一来源采购且价格偏高,建议评估独家供应商必要性并探索替代供应源"
        )
    if rule_flags.get("price_outlier", 0) > 0:
        recs.append(
            f"发现{rule_flags['price_outlier']}笔价格统计离群,"
            "建议复核单价构成与采购审批流程"
        )
    critical = summary.get("confirmed_anomaly_count", 0)
    if critical > 0:
        recs.append(
            f"{critical}笔交易异常评分达critical级别,建议优先开展专项审计"
        )
    if not recs:
        recs.append("未发现显著价格异常,建议保持常规监控")
    return recs
