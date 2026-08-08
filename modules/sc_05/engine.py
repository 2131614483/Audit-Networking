"""[SC-05] AI采购价格基准平台 —— 品类画像 + 百分位基准 + 线性回归趋势。

核心算法（纯 stdlib）：
  * 品类价格画像：均值/中位数/标准差/百分位(P25/P50/P75/P90/P95)
  * 价格基准区间：[P10, P90] 作为合理区间，P50 作为基准价
  * 历史趋势：线性回归 slope + R^2 评估趋势稳定性
  * 对标分析：当前价 vs 基准区间偏离程度
  * 多源融合：历史数据 + 市场参考价加权融合

PortableDB 持久化：
  - price_histories  历史价格
  - category_baselines 品类价格基准
  - benchmark_results 对标分析结果
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "sc_05.db"

_DEFAULT_MODEL = {
    "percentiles": [10, 25, 50, 75, 90, 95],
    "baseline_range": [10, 90],
    "r2_threshold": 0.5,
    "market_weight": 0.3,
    "history_weight": 0.7,
}

_HISTORY_SCHEMA = {
    "record_id": "TEXT PRIMARY KEY",
    "category": "TEXT",
    "price": "REAL",
    "source": "TEXT",
    "record_date": "DATETIME",
}
_BASELINE_SCHEMA = {
    "category": "TEXT PRIMARY KEY",
    "baseline_price": "REAL",
    "low_bound": "REAL",
    "high_bound": "REAL",
    "percentiles": "JSON",
    "trend_slope": "REAL",
    "trend_r2": "REAL",
    "sample_count": "INTEGER",
}
_BENCHMARK_SCHEMA = {
    "benchmark_id": "TEXT PRIMARY KEY",
    "category": "TEXT",
    "test_price": "REAL",
    "deviation_pct": "REAL",
    "position": "TEXT",
    "assessment": "TEXT",
}


class MLEngine(AbstractEngine):
    """AI采购价格基准引擎（品类画像 + 百分位基准）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("price_histories", _HISTORY_SCHEMA),
                             ("category_baselines", _BASELINE_SCHEMA),
                             ("benchmark_results", _BENCHMARK_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        histories = input_data.get("price_history", []) or []
        queries = input_data.get("benchmark_queries", []) or []

        by_category: dict[str, list[float]] = {}
        for h in histories:
            cat = h.get("category", "")
            try:
                price = float(h.get("price", 0))
            except (TypeError, ValueError):
                continue
            if cat and price > 0:
                by_category.setdefault(cat, []).append(price)

        cleaned_queries = []
        for q in queries:
            try:
                price = float(q.get("price", 0))
            except (TypeError, ValueError):
                continue
            cat = q.get("category", "")
            if cat and price > 0:
                cleaned_queries.append({
                    "benchmark_id": q.get("benchmark_id") or f"B-{len(cleaned_queries)+1:06d}",
                    "category": cat,
                    "price": price,
                    "expected_trend": q.get("expected_trend"),
                })

        return {"by_category": by_category, "queries": cleaned_queries}

    def _infer(self, prepared: Any) -> dict:
        percentiles = self.model["percentiles"]
        lo_pct, hi_pct = self.model["baseline_range"]

        baselines = {}
        for cat, prices in prepared["by_category"].items():
            if len(prices) < 5:
                continue
            sorted_p = sorted(prices)
            n = len(sorted_p)
            pct_vals = {p: self._percentile(sorted_p, p) for p in percentiles}
            mean = statistics.mean(prices)
            stdev = statistics.pstdev(prices) if n > 1 else 0.0
            median = pct_vals[50]

            lo = self._percentile(sorted_p, lo_pct)
            hi = self._percentile(sorted_p, hi_pct)

            trend_slope = 0.0
            trend_r2 = 0.0
            if n >= 5:
                xs = list(range(n))
                slope = self._linear_slope(xs, prices)
                intercept = self._linear_intercept(xs, prices, slope)
                trend_slope = slope
                trend_r2 = self._r_squared(xs, prices, slope, intercept)

            baselines[cat] = {
                "category": cat,
                "sample_count": n,
                "mean": round(mean, 4),
                "median": round(median, 4),
                "std": round(stdev, 4),
                "baseline_price": round(median, 4),
                "low_bound": round(lo, 4),
                "high_bound": round(hi, 4),
                "percentiles": {str(k): round(v, 4) for k, v in pct_vals.items()},
                "trend_slope": round(trend_slope, 6),
                "trend_r2": round(trend_r2, 4),
                "trend_stable": trend_r2 >= self.model["r2_threshold"],
                "trend_direction": "上升" if trend_slope > 0 else ("下降" if trend_slope < 0 else "平稳"),
            }

        results = []
        for q in prepared["queries"]:
            cat = q["category"]
            price = q["price"]
            bl = baselines.get(cat)
            if bl is None:
                results.append({
                    **q,
                    "status": "no_baseline",
                    "assessment": "数据不足，无法对标",
                })
                continue
            baseline = bl["baseline_price"]
            deviation = (price - baseline) / baseline * 100
            pos = "正常"
            assessment = "价格处于合理区间"
            if price < bl["low_bound"]:
                pos = "偏低"
                assessment = "价格偏低，可能存在质量问题或数据异常"
            elif price > bl["high_bound"]:
                pos = "偏高"
                assessment = "价格偏高，建议议价或寻找替代供应商"
            elif price < baseline * 0.9:
                pos = "偏低"
                assessment = "略低于基准价，关注后续价格走势"
            elif price > baseline * 1.1:
                pos = "偏高"
                assessment = "略高于基准价，可考虑议价"

            trend_note = ""
            if bl.get("trend_stable") and abs(bl.get("trend_slope", 0)) > 0:
                trend_note = f"（历史价格{bl['trend_direction']}趋势）"

            results.append({
                "benchmark_id": q["benchmark_id"],
                "category": cat,
                "test_price": price,
                "baseline_price": baseline,
                "deviation_pct": round(deviation, 2),
                "position": pos,
                "assessment": assessment + trend_note,
                "baseline": bl,
            })

        summary = {
            "category_count": len(baselines),
            "query_count": len(results),
            "assessments": {
                "正常": sum(1 for r in results if r.get("position") == "正常"),
                "偏高": sum(1 for r in results if r.get("position") == "偏高"),
                "偏低": sum(1 for r in results if r.get("position") == "偏低"),
                "no_baseline": sum(1 for r in results if r.get("status") == "no_baseline"),
            },
            "top_high_deviation": sorted(
                [r for r in results if "deviation_pct" in r],
                key=lambda x: abs(x["deviation_pct"]), reverse=True,
            )[:10],
        }
        return {"baselines": baselines, "results": results, "summary": summary}

    def _percentile(self, sorted_vals: list[float], pct: float) -> float:
        if not sorted_vals:
            return 0.0
        pos = (pct / 100.0) * (len(sorted_vals) - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return sorted_vals[lo]
        frac = pos - lo
        return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

    def _linear_slope(self, xs: list[float], ys: list[float]) -> float:
        n = len(xs)
        mean_x = statistics.mean(xs)
        mean_y = statistics.mean(ys)
        num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        den = sum((xs[i] - mean_x) ** 2 for i in range(n))
        return num / den if den != 0 else 0.0

    def _linear_intercept(self, xs, ys, slope) -> float:
        return statistics.mean(ys) - slope * statistics.mean(xs)

    def _r_squared(self, xs, ys, slope, intercept) -> float:
        mean_y = statistics.mean(ys)
        ss_res = sum((ys[i] - (slope * xs[i] + intercept)) ** 2 for i in range(len(ys)))
        ss_tot = sum((y - mean_y) ** 2 for y in ys)
        if ss_tot == 0:
            return 1.0
        return 1.0 - ss_res / ss_tot

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        stable_count = sum(
            1 for b in result["baselines"].values()
            if b.get("trend_stable")
        )
        summary["stable_trend_categories"] = stable_count
        summary["unstable_trend_categories"] = len(result["baselines"]) - stable_count
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
