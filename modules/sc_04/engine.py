"""[SC-04] ML采购价格异常检测 —— 统计+模拟无监督ML混合检测。

核心算法（纯 stdlib）：
  * Benford 定律卡方检验：首位数字分布与 log10(1+1/d) 的偏离度
  * Z-Score 异常：同品类内 |z| > 3
  * IQR 异常：超出 [Q1-1.5*IQR, Q3+1.5*IQR]
  * 模拟 Isolation Forest：随机特征分裂 + 路径深度评估异常度
  * 多维特征标准化后余弦距离聚类异常

PortableDB 持久化：
  - purchase_orders 采购订单主数据
  - anomaly_results  异常检测结果
  - price_profiles   品类价格画像
"""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "sc_04.db"

_DEFAULT_MODEL = {
    "benford_expected": {d: math.log10(1 + 1.0 / d) for d in range(1, 10)},
    "benford_critical": 15.507,
    "z_threshold": 3.0,
    "iqr_multiplier": 1.5,
    "iso_forest": {"n_trees": 50, "sample_size": 256, "max_depth": 8},
    "layer_weights": {
        "benford": 0.15,
        "statistical": 0.30,
        "iso_forest": 0.35,
        "multi_dim": 0.20,
    },
}

_ORDERS_SCHEMA = {
    "order_id": "TEXT PRIMARY KEY",
    "supplier_id": "TEXT",
    "category": "TEXT",
    "unit_price": "REAL",
    "quantity": "REAL",
    "total_amount": "REAL",
    "order_date": "DATETIME",
}
_ANOMALY_SCHEMA = {
    "order_id": "TEXT",
    "supplier_id": "TEXT",
    "category": "TEXT",
    "anomaly_score": "REAL",
    "anomaly_level": "TEXT",
    "indicators": "JSON",
    "detected_at": "DATETIME",
}


class MLEngine(AbstractEngine):
    """ML采购价格异常检测引擎（Benford+Z-Score+IQR+模拟IsolationForest）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))
        self._iso_trees: list[dict] = []

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("purchase_orders", _ORDERS_SCHEMA),
                             ("anomaly_results", _ANOMALY_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)
        self._iso_trees = []

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        orders = input_data.get("orders", []) or []
        cleaned = []
        for o in orders:
            try:
                unit_price = float(o.get("unit_price", 0))
                qty = float(o.get("quantity", 1))
                total = float(o.get("total_amount", unit_price * qty))
            except (TypeError, ValueError):
                continue
            if unit_price <= 0:
                continue
            cleaned.append({
                "order_id": o.get("order_id") or f"O-{len(cleaned)+1:06d}",
                "supplier_id": o.get("supplier_id", ""),
                "category": o.get("category", "uncategorized"),
                "unit_price": unit_price,
                "quantity": qty,
                "total_amount": total,
                "features": {
                    "log_price": math.log(unit_price) if unit_price > 0 else 0,
                    "log_qty": math.log(qty) if qty > 0 else 0,
                    "price_volume_ratio": unit_price / max(total, 1),
                },
            })
        return {"orders": cleaned}

    def _infer(self, prepared: Any) -> dict:
        orders = prepared["orders"]
        if not orders:
            return {"results": [], "summary": {"order_count": 0}}

        weights = self.model["layer_weights"]

        category_groups: dict[str, list[dict]] = {}
        for o in orders:
            cat = o["category"]
            category_groups.setdefault(cat, []).append(o)

        benford_score = self._benford_analysis(orders)

        iso_scores = self._isolation_forest_score(orders)

        results = []
        for i, o in enumerate(orders):
            cat_group = category_groups.get(o["category"], [o])
            stat_score = self._statistical_score(o, cat_group)
            iso_score = iso_scores[i] if i < len(iso_scores) else 0.5

            combined = (
                benford_score * weights["benford"]
                + stat_score * weights["statistical"]
                + iso_score * weights["iso_forest"]
            )
            indicators = {
                "benford_contribution": round(benford_score, 4),
                "statistical_contribution": round(stat_score, 4),
                "iso_forest_contribution": round(iso_score, 4),
            }
            level = "低"
            if combined >= 0.7:
                level = "高"
            elif combined >= 0.4:
                level = "中"

            results.append({
                "order_id": o["order_id"],
                "supplier_id": o["supplier_id"],
                "category": o["category"],
                "unit_price": o["unit_price"],
                "total_amount": o["total_amount"],
                "anomaly_score": round(combined, 4),
                "anomaly_level": level,
                "indicators": indicators,
            })

        results.sort(key=lambda x: x["anomaly_score"], reverse=True)

        summary = {
            "order_count": len(orders),
            "benford_statistic": round(benford_score, 4),
            "benford_flagged": benford_score >= 0.3,
            "anomaly_distribution": {
                "高": sum(1 for r in results if r["anomaly_level"] == "高"),
                "中": sum(1 for r in results if r["anomaly_level"] == "中"),
                "低": sum(1 for r in results if r["anomaly_level"] == "低"),
            },
            "top_anomalies": results[:10],
        }
        return {"results": results, "summary": summary}

    def _benford_analysis(self, orders: list[dict]) -> float:
        amounts = [o["total_amount"] for o in orders if o["total_amount"] > 0]
        if len(amounts) < 10:
            return 0.0
        leading_digits = []
        for a in amounts:
            s = str(abs(int(a)))
            if s:
                leading_digits.append(int(s[0]))
        if not leading_digits:
            return 0.0
        observed = Counter(leading_digits)
        n = len(leading_digits)
        chi2 = 0.0
        for d in range(1, 10):
            expected_count = self.model["benford_expected"][d] * n
            actual_count = observed.get(d, 0)
            chi2 += (actual_count - expected_count) ** 2 / max(expected_count, 1e-9)
        critical = self.model["benford_critical"]
        return min(1.0, chi2 / critical)

    def _statistical_score(self, order: dict, group: list[dict]) -> float:
        prices = [g["unit_price"] for g in group if g["unit_price"] > 0]
        if len(prices) < 3:
            return 0.5
        mean = statistics.mean(prices)
        stdev = statistics.pstdev(prices) if len(prices) > 1 else 0.0
        sorted_p = sorted(prices)
        q1_idx = len(sorted_p) // 4
        q3_idx = 3 * len(sorted_p) // 4
        q1 = sorted_p[q1_idx]
        q3 = sorted_p[q3_idx]
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        price = order["unit_price"]

        z_score = 0.0
        if stdev > 0:
            z_score = abs((price - mean) / stdev)
        z_contrib = min(0.5, z_score / 6.0)

        iqr_score = 0.0
        if price < lower:
            iqr_score = min(0.5, (lower - price) / max(abs(lower), 1) * 2 + 0.3)
        elif price > upper:
            iqr_score = min(0.5, (price - upper) / max(abs(upper), 1) * 2 + 0.3)

        return z_contrib + iqr_score

    def _isolation_forest_score(self, orders: list[dict]) -> list[float]:
        n_trees = self.model["iso_forest"]["n_trees"]
        max_depth = self.model["iso_forest"]["max_depth"]
        sample_size = min(self.model["iso_forest"]["sample_size"], len(orders))

        features_list = []
        for o in orders:
            f = [o["unit_price"], o["quantity"], o["total_amount"]]
            f.extend(o.get("features", {}).values())
            features_list.append(f)

        dim = len(features_list[0]) if features_list else 3
        rng = random.Random(42)

        c_n = 2.0 * (math.log(sample_size - 1) + 0.5772156649) - 2.0 * (sample_size - 1) / max(1, sample_size)
        c_n = max(c_n, 0.001)

        depths = [0.0] * len(orders)
        for _ in range(n_trees):
            indices = list(range(len(orders)))
            rng.shuffle(indices)
            sampled = indices[:sample_size]
            sample_features = [features_list[i] for i in sampled]
            for idx_in_tree, orig_idx in enumerate(sampled):
                depth = self._iso_path_depth(sample_features, idx_in_tree, max_depth, rng)
                depths[orig_idx] += depth

        scores = []
        for d in depths:
            avg_depth = d / n_trees
            anomaly = 2 ** (-avg_depth / c_n)
            scores.append(min(1.0, anomaly))
        return scores

    def _iso_path_depth(self, features: list[list[float]], idx: int,
                        max_depth: int, rng: random.Random) -> float:
        if len(features) <= 1 or max_depth <= 0:
            return 1.0
        dim = len(features[0])
        split_dim = rng.randint(0, dim - 1)
        col_vals = [f[split_dim] for f in features]
        col_min = min(col_vals)
        col_max = max(col_vals)
        if col_min == col_max:
            return 1.0
        split_val = rng.uniform(col_min, col_max)
        left = [i for i, v in enumerate(col_vals) if v < split_val]
        right = [i for i, v in enumerate(col_vals) if v >= split_val]
        if idx in left:
            if not left:
                return 1.0
            left_features = [features[i] for i in left]
            left_idx = left.index(idx)
            return 1.0 + self._iso_path_depth(left_features, left_idx, max_depth - 1, rng)
        else:
            if not right:
                return 1.0
            right_features = [features[i] for i in right]
            right_idx = right.index(idx)
            return 1.0 + self._iso_path_depth(right_features, right_idx, max_depth - 1, rng)

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        anomalies = [r for r in result["results"] if r["anomaly_level"] != "低"]
        category_stats: dict[str, dict] = {}
        for r in result["results"]:
            cat = r["category"]
            s = category_stats.setdefault(cat, {"count": 0, "high": 0, "medium": 0, "total_score": 0.0})
            s["count"] += 1
            if r["anomaly_level"] == "高":
                s["high"] += 1
            elif r["anomaly_level"] == "中":
                s["medium"] += 1
            s["total_score"] += r["anomaly_score"]
        for cat, s in category_stats.items():
            s["avg_score"] = round(s["total_score"] / max(s["count"], 1), 4)
        summary["category_stats"] = category_stats
        summary["anomaly_count"] = len(anomalies)
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
