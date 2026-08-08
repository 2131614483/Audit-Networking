"""[IA-02] 持续风险监控平台引擎 —— 纯 stdlib 规则引擎 + Isolation Forest + 知识图谱关联分析。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 规则引擎（DSL 正则 + 条件组合）：
      - 规则类型：阈值型 / 比率型 / 趋势型 / 组合型
      - 条件：value > / < / == threshold, ratio, consecutive N
      - 执行：对每条记录评估所有生效规则
  * Isolation Forest 异常检测（纯 stdlib 实现）：
      - 树结构：随机选择特征 + 随机分裂点
      - 异常分数 = 2^(-平均路径长度 / c(n))
      - 阈值自适应：基于历史分布的 95% 分位数
  * 动态阈值（滚动窗口 Z-score）：
      - window_size = 50, z_threshold = 3.0
      - 每日更新基线
  * 知识图谱关联分析：
      - 实体：业务单元 / 供应商 / 客户 / 员工 / 系统
      - 关系：交易 / 审批 / 控制 / 访问
      - 图算法：PageRank(风险中心度) / BFS传导路径
  * 告警分级（4级）：
      - 🔴 严重 score>90 → 即时通知
      - 🟠 高危 score75-90 → 24h复核
      - 🟡 中危 score50-75 → 日汇总
      - 🟢 低危 score<50 → 周归档

模型结构（self.model）：
  {
    "rules": [...],
    "iforest": {"trees": [...], "threshold": 0.7},
    "baselines": {},
    "graph": {"entities": [...], "edges": [...], "adjacency": {...}},
    "alert_thresholds": [...],
  }
"""
from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ia_02.db"

_EVENTS_SCHEMA = {
    "event_id": "TEXT",
    "timestamp": "DATETIME",
    "entity_id": "TEXT",
    "entity_type": "TEXT",
    "metric": "TEXT",
    "value": "REAL",
    "source": "TEXT",
    "raw_data": "JSON",
}
_ALERTS_SCHEMA = {
    "alert_id": "TEXT",
    "detector": "TEXT",
    "rule_id": "TEXT",
    "severity": "TEXT",
    "score": "REAL",
    "entity_id": "TEXT",
    "entity_name": "TEXT",
    "description": "TEXT",
    "related_event_ids": "JSON",
    "created_at": "DATETIME",
    "status": "TEXT",
}
_ENTITIES_SCHEMA = {
    "entity_id": "TEXT",
    "entity_type": "TEXT",
    "name": "TEXT",
    "properties": "JSON",
    "page_rank": "REAL",
}
_EDGES_SCHEMA = {
    "edge_id": "TEXT",
    "from_id": "TEXT",
    "to_id": "TEXT",
    "relation": "TEXT",
    "weight": "REAL",
}
_BASELINES_SCHEMA = {
    "metric": "TEXT",
    "mean": "REAL",
    "std": "REAL",
    "window": "JSON",
    "updated_at": "DATETIME",
}

_DEFAULT_RULES: list[dict] = [
    {"id": "R001", "name": "单笔金额超限", "type": "threshold",
     "metric": "amount", "op": ">", "threshold": 1000000, "severity": "high",
     "description": "单笔交易金额超过 100 万"},
    {"id": "R002", "name": "频率异常", "type": "rate",
     "metric": "transaction_count", "window_hours": 24, "threshold": 500,
     "severity": "medium", "description": "24小时内交易次数异常偏高"},
    {"id": "R003", "name": "连续上升趋势", "type": "trend",
     "metric": "rejection_rate", "consecutive": 5, "direction": "up",
     "severity": "medium", "description": "拒绝率连续5个周期上升"},
    {"id": "R004", "name": "职责分离违反", "type": "combo",
     "conditions": [
         {"metric": "created_by", "op": "==", "field": "approved_by"},
         {"metric": "type", "op": "==", "value": "payment"},
     ], "logic": "AND", "severity": "critical",
     "description": "同一人创建并审批付款交易"},
    {"id": "R005", "name": "非工作时间访问", "type": "combo",
     "conditions": [
         {"metric": "hour", "op": "<", "value": 7},
         {"metric": "day_of_week", "op": ">=", "value": 5},
     ], "logic": "OR", "severity": "medium",
     "description": "非工作时间（周末或凌晨）系统访问"},
]


class KGEngine(AbstractEngine):
    """IA-02 持续风险监控引擎（规则引擎 + Isolation Forest + 知识图谱）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        tables = {
            "events": _EVENTS_SCHEMA, "alerts": _ALERTS_SCHEMA,
            "entities": _ENTITIES_SCHEMA, "edges": _EDGES_SCHEMA,
            "baselines": _BASELINES_SCHEMA,
        }
        for t, s in tables.items():
            if t not in self.db.tables():
                self.db.create_table(t, s)
        self.model = {
            "rules": list(_DEFAULT_RULES),
            "iforest": {"trees": [], "n_trees": 100, "sample_size": 256},
            "baselines": {},
            "graph": {"entities": {}, "edges": [], "adjacency": defaultdict(list)},
            "alert_thresholds": {"critical": 90, "high": 75, "medium": 50, "low": 0},
            "window_size": 50,
            "z_threshold": 3.0,
        }
        self._load_graph()

    def _load_graph(self) -> None:
        if not self.db:
            return
        for e in self.db.all("entities"):
            self.model["graph"]["entities"][e["entity_id"]] = e
        for edge in self.db.all("edges"):
            self.model["graph"]["edges"].append(edge)
            self.model["graph"]["adjacency"][edge["from_id"]].append(edge)

    def _preprocess(self, input_data: Any) -> dict:
        if isinstance(input_data, dict):
            action = input_data.get("action", "monitor")
            if action == "monitor":
                return {"action": "monitor", "events": input_data.get("events", [])}
            if action == "check_rule":
                return {"action": "check_rule", "event": input_data.get("event"),
                        "rule_id": input_data.get("rule_id")}
            if action == "fit_iforest":
                return {"action": "fit_iforest", "events": input_data.get("events", []),
                        "metric": input_data.get("metric", "amount")}
            if action == "score_anomaly":
                return {"action": "score_anomaly", "event": input_data.get("event"),
                        "metric": input_data.get("metric", "amount")}
            if action == "analyze_propagation":
                return {"action": "analyze_propagation", "entity_id": input_data.get("entity_id"),
                        "max_depth": input_data.get("max_depth", 3)}
            if action == "build_graph":
                return {"action": "build_graph", "entities": input_data.get("entities", []),
                        "edges": input_data.get("edges", [])}
            if action == "list_alerts":
                return {"action": "list_alerts", "severity": input_data.get("severity"),
                        "since_days": input_data.get("since_days", 7)}
        raise ValueError(f"无法识别的输入: {input_data}")

    def _infer(self, prepared: dict) -> dict:
        action = prepared["action"]
        if action == "monitor":
            return self._monitor_events(prepared["events"])
        if action == "check_rule":
            return self._check_single_rule(prepared["event"], prepared["rule_id"])
        if action == "fit_iforest":
            return self._fit_iforest(prepared["events"], prepared["metric"])
        if action == "score_anomaly":
            return self._score_anomaly(prepared["event"], prepared["metric"])
        if action == "analyze_propagation":
            return self._analyze_propagation(prepared["entity_id"], prepared["max_depth"])
        if action == "build_graph":
            return self._build_graph(prepared["entities"], prepared["edges"])
        if action == "list_alerts":
            return self._list_alerts(prepared["severity"], prepared["since_days"])
        raise ValueError(f"未知 action: {action}")

    def _postprocess(self, result: dict) -> dict:
        result["engine"] = "IA-02-ContinuousRiskMonitor"
        result["timestamp"] = datetime.now().isoformat()
        return result

    # ---------- 规则引擎 ----------

    def _monitor_events(self, events: list[dict]) -> dict:
        alerts = []
        for ev in events:
            self._store_event(ev)
            for rule in self.model["rules"]:
                alert = self._evaluate_rule(ev, rule)
                if alert:
                    alerts.append(alert)
            anomaly_alert = self._ml_check(ev)
            if anomaly_alert:
                alerts.append(anomaly_alert)
        self._update_baselines(events)
        return {
            "action": "monitor",
            "total_events": len(events),
            "alerts_generated": len(alerts),
            "alerts_by_severity": dict(Counter(a["severity"] for a in alerts)),
            "alerts": alerts,
        }

    def _store_event(self, ev: dict) -> None:
        if not self.db:
            return
        eid = ev.get("event_id") or hashlib.md5(
            (str(ev.get("entity_id", "")) + str(ev.get("metric", ""))
             + str(ev.get("timestamp", datetime.now()))).encode()
        ).hexdigest()[:12]
        row = {
            "event_id": eid, "timestamp": ev.get("timestamp", datetime.now()),
            "entity_id": ev.get("entity_id", "unknown"),
            "entity_type": ev.get("entity_type", "unknown"),
            "metric": ev.get("metric", "unknown"),
            "value": float(ev.get("value", 0)),
            "source": ev.get("source", "unknown"),
            "raw_data": {k: v for k, v in ev.items() if k not in (
                "event_id", "timestamp", "entity_id", "entity_type", "metric", "value", "source")},
        }
        self.db.insert("events", row)

    def _evaluate_rule(self, event: dict, rule: dict) -> dict | None:
        rule_type = rule.get("type", "threshold")
        triggered = False
        details = {}
        if rule_type == "threshold":
            metric_val = self._resolve_metric(event, rule.get("metric"))
            threshold = rule.get("threshold", 0)
            op = rule.get("op", ">")
            triggered = self._apply_op(metric_val, op, threshold)
            details = {"metric_value": metric_val, "threshold": threshold, "op": op}
        elif rule_type == "rate":
            metric = rule.get("metric")
            window_hours = rule.get("window_hours", 24)
            threshold = rule.get("threshold", 100)
            metric_val = self._resolve_metric(event, metric)
            baseline = self.model["baselines"].get(metric, {}).get("mean", 0)
            rate = metric_val / max(baseline, 1) if baseline else 1.0
            triggered = rate > threshold / 100 * 3 or metric_val > threshold
            details = {"rate_vs_baseline": round(rate, 2), "current": metric_val}
        elif rule_type == "trend":
            metric = rule.get("metric")
            consecutive = rule.get("consecutive", 3)
            values = self._get_recent_values(metric, consecutive + 1)
            if len(values) >= consecutive + 1:
                triggered = all(
                    (values[i + 1] > values[i]) if rule.get("direction", "up") == "up"
                    else (values[i + 1] < values[i])
                    for i in range(consecutive)
                )
            details = {"values": values}
        elif rule_type == "combo":
            conditions = rule.get("conditions", [])
            logic = rule.get("logic", "AND")
            results = [self._resolve_cond(event, c) for c in conditions]
            triggered = (all(results) if logic == "AND" else any(results))
            details = {"condition_results": results}
        if not triggered:
            return None
        alert = self._make_alert(
            detector="rule", rule_id=rule["id"],
            severity=rule.get("severity", "medium"),
            score=self._severity_score(rule.get("severity", "medium")),
            entity_id=event.get("entity_id", "unknown"),
            entity_name=event.get("entity_name", event.get("entity_id", "unknown")),
            description=f"规则触发：{rule.get('name', rule['id'])} - {rule.get('description', '')}",
            related_event_ids=[event.get("event_id", "")],
        )
        return alert

    def _resolve_metric(self, event: dict, metric: str | None) -> float:
        if metric is None:
            return float(event.get("value", 0))
        if metric == "amount":
            return float(event.get("amount", event.get("value", 0)))
        if metric in ("hour", "day_of_week"):
            ts = event.get("timestamp")
            if isinstance(ts, datetime):
                return ts.hour if metric == "hour" else ts.weekday()
            return 0
        return float(event.get(metric, 0))

    def _resolve_cond(self, event: dict, cond: dict) -> bool:
        field = cond.get("metric")
        val = self._resolve_metric(event, field)
        op = cond.get("op", "==")
        target = cond.get("value", cond.get("threshold"))
        if op == "==":
            return val == target or str(event.get(field)) == str(target)
        return self._apply_op(val, op, target)

    def _apply_op(self, val: float, op: str, threshold: float) -> bool:
        try:
            v = float(val)
            t = float(threshold)
        except (ValueError, TypeError):
            return False
        if op == ">":
            return v > t
        if op == ">=":
            return v >= t
        if op == "<":
            return v < t
        if op == "<=":
            return v <= t
        if op == "==":
            return v == t
        if op == "!=":
            return v != t
        return False

    def _get_recent_values(self, metric: str, n: int) -> list[float]:
        if not self.db:
            return []
        rows = self.db.query("events", where=f"metric = ?",
                              params=[metric], order_by="timestamp DESC", limit=n)
        return [r["value"] for r in rows][::-1]

    def _ml_check(self, event: dict) -> dict | None:
        metric = event.get("metric", "amount")
        value = float(event.get("value", 0))
        base = self.model["baselines"].get(metric)
        if not base or base.get("std", 0) == 0:
            return None
        mean = base["mean"]
        std = base["std"]
        z = abs(value - mean) / std
        if z > self.model["z_threshold"]:
            severity = "high" if z > 5 else ("medium" if z > 4 else "low")
            return self._make_alert(
                detector="ml_zscore", rule_id="ML-ZSCORE",
                severity=severity,
                score=min(z * 20, 95),
                entity_id=event.get("entity_id", "unknown"),
                entity_name=event.get("entity_name", event.get("entity_id", "unknown")),
                description=f"Z-score 异常：{metric} 值={value:.2f}, z={z:.2f}（基线 μ={mean:.2f}, σ={std:.2f}）",
                related_event_ids=[event.get("event_id", "")],
            )
        return None

    def _severity_score(self, severity: str) -> float:
        t = self.model["alert_thresholds"]
        return t.get(severity, 50)

    def _make_alert(self, **kwargs) -> dict:
        aid = hashlib.md5(
            (kwargs.get("rule_id", "") + kwargs.get("entity_id", "")
             + datetime.now().isoformat()).encode()
        ).hexdigest()[:12]
        alert = {"alert_id": aid, "created_at": datetime.now(), "status": "open", **kwargs}
        if self.db:
            self.db.insert("alerts", alert)
        return alert

    def _check_single_rule(self, event: dict, rule_id: str | None) -> dict:
        rules = self.model["rules"]
        if rule_id:
            rules = [r for r in rules if r["id"] == rule_id]
        results = []
        for r in rules:
            alert = self._evaluate_rule(event, r)
            results.append({"rule_id": r["id"], "triggered": alert is not None,
                             "alert": alert})
        return {"action": "check_rule", "results": results}

    def _update_baselines(self, events: list[dict]) -> None:
        metric_values: dict[str, list[float]] = defaultdict(list)
        for ev in events:
            metric_values[ev.get("metric", "unknown")].append(float(ev.get("value", 0)))
        for metric, vals in metric_values.items():
            if len(vals) >= 2:
                mean = sum(vals) / len(vals)
                variance = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
                std = math.sqrt(variance)
                self.model["baselines"][metric] = {
                    "mean": mean, "std": std, "updated_at": datetime.now(),
                }
                if self.db:
                    existing = self.db.get("baselines", where="metric = ?", params=[metric])
                    row = {"metric": metric, "mean": mean, "std": std,
                           "window": vals[-self.model["window_size"]:],
                           "updated_at": datetime.now()}
                    if existing:
                        self.db.update("baselines", row, where="metric = ?", params=[metric])
                    else:
                        self.db.insert("baselines", row)

    # ---------- Isolation Forest ----------

    def _fit_iforest(self, events: list[dict], metric: str) -> dict:
        values = [float(e.get("value", 0)) for e in events]
        if len(values) < 10:
            return {"action": "fit_iforest", "error": "样本量不足"}
        n_trees = self.model["iforest"]["n_trees"]
        sample_size = min(self.model["iforest"]["sample_size"], len(values))
        trees = []
        for _ in range(n_trees):
            sample = random.sample(values, sample_size)
            tree = self._build_i_tree(sample, max_depth=int(math.log2(sample_size)) + 1)
            trees.append(tree)
        self.model["iforest"]["trees"] = trees
        scores = [self._anomaly_score(v, trees, sample_size) for v in values]
        self.model["iforest"]["threshold"] = statistics_quantile(scores, 0.95)
        return {
            "action": "fit_iforest", "metric": metric,
            "n_trees": n_trees, "sample_size": sample_size,
            "threshold_95": round(self.model["iforest"]["threshold"], 4),
            "fitted_at": datetime.now().isoformat(),
        }

    def _build_i_tree(self, data: list[float], depth: int) -> dict:
        if depth <= 0 or len(data) <= 1:
            return {"type": "leaf", "size": len(data)}
        feature_idx = 0
        min_v = min(data)
        max_v = max(data)
        if min_v == max_v:
            return {"type": "leaf", "size": len(data)}
        split = random.uniform(min_v, max_v)
        left = [v for v in data if v < split]
        right = [v for v in data if v >= split]
        if not left or not right:
            return {"type": "leaf", "size": len(data)}
        return {
            "type": "node", "split": split, "feature": feature_idx,
            "left": self._build_i_tree(left, depth - 1),
            "right": self._build_i_tree(right, depth - 1),
        }

    def _path_length(self, tree: dict, value: float) -> float:
        if tree["type"] == "leaf":
            return self._c(tree["size"])
        if value < tree["split"]:
            return 1 + self._path_length(tree["left"], value)
        return 1 + self._path_length(tree["right"], value)

    def _c(self, n: int) -> float:
        if n <= 1:
            return 0
        return 2 * (math.log(n - 1) + 0.5772156649) - 2 * (n - 1) / n

    def _anomaly_score(self, value: float, trees: list[dict], sample_size: int) -> float:
        if not trees:
            return 0.5
        avg = sum(self._path_length(t, value) for t in trees) / len(trees)
        n = sample_size
        return 2 ** (-avg / self._c(n))

    def _score_anomaly(self, event: dict, metric: str) -> dict:
        value = float(event.get("value", 0))
        trees = self.model["iforest"]["trees"]
        if not trees:
            return {"action": "score_anomaly", "score": 0.5, "threshold": 0.7,
                    "is_anomaly": False, "note": "iForest 未训练"}
        score = self._anomaly_score(value, trees, len(trees))
        threshold = self.model["iforest"].get("threshold", 0.7)
        is_anomaly = score > threshold
        return {
            "action": "score_anomaly",
            "value": value, "score": round(score, 4), "threshold": round(threshold, 4),
            "is_anomaly": is_anomaly,
            "severity": "critical" if score > 0.85 else ("high" if score > 0.75 else "medium"),
        }

    # ---------- 知识图谱 ----------

    def _build_graph(self, entities: list[dict], edges: list[dict]) -> dict:
        g = self.model["graph"]
        for ent in entities:
            eid = ent.get("entity_id") or hashlib.md5(
                (ent.get("name", "") + ent.get("entity_type", "")).encode()
            ).hexdigest()[:12]
            g["entities"][eid] = {**ent, "entity_id": eid}
            if self.db:
                self.db.upsert("entities", g["entities"][eid], pk="entity_id")
        for edge in edges:
            eid = edge.get("edge_id") or hashlib.md5(
                (edge.get("from_id", "") + edge.get("to_id", "") + edge.get("relation", "")).encode()
            ).hexdigest()[:12]
            row = {**edge, "edge_id": eid, "weight": edge.get("weight", 1.0)}
            g["edges"].append(row)
            g["adjacency"][row["from_id"]].append(row)
            if self.db:
                self.db.upsert("edges", row, pk="edge_id")
        self._pagerank()
        return {"action": "build_graph", "entities_added": len(entities),
                "edges_added": len(edges),
                "page_rank_top_5": dict(sorted(
                    ((eid, e.get("page_rank", 0))
                     for eid, e in g["entities"].items()),
                    key=lambda x: x[1], reverse=True)[:5])}

    def _pagerank(self, damping: float = 0.85, iterations: int = 30) -> None:
        g = self.model["graph"]
        entities = list(g["entities"].keys())
        if not entities:
            return
        n = len(entities)
        rank = {e: 1.0 / n for e in entities}
        for _ in range(iterations):
            new_rank = {}
            for e in entities:
                incoming = []
                for from_id, adj in g["adjacency"].items():
                    for edge in adj:
                        if edge["to_id"] == e:
                            incoming.append(from_id)
                s = sum(rank.get(f, 0) / max(len([ed for ed in g["adjacency"].get(f, [])]), 1)
                        for f in incoming)
                new_rank[e] = (1 - damping) / n + damping * s
            rank = new_rank
        for eid in entities:
            g["entities"][eid]["page_rank"] = round(rank[eid], 6)

    def _analyze_propagation(self, entity_id: str, max_depth: int) -> dict:
        g = self.model["graph"]
        visited = {entity_id}
        queue = deque([(entity_id, 0)])
        paths = []
        propagation_score = 0.0
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in g["adjacency"].get(current, []):
                neighbor = edge["to_id"]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
                    weight = edge.get("weight", 1.0) / (depth + 1)
                    propagation_score += weight * g["entities"].get(neighbor, {}).get(
                        "page_rank", 0.01)
                    paths.append({
                        "from": current, "to": neighbor,
                        "relation": edge.get("relation", "related"),
                        "depth": depth + 1,
                    })
        return {
            "action": "analyze_propagation",
            "source_entity": entity_id,
            "max_depth": max_depth,
            "reachable_entities": len(visited),
            "propagation_score": round(propagation_score, 4),
            "paths": paths[:50],
            "risk_center": self._find_risk_center(entity_id, max_depth),
        }

    def _find_risk_center(self, entity_id: str, max_depth: int) -> dict | None:
        g = self.model["graph"]
        best = None
        best_pr = 0
        for eid, ent in g["entities"].items():
            if eid == entity_id:
                continue
            if ent.get("page_rank", 0) > best_pr:
                best_pr = ent["page_rank"]
                best = ent
        return best

    def _list_alerts(self, severity: str | None, since_days: int) -> dict:
        if not self.db:
            return {"action": "list_alerts", "alerts": []}
        where = f"created_at >= datetime('now', '-{since_days} days')"
        params: list = []
        if severity:
            where += " AND severity = ?"
            params.append(severity)
        alerts = self.db.query("alerts", where=where, params=params,
                                order_by="created_at DESC", limit=100)
        return {"action": "list_alerts", "severity": severity,
                "since_days": since_days, "total": len(alerts), "alerts": alerts}


def statistics_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.5
    sorted_vals = sorted(values)
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac
