"""自定义业务规则：在 engine 之后执行，补充价格异常业务标记。

规则（基于 engine 输出的 results，按品类聚合计算）：
  1) 价格偏离品类均值 > 2σ → price_outlier（统计离群标记）
  2) 单一来源采购（品类仅 1 家供应商）且价格高于品类均价 → sole_source_investigate（建议核查）
  3) 价格高于品类中位数基准 > 15% → overcharge（疑似高价采购）

品类中位数/均值作为内部"市场基准"代理，无需外部数据即可计算。
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any

_ZSCORE_FLAG = 2.0      # 价格偏离均值 σ 倍数阈值
_OVERCHARGE_PCT = 0.15  # 高于品类中位数基准的比例阈值


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：统计离群 / 单一来源核查 / 高价采购标记。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    z_flag = float(rules_cfg.get("zscore_flag", _ZSCORE_FLAG))
    overcharge_pct = float(rules_cfg.get("overcharge_pct", _OVERCHARGE_PCT))

    results = result.get("results", [])

    # 按品类聚合
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r.get("category", "uncategorized")].append(r)

    # 预计算每个品类的统计画像
    cat_stats: dict[str, dict] = {}
    for cat, items in by_cat.items():
        prices = [
            float(r.get("unit_price", 0)) for r in items
            if float(r.get("unit_price", 0)) > 0
        ]
        if not prices:
            continue
        mean = statistics.mean(prices)
        stdev = statistics.pstdev(prices) if len(prices) > 1 else 0.0
        median = statistics.median(prices)
        suppliers = {
            r.get("supplier_id") for r in items if r.get("supplier_id")
        }
        cat_stats[cat] = {
            "mean": mean,
            "stdev": stdev,
            "median": median,
            "supplier_count": len(suppliers),
            "count": len(prices),
        }

    price_outlier_count = 0
    sole_source_count = 0
    overcharge_count = 0
    for r in results:
        cat = r.get("category", "uncategorized")
        price = float(r.get("unit_price", 0))
        cs = cat_stats.get(cat)
        adjustments = r.setdefault("rule_flags", [])
        r.setdefault("price_outlier", False)
        r.setdefault("sole_source_investigate", False)
        r.setdefault("overcharge", False)
        if cs is None or price <= 0:
            continue

        # 规则 1：|z| > z_flag → 统计离群
        z = abs((price - cs["mean"]) / cs["stdev"]) if cs["stdev"] > 0 else 0.0
        if z > z_flag:
            r["price_outlier"] = True
            price_outlier_count += 1
            adjustments.append(f"价格偏离均值{z:.2f}σ(>{z_flag})")

        # 规则 2：单一来源 + 价格高于品类均价 → 建议核查
        if cs["supplier_count"] == 1 and price > cs["mean"]:
            r["sole_source_investigate"] = True
            sole_source_count += 1
            adjustments.append("单一来源采购且价格高于品类均价,建议核查")

        # 规则 3：价格高于品类中位数基准 > overcharge_pct → 疑似高价
        benchmark = cs["median"]
        if benchmark > 0 and price > benchmark * (1 + overcharge_pct):
            r["overcharge"] = True
            overcharge_count += 1
            deviation = (price - benchmark) / benchmark * 100
            adjustments.append(
                f"价格高于品类基准中位数{deviation:.1f}%(>{overcharge_pct * 100:.0f}%)"
            )

    # 同步统计
    summary = result.get("summary", {})
    summary["rule_flags"] = {
        "price_outlier": price_outlier_count,
        "sole_source_investigate": sole_source_count,
        "overcharge": overcharge_count,
    }
    result["summary"] = summary
    return result
