"""[SC-03] 供应商持续风险监控 —— 滑动窗口异常检测 + 趋势预警 + EWMA。

核心算法（纯 stdlib + PortableDB）：
  * 滑动窗口统计：在给定窗口内计算均值/标准差/趋势/波动率
  * Z-Score 异常检测：|z| > 3 标记异常
  * IQR 异常检测：超出 [Q1-1.5*IQR, Q3+1.5*IQR] 标记异常
  * EWMA 指数加权移动平均：λ=0.3，对最新观测赋予更高权重
  * 趋势斜率：线性回归 slope（最小二乘法）
  * 预警分级：低/中/高/紧急 四级

PortableDB 持久化：
  - supplier_metrics 供应商时序指标
  - risk_alerts      风险预警记录
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
_DB_PATH = _DATA_DIR / "sc_03.db"

_DEFAULT_MODEL = {
    "ewma_lambda": 0.3,
    "z_threshold": 3.0,
    "iqr_multiplier": 1.5,
    "window_size": 30,
    "trend_confidence": 0.05,
    "alert_levels": [
        ("紧急", 0.8),
        ("高", 0.6),
        ("中", 0.4),
        ("低", 0.0),
    ],
    "metrics": [
        "payment_delay_days",
        "quality_failure_rate",
        "on_time_delivery_rate",
        "rejection_rate",
        "price_change_pct",
        "communication_responsiveness",
    ],
}

_METRICS_SCHEMA = {
    "supplier_id": "TEXT",
    "metric_name": "TEXT",
    "metric_value": "REAL",
    "timestamp": "DATETIME",
}
_ALERTS_SCHEMA = {
    "supplier_id": "TEXT",
    "metric_name": "TEXT",
    "alert_level": "TEXT",
    "alert_score": "REAL",
    "description": "TEXT",
    "details": "JSON",
    "created_at": "DATETIME",
}


class MLEngine(AbstractEngine):
    """供应商持续风险监控引擎（滑动窗口 + EWMA）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("supplier_metrics", _METRICS_SCHEMA),
                             ("risk_alerts", _ALERTS_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        suppliers = input_data.get("suppliers", []) or []
        window_size = self.config.get("window_size", self.model["window_size"])

        cleaned: list[dict] = []
        for s in suppliers:
            sid = s.get("supplier_id") or ""
            metrics_raw = s.get("metrics", {}) or {}
            metrics_series = {}
            for mname, values in metrics_raw.items():
                if not isinstance(values, (list, tuple)):
                    continue
                nums = [float(v) for v in values if v is not None]
                metrics_series[mname] = nums[-window_size:]
            if not sid or not metrics_series:
                continue
            cleaned.append({
                "supplier_id": sid,
                "name": s.get("name", sid),
                "metrics": metrics_series,
            })

        return {"suppliers": cleaned, "window_size": window_size}

    def _infer(self, prepared: Any) -> dict:
        ewma_l = self.model["ewma_lambda"]
        z_thr = self.model["z_threshold"]
        iqr_mul = self.model["iqr_multiplier"]
        alert_levels = self.model["alert_levels"]

        results = []
        for sup in prepared["suppliers"]:
            sid = sup["supplier_id"]
            sup_result = {
                "supplier_id": sid,
                "name": sup["name"],
                "metric_analyses": {},
                "overall_risk_score": 0.0,
                "alerts": [],
            }
            scores = []
            for mname, values in sup["metrics"].items():
                analysis = self._analyze_metric(values, ewma_l, z_thr, iqr_mul)
                sup_result["metric_analyses"][mname] = analysis
                scores.append(analysis.get("anomaly_score", 0.0))
                for alert in analysis.get("alerts", []):
                    alert["metric_name"] = mname
                    sup_result["alerts"].append(alert)

            overall = sum(scores) / max(len(scores), 1) if scores else 0.0
            sup_result["overall_risk_score"] = round(overall, 4)

            level = "低"
            for lv, thr in alert_levels:
                if overall >= thr:
                    level = lv
                    break
            sup_result["alert_level"] = level
            results.append(sup_result)

        results.sort(key=lambda x: x["overall_risk_score"], reverse=True)

        summary = {
            "supplier_count": len(results),
            "alerts_by_level": {},
            "avg_risk_score": round(
                sum(r["overall_risk_score"] for r in results) / max(len(results), 1), 4
            ),
        }
        for lv, _ in alert_levels:
            summary["alerts_by_level"][lv] = sum(
                1 for r in results if r["alert_level"] == lv
            )
        return {"suppliers": results, "summary": summary}

    def _analyze_metric(self, values: list[float], ewma_l: float,
                        z_thr: float, iqr_mul: float) -> dict:
        if len(values) < 3:
            return {"status": "insufficient_data", "anomaly_score": 0.0, "alerts": []}

        mean = statistics.mean(values)
        stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
        sorted_vals = sorted(values)
        q1 = self._percentile(sorted_vals, 25)
        q3 = self._percentile(sorted_vals, 75)
        iqr = q3 - q1
        lower = q1 - iqr_mul * iqr
        upper = q3 + iqr_mul * iqr

        z_anomalies = []
        iqr_anomalies = []
        for i, v in enumerate(values):
            if stdev > 0:
                z = (v - mean) / stdev
                if abs(z) > z_thr:
                    z_anomalies.append({"index": i, "value": v, "z_score": round(z, 3)})
            if v < lower or v > upper:
                iqr_anomalies.append({"index": i, "value": v, "bound": round(upper if v > upper else lower, 3)})

        ewma_val = self._ewma(values, ewma_l)
        latest = values[-1]
        ewma_ratio = abs(latest - ewma_val) / max(abs(ewma_val), 1e-9)

        slope = self._linear_slope(values)
        trend_direction = "上升" if slope > 0 else ("下降" if slope < 0 else "平稳")
        trend_score = min(1.0, abs(slope) / max(abs(mean), 1e-9))

        anomaly_score = 0.0
        anomaly_score += min(0.4, len(z_anomalies) * 0.1)
        anomaly_score += min(0.3, len(iqr_anomalies) * 0.1)
        anomaly_score += min(0.15, ewma_ratio * 2)
        anomaly_score += min(0.15, trend_score)
        anomaly_score = min(1.0, anomaly_score)

        alerts = []
        if z_anomalies:
            alerts.append({
                "type": "z_score_anomaly",
                "severity": "high",
                "count": len(z_anomalies),
                "details": z_anomalies[-3:],
            })
        if iqr_anomalies:
            alerts.append({
                "type": "iqr_anomaly",
                "severity": "medium",
                "count": len(iqr_anomalies),
                "details": iqr_anomalies[-3:],
            })
        if ewma_ratio > 0.5:
            alerts.append({
                "type": "ewma_deviation",
                "severity": "high" if ewma_ratio > 1.0 else "medium",
                "deviation_pct": round(ewma_ratio * 100, 1),
            })
        if abs(slope) > 0 and trend_score > 0.3:
            alerts.append({
                "type": "significant_trend",
                "severity": "medium",
                "direction": trend_direction,
                "slope": round(slope, 4),
            })

        return {
            "count": len(values),
            "mean": round(mean, 4),
            "std": round(stdev, 4),
            "latest": round(latest, 4),
            "ewma": round(ewma_val, 4),
            "trend_direction": trend_direction,
            "trend_slope": round(slope, 4),
            "z_anomaly_count": len(z_anomalies),
            "iqr_anomaly_count": len(iqr_anomalies),
            "anomaly_score": round(anomaly_score, 4),
            "alerts": alerts,
        }

    def _ewma(self, values: list[float], lam: float) -> float:
        if not values:
            return 0.0
        result = values[0]
        for v in values[1:]:
            result = lam * v + (1 - lam) * result
        return result

    def _linear_slope(self, values: list[float]) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mean_x = (n - 1) / 2.0
        mean_y = statistics.mean(values)
        num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
        den = sum((xs[i] - mean_x) ** 2 for i in range(n))
        return num / den if den != 0 else 0.0

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

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        suppliers = result["suppliers"]
        high_risk = [s for s in suppliers if s["alert_level"] in ("紧急", "高")]
        summary["high_risk_suppliers"] = [
            {"supplier_id": s["supplier_id"], "name": s["name"],
             "alert_level": s["alert_level"], "risk_score": s["overall_risk_score"]}
            for s in high_risk[:10]
        ]
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
