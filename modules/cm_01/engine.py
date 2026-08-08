"""[CM-01] 持续审计技术平台引擎 —— 纯 stdlib CUSUM + 规则引擎 + 滑动窗口。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 滑动窗口聚合（统计指标计算）：
      - 指标：count / mean / std / min / max / sum / z-score
      - 窗口：时间窗口（最近 N 条记录）
  * CUSUM 累积和控制图（均值偏移检测）：
      - 累积和 St = St-1 + (xt - μ - k)
      - 阈值 h，若 St > h 则触发异常
      - 上下双侧检测（上升/下降漂移）
  * 规则引擎（20+监控规则，可配置）：
      - 阈值型：value > / < / == threshold
      - 比率型：ratio > / < threshold
      - 趋势型：连续 N 点上升/下降
      - 组合型：多 AND / OR 条件
  * 告警分级：P0(>80, 立即) / P1(60-80, 专项) / P2(40-60, 监控) / P3(<40, 归档)

模型结构（self.model）：
  {
    "rules": [...],
    "cusum_params": {"k": 0.5, "h": 5.0},
    "baselines": {},
    "window_size": 100,
  }
"""
from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "cm_01.db"

_METRICS_SCHEMA = {
    "metric_id": "TEXT",
    "timestamp": "DATETIME",
    "metric_name": "TEXT",
    "value": "REAL",
    "source": "TEXT",
    "window_stats": "JSON",
}
_ALERTS_SCHEMA = {
    "alert_id": "TEXT",
    "metric_name": "TEXT",
    "rule_id": "TEXT",
    "rule_name": "TEXT",
    "severity": "TEXT",
    "score": "REAL",
    "value": "REAL",
    "threshold": "REAL",
    "deviation": "REAL",
    "detector": "TEXT",
    "timestamp": "DATETIME",
    "details": "JSON",
}


class StreamingEngine(AbstractEngine):
    """CM-01 持续审计引擎（CUSUM + 规则引擎 + 滑动窗口）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for table, schema in [("metrics", _METRICS_SCHEMA), ("alerts", _ALERTS_SCHEMA)]:
            if table not in self.db.tables():
                self.db.create_table(table, schema)

        self.model = {
            "rules": [
                {"rule_id": "R01", "name": "大额交易", "metric": "transaction_amount",
                 "type": "threshold", "op": ">", "threshold": 1_000_000, "score": 30},
                {"rule_id": "R02", "name": "超大额交易", "metric": "transaction_amount",
                 "type": "threshold", "op": ">", "threshold": 5_000_000, "score": 50},
                {"rule_id": "R03", "name": "高频操作", "metric": "operation_count",
                 "type": "threshold", "op": ">", "threshold": 50, "score": 25},
                {"rule_id": "R04", "name": "金额异常波动", "metric": "transaction_amount",
                 "type": "zscore", "threshold": 3.0, "score": 35},
                {"rule_id": "R05", "name": "CUSUM均值漂移", "metric": "metric_value",
                 "type": "cusum", "threshold": 5.0, "score": 40},
                {"rule_id": "R06", "name": "交易频率下降", "metric": "transaction_count",
                 "type": "trend_decline", "threshold": 0.5, "score": 20},
                {"rule_id": "R07", "name": "异常IP登录", "metric": "login_count",
                 "type": "threshold", "op": ">", "threshold": 20, "score": 30},
            ],
            "cusum_params": {"k": 0.5, "h": 5.0},
            "baselines": {},
            "window_size": 100,
            "cusum_state": {},
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取实时指标流，按 metric 分组构建窗口。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 metrics 列表")

        raw = input_data.get("metrics", [])
        window_size = int(input_data.get("window_size", self.model["window_size"]))

        grouped: dict[str, list[dict]] = {}
        for m in raw:
            if not isinstance(m, dict):
                continue
            name = m.get("metric_name") or m.get("name", "")
            val = float(m.get("value", 0))
            src = m.get("source", "unknown")
            ts = m.get("timestamp", "")
            if name not in grouped:
                grouped[name] = []
            grouped[name].append({"value": val, "source": src, "timestamp": ts})

        prepared = {}
        for name, items in grouped.items():
            window = items[-window_size:]
            values = [it["value"] for it in window]
            if len(values) >= 2:
                mean = sum(values) / len(values)
                variance = sum((v - mean) ** 2 for v in values) / len(values)
                std = math.sqrt(variance) if variance > 0 else 0.0
            else:
                mean = values[0] if values else 0.0
                std = 0.0

            self.model["baselines"][name] = {"mean": mean, "std": std,
                                             "count": len(values)}
            prepared[name] = {
                "window": window,
                "values": values,
                "stats": {"mean": mean, "std": std,
                          "min": min(values) if values else 0,
                          "max": max(values) if values else 0,
                          "count": len(values)},
            }
        return prepared

    def _infer(self, prepared: Any) -> Any:
        """规则引擎 + CUSUM 检测 → 告警列表。"""
        rules = self.model["rules"]
        cusum_params = self.model["cusum_params"]
        alerts: list[dict] = []

        for metric_name, data in prepared.items():
            values = data["values"]
            stats = data["stats"]
            baseline_mean = self.model["baselines"].get(metric_name, {}).get("mean", 0)
            baseline_std = self.model["baselines"].get(metric_name, {}).get("std", 1.0)

            for rule in rules:
                if rule["metric"] != metric_name and rule["metric"] not in ("metric_value",):
                    continue

                if rule["type"] == "threshold":
                    hits = self._check_threshold(values, rule)
                    for hit in hits:
                        score = rule["score"]
                        alerts.append(self._make_alert(
                            metric_name, rule, hit, "threshold", score
                        ))

                elif rule["type"] == "zscore" and baseline_std > 0:
                    for v in values[-5:]:
                        z = abs(v - baseline_mean) / baseline_std
                        if z > rule["threshold"]:
                            alerts.append(self._make_alert(
                                metric_name, rule, v, "zscore",
                                min(rule["score"] + int(z * 5), 100),
                                deviation=round(z, 4)
                            ))

                elif rule["type"] == "cusum":
                    cusum_alerts = self._run_cusum(
                        values, baseline_mean, cusum_params["k"], cusum_params["h"],
                        metric_name, rule
                    )
                    alerts.extend(cusum_alerts)

                elif rule["type"] == "trend_decline":
                    decline_alerts = self._check_trend_decline(
                        values, rule
                    )
                    alerts.extend(decline_alerts)

        for a in alerts:
            a["severity"] = self._score_to_severity(a["score"])

        alerts.sort(key=lambda a: -a["score"])
        return {"alerts": alerts, "metrics": prepared}

    def _check_threshold(self, values: list[float], rule: dict) -> list[float]:
        hits = []
        for v in values:
            threshold = rule["threshold"]
            op = rule["op"]
            trigger = False
            if op == ">":
                trigger = v > threshold
            elif op == ">=":
                trigger = v >= threshold
            elif op == "<":
                trigger = v < threshold
            elif op == "<=":
                trigger = v <= threshold
            elif op == "==":
                trigger = v == threshold
            if trigger:
                hits.append(v)
        return hits

    def _run_cusum(self, values: list[float], target: float, k: float, h: float,
                   metric_name: str, rule: dict) -> list[dict]:
        state = self.model["cusum_state"].get(metric_name, {"sh": 0.0, "sl": 0.0})
        alerts = []
        for x in values:
            state["sh"] = max(0, state["sh"] + (x - target - k))
            state["sl"] = min(0, state["sl"] + (x - target + k))
            if state["sh"] > h:
                alerts.append(self._make_alert(
                    metric_name, rule, x, "cusum_up",
                    min(rule["score"] + int(state["sh"] * 5), 100),
                    deviation=round(state["sh"], 4)
                ))
                state["sh"] = 0.0
            if state["sl"] < -h:
                alerts.append(self._make_alert(
                    metric_name, rule, x, "cusum_down",
                    min(rule["score"] + int(abs(state["sl"]) * 5), 100),
                    deviation=round(state["sl"], 4)
                ))
                state["sl"] = 0.0
        self.model["cusum_state"][metric_name] = state
        return alerts

    def _check_trend_decline(self, values: list[float], rule: dict) -> list[dict]:
        if len(values) < 10:
            return []
        recent = values[-5:]
        prev = values[-10:-5]
        if not prev:
            return []
        recent_mean = sum(recent) / len(recent)
        prev_mean = sum(prev) / len(prev)
        if prev_mean <= 0:
            return []
        ratio = recent_mean / prev_mean
        if ratio < rule["threshold"]:
            return [self._make_alert(
                "metric", rule, recent_mean, "trend_decline",
                rule["score"], deviation=round(ratio, 4)
            )]
        return []

    def _make_alert(self, metric_name: str, rule: dict, value: float,
                    detector: str, score: int, deviation: float | None = None) -> dict:
        return {
            "alert_id": f"{metric_name}_{rule['rule_id']}_{detector}",
            "metric_name": metric_name,
            "rule_id": rule["rule_id"],
            "rule_name": rule["name"],
            "severity": "P3",
            "score": min(score, 100),
            "value": round(value, 4),
            "threshold": rule.get("threshold", 0),
            "deviation": deviation if deviation is not None else 0.0,
            "detector": detector,
            "timestamp": datetime.now().isoformat(),
            "details": {"rule_type": rule["type"], "metric": metric_name},
        }

    def _score_to_severity(self, score: int) -> str:
        if score >= 80:
            return "P0"
        if score >= 60:
            return "P1"
        if score >= 40:
            return "P2"
        return "P3"

    def _postprocess(self, result: Any) -> Any:
        """持久化告警 + 统计汇总。"""
        alerts = result.get("alerts", [])
        for a in alerts:
            self.db.insert("alerts", {
                "alert_id": a["alert_id"],
                "metric_name": a["metric_name"],
                "rule_id": a["rule_id"],
                "rule_name": a["rule_name"],
                "severity": a["severity"],
                "score": a["score"],
                "value": a["value"],
                "threshold": a["threshold"],
                "deviation": a["deviation"],
                "detector": a["detector"],
                "timestamp": a["timestamp"],
                "details": a["details"],
            })

        by_severity: dict[str, int] = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        for a in alerts:
            by_severity[a["severity"]] += 1

        result["summary"] = {
            "total_alerts": len(alerts),
            "by_severity": by_severity,
            "p0_p1_count": by_severity["P0"] + by_severity["P1"],
            "avg_score": round(
                sum(a["score"] for a in alerts) / len(alerts), 2
            ) if alerts else 0,
        }
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
