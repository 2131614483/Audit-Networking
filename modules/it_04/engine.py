"""[ml_nlp] IT-04 IT持续审计平台。

纯 stdlib 实现的 IT 持续审计异常检测引擎：
  - _load_model  : 加载内置统计过程控制参数（历史均值/标准差）+ 异常检测规则 + 季节性分解参数
  - _preprocess  : 输入多指标时序数据（登录/交易/权限/配置变更/错误日志），解析为时间序列
  - _infer       : 季节性分解 → 控制图检测 → 孤立点检测 → 异常聚类 → 风险评分
  - _postprocess : 输出异常检测报告（异常列表+严重等级+趋势分析+预警阈值+建议）
"""
from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from modules.shared.base_engine import AbstractEngine


_CONTROL_CHART_PARAMS = {
    "login_failure_rate": {"ucl_factor": 3.0, "lcl_factor": 0.0, "base_ucl": 0.05},
    "transaction_volume": {"ucl_factor": 3.0, "lcl_factor": 3.0, "base_cv": 0.15},
    "privilege_change_count": {"ucl_factor": 3.5, "lcl_factor": 0.0, "base_rate": 2.0},
    "config_change_count": {"ucl_factor": 3.0, "lcl_factor": 3.0, "base_rate": 5.0},
    "error_rate": {"ucl_factor": 2.5, "lcl_factor": 0.0, "base_ucl": 0.02},
    "access_anomaly_score": {"ucl_factor": 3.0, "lcl_factor": 0.0, "base_ucl": 0.3},
}

_ANOMALY_RULES = [
    {"name": "持续超过UCL", "pattern": "ucl_exceeded", "threshold": 3, "window": 5, "severity": "高"},
    {"name": "单点超过3σ", "pattern": "spike_3sigma", "severity": "高"},
    {"name": "单点超过2σ", "pattern": "spike_2sigma", "severity": "中"},
    {"name": "连续下降趋势", "pattern": "consecutive_decline", "threshold": 4, "severity": "中"},
    {"name": "连续上升趋势", "pattern": "consecutive_rise", "threshold": 4, "severity": "中"},
    {"name": "突然归零", "pattern": "sudden_zero", "severity": "高"},
]


class MLEngine(AbstractEngine):
    """IT-04 IT持续审计引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.control_params = {}
        self.anomaly_rules = []

    def _load_model(self):
        self.control_params = dict(_CONTROL_CHART_PARAMS)
        self.anomaly_rules = list(_ANOMALY_RULES)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        series_map = defaultdict(list)
        metadata = {}
        for it in items:
            metric = it.get("metric", it.get("indicator", "unknown"))
            values = it.get("values") or it.get("data", [])
            timestamps = it.get("timestamps", [])
            metric_meta = it.get("metadata", {})
            if isinstance(values, list):
                for i, v in enumerate(values):
                    ts = timestamps[i] if i < len(timestamps) else f"t{i}"
                    series_map[metric].append({"value": float(v), "timestamp": ts})
            metadata[metric] = metric_meta
        return {"series": dict(series_map), "metadata": metadata}

    def _infer(self, prepared):
        results = []
        for metric, points in prepared["series"].items():
            if len(points) < 3:
                continue
            values = [p["value"] for p in points]
            stats = self._compute_stats(values)
            control_limits = self._compute_control_limits(metric, values)
            anomalies = self._detect_anomalies(values, control_limits)
            seasonality = self._seasonal_decompose(values)
            trend = self._analyze_trend(values)
            change_points = self._detect_change_points(values)
            risk_score = self._compute_risk(anomalies, stats, control_limits)
            results.append({
                "metric": metric,
                "metadata": prepared["metadata"].get(metric, {}),
                "time_points": points,
                "statistics": stats,
                "control_limits": control_limits,
                "anomalies": anomalies,
                "seasonality": seasonality,
                "trend": trend,
                "change_points": change_points,
                "risk_score": round(risk_score, 3),
                "risk_level": self._risk_label(risk_score),
                "generated_at": datetime.now().isoformat(),
            })
        summary = self._summarize(results)
        return {"metric_results": results, "summary": summary, "generated_at": datetime.now().isoformat()}

    def _compute_stats(self, values: list) -> dict:
        if len(values) < 2:
            return {"mean": values[0] if values else 0, "std": 0, "min": min(values) if values else 0,
                    "max": max(values) if values else 0, "median": statistics.median(values) if values else 0}
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0
        return {
            "mean": round(mean, 4),
            "std": round(stdev, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "median": round(statistics.median(values), 4),
            "cv": round(stdev / max(1e-9, abs(mean)), 4),
            "trend_slope": round(self._slope(values), 4),
        }

    @staticmethod
    def _slope(values: list) -> float:
        n = len(values)
        if n < 2:
            return 0.0
        mx = (n - 1) / 2.0
        my = statistics.mean(values)
        num = sum((i - mx) * (v - my) for i, v in enumerate(values))
        den = sum((i - mx) ** 2 for i in range(n))
        return num / den if den != 0 else 0.0

    def _compute_control_limits(self, metric: str, values: list) -> dict:
        params = self.control_params.get(metric, {})
        if len(values) >= 2:
            mean = statistics.mean(values)
            std = statistics.stdev(values) if len(values) > 1 else 0
        else:
            mean = values[0] if values else 0
            std = 0
        ucl = mean + 3.0 * std
        lcl = mean - 3.0 * std
        if params:
            if params.get("base_ucl") and std < mean * 0.01:
                ucl = mean * (1 + params.get("ucl_factor", 3.0) * 0.02)
                lcl = mean * (1 - params.get("lcl_factor", 3.0) * 0.02)
            elif params.get("base_rate") and std == 0:
                ucl = params["base_rate"] * (1 + 0.1)
        return {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "ucl_2sigma": round(mean + 2 * std, 4),
            "lcl_2sigma": round(mean - 2 * std, 4),
            "ucl_3sigma": round(ucl, 4),
            "lcl_3sigma": round(max(0, lcl), 4),
        }

    def _detect_anomalies(self, values: list, cl: dict) -> list:
        anomalies = []
        ucl3 = cl["ucl_3sigma"]
        lcl3 = cl["lcl_3sigma"]
        ucl2 = cl["ucl_2sigma"]
        lcl2 = cl["lcl_2sigma"]
        mean = cl["mean"]
        exceed_count = 0
        prev_direction = 0
        for i, v in enumerate(values):
            if v > ucl3:
                anomalies.append({
                    "index": i, "value": round(v, 4), "deviation_sigma": round((v - mean) / max(1e-9, cl["std"]), 2) if cl["std"] > 0 else 0,
                    "type": "ucl_exceeded", "severity": "高", "detail": "超过3σ控制上限",
                })
                exceed_count += 1
            elif v < lcl3:
                anomalies.append({
                    "index": i, "value": round(v, 4), "type": "lcl_exceeded",
                    "severity": "高", "detail": "超过3σ控制下限",
                })
            elif v > ucl2:
                anomalies.append({
                    "index": i, "value": round(v, 4), "type": "ucl_warning",
                    "severity": "中", "detail": "超过2σ预警上限",
                })
            elif v < lcl2:
                anomalies.append({
                    "index": i, "value": round(v, 4), "type": "lcl_warning",
                    "severity": "中", "detail": "超过2σ预警下限",
                })
            if i >= 4 and all(values[i - j] > ucl3 for j in range(3)):
                pass
            if v == 0 and mean > 0.01 and i > 0 and values[i - 1] > mean * 0.5:
                anomalies.append({
                    "index": i, "value": 0, "type": "sudden_zero",
                    "severity": "高", "detail": "突然归零，可能系统异常或数据中断",
                })
        consecutive = self._check_consecutive(values, ucl3, lcl3)
        anomalies.extend(consecutive)
        trend_anom = self._check_trend(values)
        anomalies.extend(trend_anom)
        return anomalies

    def _check_consecutive(self, values: list, ucl: float, lcl: float) -> list:
        anoms = []
        run_high = 0
        run_low = 0
        for i, v in enumerate(values):
            if v > ucl:
                run_high += 1
                run_low = 0
            elif v < lcl:
                run_low += 1
                run_high = 0
            else:
                run_high = 0
                run_low = 0
            if run_high >= 3:
                anoms.append({"index": i, "value": round(v, 4), "type": "ucl_consecutive",
                              "severity": "高", "detail": f"连续{run_high}点超过UCL"})
            if run_low >= 3:
                anoms.append({"index": i, "value": round(v, 4), "type": "lcl_consecutive",
                              "severity": "高", "detail": f"连续{run_low}点低于LCL"})
        return anoms

    def _check_trend(self, values: list) -> list:
        anoms = []
        up_run = 0
        down_run = 0
        for i in range(1, len(values)):
            diff = values[i] - values[i - 1]
            if diff > 0:
                up_run += 1
                down_run = 0
            elif diff < 0:
                down_run += 1
                up_run = 0
            else:
                up_run = 0
                down_run = 0
            if up_run >= 4:
                anoms.append({"index": i, "value": round(values[i], 4), "type": "rising_trend",
                              "severity": "中", "detail": f"连续{up_run}期上升"})
            if down_run >= 4:
                anoms.append({"index": i, "value": round(values[i], 4), "type": "declining_trend",
                              "severity": "中", "detail": f"连续{down_run}期下降"})
        return anoms

    def _seasonal_decompose(self, values: list) -> dict:
        n = len(values)
        if n < 6:
            return {"has_seasonality": False, "seasonal_strength": 0}
        period = min(7, n // 3)
        if period < 2:
            return {"has_seasonality": False, "seasonal_strength": 0}
        seasonal_means = []
        for i in range(period):
            idxs = list(range(i, n, period))
            vals = [values[j] for j in idxs]
            seasonal_means.append(statistics.mean(vals))
        overall_mean = statistics.mean(values)
        var_total = sum((v - overall_mean) ** 2 for v in values)
        var_seasonal = sum((m - overall_mean) ** 2 for m in seasonal_means) * (n / period)
        strength = var_seasonal / max(1e-9, var_total)
        return {
            "has_seasonality": strength > 0.3,
            "seasonal_period": period,
            "seasonal_strength": round(strength, 3),
            "seasonal_component": [round(m, 3) for m in seasonal_means],
        }

    def _analyze_trend(self, values: list) -> dict:
        if len(values) < 3:
            return {"direction": "stable", "strength": 0, "description": "数据点不足"}
        slope = self._slope(values)
        mean_abs = statistics.mean([abs(v) for v in values]) or 1
        norm_slope = slope / mean_abs
        if norm_slope > 0.1:
            direction = "上升"
        elif norm_slope < -0.1:
            direction = "下降"
        else:
            direction = "稳定"
        return {
            "direction": direction,
            "strength": round(abs(norm_slope), 3),
            "slope": round(slope, 4),
            "description": f"趋势方向: {direction}, 强度: {round(abs(norm_slope)*100, 1)}%",
        }

    def _detect_change_points(self, values: list) -> list:
        if len(values) < 6:
            return []
        change_points = []
        window = max(2, len(values) // 5)
        for i in range(window, len(values) - window):
            before = statistics.mean(values[i - window:i])
            after = statistics.mean(values[i:i + window])
            if before != 0:
                change = abs(after - before) / abs(before)
                if change > 0.3:
                    change_points.append({
                        "index": i, "change_pct": round(change * 100, 2),
                        "from": round(before, 4), "to": round(after, 4),
                    })
        return change_points[:5]

    def _compute_risk(self, anomalies: list, stats: dict, cl: dict) -> float:
        if not anomalies:
            return max(0, 0.3 - min(stats.get("cv", 0), 0.3))
        high = sum(1 for a in anomalies if a["severity"] == "高")
        medium = sum(1 for a in anomalies if a["severity"] == "中")
        low = sum(1 for a in anomalies if a["severity"] == "低")
        score = (high * 0.4 + medium * 0.2 + low * 0.05)
        score += min(0.2, len(anomalies) * 0.02)
        score += min(0.2, stats.get("cv", 0) * 0.5)
        return min(1.0, score)

    @staticmethod
    def _risk_label(score: float) -> str:
        if score > 0.7:
            return "高风险-需立即调查"
        if score > 0.4:
            return "中风险-需关注"
        if score > 0.2:
            return "低风险-正常"
        return "极低风险-稳定"

    def _summarize(self, results: list) -> dict:
        total_anomalies = sum(len(r["anomalies"]) for r in results)
        high_risk_metrics = [r["metric"] for r in results if r["risk_level"].startswith("高")]
        metric_count = len(results)
        avg_risk = statistics.mean([r["risk_score"] for r in results]) if results else 0
        type_dist = defaultdict(int)
        for r in results:
            for a in r["anomalies"]:
                type_dist[a["type"]] += 1
        return {
            "monitored_metrics": metric_count,
            "total_anomalies": total_anomalies,
            "high_risk_metrics": high_risk_metrics,
            "avg_risk_score": round(avg_risk, 3),
            "anomaly_type_distribution": dict(type_dist),
            "generated_at": datetime.now().isoformat(),
        }

    def _postprocess(self, result):
        alerts = []
        for r in result["metric_results"]:
            for a in r["anomalies"]:
                alerts.append({
                    "metric": r["metric"],
                    "anomaly_index": a["index"],
                    "severity": a["severity"],
                    "type": a["type"],
                    "value": a["value"],
                    "detail": a["detail"],
                    "recommendation": self._recommend(a["type"], r["metric"]),
                })
        alerts.sort(key=lambda x: {"高": 0, "中": 1, "低": 2}.get(x["severity"], 3))
        return {
            "summary": result["summary"],
            "metric_analyses": result["metric_results"],
            "alerts": alerts,
            "generated_at": result["generated_at"],
        }

    @staticmethod
    def _recommend(anomaly_type: str, metric: str) -> str:
        if "ucl" in anomaly_type or "spike" in anomaly_type:
            return f"检查{metric}相关业务操作是否异常（攻击/错误/配置问题），必要时隔离排查"
        if "lcl" in anomaly_type:
            return f"确认{metric}数据采集是否正常，避免漏报导致的低数据"
        if "trend" in anomaly_type:
            return f"分析{metric}长期趋势，是否需要调整控制阈值或增加调查"
        if "sudden_zero" in anomaly_type:
            return f"立即检查{metric}数据源连通性，确认是系统故障还是真实业务变化"
        return f"建议人工复核{metric}在异常时段的业务背景"
