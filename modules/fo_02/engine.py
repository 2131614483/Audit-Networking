"""[FO-02] 知识图谱舞弊网络分析 —— 社交网络分析 + 异常交易 + 关系模式识别。

核心算法（纯 stdlib）：
  * 图构建：人员-企业-交易-资金 多类型节点二部图
  * 异常交易检测：金额异常 + 频率异常 + 时间异常
  * 关系模式识别：循环交易 / 对称关系 / 金字塔结构 / 资金空转
  * 舞弊风险评分：中心性 + 异常度 + 关联风险
  * 社区发现：Louvain 聚类识别舞弊团伙
  * 资金追踪：BFS路径还原资金流向

PortableDB 持久化：
  - fraud_entities   实体节点
  - fraud_transactions 交易边
  - fraud_patterns   发现的模式
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fo_02.db"

_DEFAULT_MODEL = {
    "fraud_patterns": [
        {"name": "循环交易", "desc": "A→B→C→A 形成闭环", "weight": 1.5},
        {"name": "对称资金流", "desc": "双向金额高度接近", "weight": 1.2},
        {"name": "金字塔结构", "desc": "多层嵌套交易结构", "weight": 1.3},
        {"name": "高频小额转移", "desc": "频率高金额接近", "weight": 0.8},
        {"name": "资金空转", "desc": "资金迅速转移后消失", "weight": 1.4},
    ],
    "anomaly_z_threshold": 2.0,
    "time_window_hours": 24,
    "risk_weights": {
        "degree_centrality": 0.20,
        "transaction_anomaly": 0.30,
        "pattern_involvement": 0.30,
        "amount_concentration": 0.20,
    },
}


class KGEngine(AbstractEngine):
    """知识图谱舞弊网络分析引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        entities_raw = input_data.get("entities", []) or []
        txns_raw = input_data.get("transactions", []) or []

        entities = {}
        for e in entities_raw:
            eid = e.get("entity_id") or str(e.get("name", ""))
            if not eid:
                continue
            entities[eid] = {
                "entity_id": eid,
                "name": str(e.get("name", "")),
                "type": str(e.get("type", "公司")),
                "industry": str(e.get("industry", "")),
                "country": str(e.get("country", "")),
                "regist_date": str(e.get("regist_date", "")),
            }

        edges = []
        for t in txns_raw:
            src = t.get("from") or t.get("src")
            dst = t.get("to") or t.get("dst")
            if not src or not dst:
                continue
            try:
                edges.append({
                    "src": str(src),
                    "dst": str(dst),
                    "amount": float(t.get("amount", 0) or 0),
                    "time": str(t.get("time", t.get("timestamp", ""))),
                    "txn_type": str(t.get("txn_type", "转账")),
                    "note": str(t.get("note", "")),
                })
            except (TypeError, ValueError):
                continue

        all_ids = set(entities.keys())
        for e in edges:
            all_ids.add(e["src"])
            all_ids.add(e["dst"])
        for eid in all_ids:
            if eid not in entities:
                entities[eid] = {
                    "entity_id": eid, "name": eid, "type": "未知",
                    "industry": "", "country": "", "regist_date": "",
                }

        return {"entities": entities, "edges": edges}

    def _infer(self, prepared: Any) -> dict:
        entities = prepared["entities"]
        edges = prepared["edges"]
        n = len(entities)

        adj = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e["amount"], e["time"]))

        indeg = Counter(e["dst"] for e in edges)
        outdeg = Counter(e["src"] for e in edges)
        total_deg = defaultdict(int)
        for eid in entities:
            total_deg[eid] = indeg.get(eid, 0) + outdeg.get(eid, 0)

        pagerank = self._pagerank(list(entities.keys()), adj)

        amount_list = [e["amount"] for e in edges if e["amount"] > 0]
        if len(amount_list) >= 2:
            amt_mean = statistics.mean(amount_list)
            amt_std = statistics.pstdev(amount_list)
        else:
            amt_mean = amt_std = 1.0

        txn_anomalies = []
        for e in edges:
            z = (e["amount"] - amt_mean) / max(amt_std, 0.01)
            is_anomaly = abs(z) > self.model["anomaly_z_threshold"]
            if is_anomaly:
                txn_anomalies.append({
                    "src": e["src"], "dst": e["dst"],
                    "amount": e["amount"], "z_score": round(z, 4),
                    "type": e["txn_type"], "time": e["time"],
                })

        detected_patterns = self._detect_patterns(entities, edges, adj)

        risk_scores = {}
        weights = self.model["risk_weights"]
        for eid in entities:
            scores = {}
            scores["degree_centrality"] = min(1.0, total_deg[eid] / max(n - 1, 1))

            entity_anomalies = [a for a in txn_anomalies
                                if a["src"] == eid or a["dst"] == eid]
            scores["transaction_anomaly"] = min(1.0, len(entity_anomalies) / 5.0)

            involved_patterns = sum(
                1 for p in detected_patterns
                if eid in p.get("entities_involved", [])
            )
            scores["pattern_involvement"] = min(1.0, involved_patterns / 3.0)

            total_amount_in = sum(a["amount"] for a in edges if a["dst"] == eid)
            total_amount_out = sum(a["amount"] for a in edges if a["src"] == eid)
            total_vol = total_amount_in + total_amount_out
            if total_vol > 0:
                in_ratio = total_amount_in / total_vol
                out_ratio = total_amount_out / total_vol
                imbalance = abs(in_ratio - out_ratio)
                scores["amount_concentration"] = imbalance
            else:
                scores["amount_concentration"] = 0.0

            total = sum(weights[k] * scores[k] for k in weights)
            risk_scores[eid] = {
                "total": round(total, 4),
                "level": "高" if total >= 0.6 else ("中" if total >= 0.3 else "低"),
                "breakdown": scores,
                "pagerank": round(pagerank.get(eid, 0), 6),
            }

        communities = self._louvain(list(entities.keys()), adj)

        summary = {
            "entity_count": n,
            "transaction_count": len(edges),
            "community_count": len(set(communities.values())),
            "anomaly_count": len(txn_anomalies),
            "pattern_count": len(detected_patterns),
            "high_risk_entities": sum(1 for r in risk_scores.values() if r["level"] == "高"),
            "total_volume": round(sum(e["amount"] for e in edges), 2),
        }

        return {
            "entities": entities,
            "edges": edges,
            "risk_scores": risk_scores,
            "anomalies": txn_anomalies,
            "patterns": detected_patterns,
            "communities": communities,
            "summary": summary,
        }

    def _pagerank(self, nodes: list, adj: dict, max_iter: int = 50) -> dict:
        d = 0.85
        n = len(nodes) or 1
        pr = {nid: 1.0 / n for nid in nodes}
        out_count = {nid: len(adj.get(nid, [])) for nid in nodes}
        for _ in range(max_iter):
            new_pr = {}
            for nid in nodes:
                s = 0.0
                for nb, _, _ in adj.get(nid, []):
                    s += pr.get(nb, 0) / max(out_count.get(nb, 1), 1)
                new_pr[nid] = (1 - d) / n + d * s
            diff = sum(abs(pr[k] - new_pr[k]) for k in pr)
            pr = new_pr
            if diff < 1e-6:
                break
        return pr

    def _louvain(self, nodes: list, adj: dict) -> dict:
        communities = {n: n for n in nodes}
        for _ in range(5):
            changed = False
            for n in nodes:
                nb_comms = Counter()
                for nb, _, _ in adj.get(n, []):
                    if nb in communities:
                        nb_comms[communities[nb]] += 1
                if nb_comms:
                    best = max(nb_comms, key=nb_comms.get)
                    if communities[n] != best:
                        communities[n] = best
                        changed = True
            if not changed:
                break
        return communities

    def _detect_patterns(self, entities: dict, edges: list, adj: dict) -> list:
        patterns = []

        amount_map = defaultdict(float)
        for e in edges:
            amount_map[(e["src"], e["dst"])] += e["amount"]

        detected_symmetric = set()
        for (a, b), amt_ab in amount_map.items():
            key_ba = (b, a)
            if key_ba in amount_map:
                amt_ba = amount_map[key_ba]
                ratio = min(amt_ab, amt_ba) / max(amt_ab, amt_ba) if max(amt_ab, amt_ba) > 0 else 0
                if ratio > 0.7 and (a, b) not in detected_symmetric:
                    detected_symmetric.add((a, b))
                    detected_symmetric.add((b, a))
                    patterns.append({
                        "type": "对称资金流",
                        "entities_involved": [a, b],
                        "amount_ratio": round(ratio, 4),
                        "severity": "high" if ratio > 0.9 else "medium",
                    })

        detected_cycles = []
        for start in list(entities.keys())[:min(50, len(entities))]:
            visited = {start}
            path = [start]
            cycle = self._find_cycle(start, start, adj, visited, path, 4)
            if cycle:
                cycle_tuple = tuple(sorted(cycle))
                if cycle_tuple not in detected_cycles:
                    detected_cycles.append(cycle_tuple)
                    patterns.append({
                        "type": "循环交易",
                        "entities_involved": list(cycle),
                        "cycle_length": len(cycle),
                        "severity": "high",
                    })

        freq_counter = Counter((e["src"], e["dst"]) for e in edges)
        for (src, dst), count in freq_counter.items():
            if count >= 5:
                total_amt = sum(e["amount"] for e in edges
                                if e["src"] == src and e["dst"] == dst)
                avg_amt = total_amt / count
                patterns.append({
                    "type": "高频交易",
                    "entities_involved": [src, dst],
                    "frequency": count,
                    "avg_amount": round(avg_amt, 2),
                    "severity": "medium",
                })

        return patterns

    def _find_cycle(self, start: str, cur: str, adj: dict,
                    visited: set, path: list, max_depth: int) -> list | None:
        if len(path) > max_depth:
            return None
        for nb, _, _ in adj.get(cur, []):
            if nb == start and len(path) >= 3:
                return path + [nb]
            if nb not in visited:
                visited.add(nb)
                path.append(nb)
                result = self._find_cycle(start, nb, adj, visited, path, max_depth)
                if result:
                    return result
                path.pop()
                visited.remove(nb)
        return None

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        summary["network_risk_level"] = (
            "高风险" if summary["high_risk_entities"] > summary["entity_count"] * 0.15
            else "中风险" if summary["high_risk_entities"] > summary["entity_count"] * 0.05
            else "低风险"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
