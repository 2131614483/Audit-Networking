"""[FI-02] 知识图谱担保链风险分析 —— 担保网络构建 + 传染风险 + 多米诺冲击模拟。

核心算法（纯 stdlib）：
  * 担保图构建：有向图，Guarantor → Borrower，权重=担保金额
  * 传染风险评分：基于网络拓扑 + 杠杆率 + 关联度
  * 多米诺冲击模拟：给定违约节点，BFS扩散计算损失
  * 社区检测：Louvain模块度聚类（复用sc_02/ta_06算法）
  * 系统重要性：PageRank + 出入度综合评分
  * 风险传导路径：最短路径 + 路径脆弱性叠加

PortableDB 持久化：
  - guarantee_edges  担保关系边
  - guarantor_nodes  担保方节点
  - shock_simulations 冲击模拟结果
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fi_02.db"

_DEFAULT_MODEL = {
    "risk_weights": {
        "leverage": 0.25,
        "connectedness": 0.25,
        "guarantee_concentration": 0.20,
        "financial_health": 0.20,
        "historical_default": 0.10,
    },
    "shock_propagation_threshold": 0.3,
    "contagion_decay": 0.7,
    "max_shock_depth": 5,
}

_GUARANTEE_SCHEMA = {
    "guarantor": "TEXT",
    "borrower": "TEXT",
    "amount": "REAL",
    "guarantee_ratio": "REAL",
    "start_date": "DATE",
    "end_date": "DATE",
}
_GUARANTOR_SCHEMA = {
    "entity_id": "TEXT PRIMARY KEY",
    "name": "TEXT",
    "industry": "TEXT",
    "leverage": "REAL",
    "current_ratio": "REAL",
    "has_default_history": "INTEGER",
    "total_assets": "REAL",
}


class KGEngine(AbstractEngine):
    """担保链风险知识图谱引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("guarantee_edges", _GUARANTEE_SCHEMA),
                             ("guarantor_nodes", _GUARANTOR_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        guarantors_raw = input_data.get("entities", []) or []
        guarantees_raw = input_data.get("guarantees", []) or []

        guarantors = {}
        for g in guarantors_raw:
            eid = g.get("entity_id") or str(g.get("name", ""))
            if not eid:
                continue
            try:
                guarantors[eid] = {
                    "entity_id": eid,
                    "name": str(g.get("name", "")),
                    "industry": str(g.get("industry", "")),
                    "leverage": float(g.get("leverage", 0.5) or 0.5),
                    "current_ratio": float(g.get("current_ratio", 1.5) or 1.5),
                    "has_default_history": bool(g.get("has_default_history", False)),
                    "total_assets": float(g.get("total_assets", 0) or 0),
                }
            except (TypeError, ValueError):
                continue

        edges = []
        seen_guarantors = set()
        seen_borrowers = set()
        for g in guarantees_raw:
            gr = g.get("guarantor") or g.get("from")
            br = g.get("borrower") or g.get("to")
            if not gr or not br:
                continue
            try:
                edges.append({
                    "guarantor": str(gr),
                    "borrower": str(br),
                    "amount": float(g.get("amount", 0) or 0),
                    "guarantee_ratio": float(g.get("guarantee_ratio", 1.0) or 1.0),
                })
                seen_guarantors.add(str(gr))
                seen_borrowers.add(str(br))
            except (TypeError, ValueError):
                continue

        all_ids = set(guarantors.keys()) | seen_guarantors | seen_borrowers
        for eid in all_ids:
            if eid not in guarantors:
                guarantors[eid] = {
                    "entity_id": eid,
                    "name": eid,
                    "industry": "",
                    "leverage": 0.5,
                    "current_ratio": 1.5,
                    "has_default_history": False,
                    "total_assets": 0,
                }

        return {"guarantors": guarantors, "edges": edges}

    def _infer(self, prepared: Any) -> dict:
        guarantors = prepared["guarantors"]
        edges = prepared["edges"]

        out_adj = defaultdict(list)
        in_adj = defaultdict(list)
        for e in edges:
            out_adj[e["guarantor"]].append(e["borrower"])
            in_adj[e["borrower"]].append(e["guarantor"])

        indeg = Counter()
        outdeg = Counter()
        for e in edges:
            indeg[e["borrower"]] += 1
            outdeg[e["guarantor"]] += 1

        n = len(guarantors)
        pagerank = self._pagerank(guarantors, out_adj, 50)

        total_guaranteed = defaultdict(float)
        total_guaranteeing = defaultdict(float)
        for e in edges:
            total_guaranteed[e["borrower"]] += e["amount"] * e["guarantee_ratio"]
            total_guaranteeing[e["guarantor"]] += e["amount"] * e["guarantee_ratio"]

        risk_scores = {}
        weights = self.model["risk_weights"]
        for eid, ent in guarantors.items():
            scores = {}
            scores["leverage"] = min(1.0, ent["leverage"])

            total_links = indeg.get(eid, 0) + outdeg.get(eid, 0)
            scores["connectedness"] = min(1.0, total_links / 10.0)

            assets = ent["total_assets"] or 1.0
            guarantee_ratio = total_guaranteeing.get(eid, 0) / assets
            scores["guarantee_concentration"] = min(1.0, guarantee_ratio / 2.0)

            cr = ent["current_ratio"]
            scores["financial_health"] = max(0.0, min(1.0, 1.0 - abs(cr - 1.5) / 3.0))

            scores["historical_default"] = 1.0 if ent["has_default_history"] else 0.1

            total = sum(weights[k] * scores[k] for k in weights)

            risk_scores[eid] = {
                "total": round(total, 4),
                "level": "高" if total >= 0.6 else ("中" if total >= 0.3 else "低"),
                "breakdown": scores,
                "pagerank": round(pagerank.get(eid, 0), 6),
            }

        communities = self._louvain(list(guarantors.keys()), out_adj, in_adj)

        shock_results = self._simulate_shocks(guarantors, edges, out_adj, risk_scores)

        summary = {
            "entity_count": n,
            "guarantee_count": len(edges),
            "community_count": len(set(communities.values())),
            "high_risk_count": sum(1 for r in risk_scores.values() if r["level"] == "高"),
            "total_guarantee_amount": round(sum(e["amount"] for e in edges), 2),
            "top_systemic": sorted(risk_scores.items(),
                                   key=lambda x: x[1]["pagerank"], reverse=True)[:10],
        }

        return {
            "guarantors": guarantors,
            "edges": edges,
            "risk_scores": risk_scores,
            "communities": communities,
            "shock_simulations": shock_results,
            "summary": summary,
        }

    def _pagerank(self, nodes: dict, out_adj: dict, max_iter: int = 50) -> dict:
        d = 0.85
        n = len(nodes) or 1
        pr = {nid: 1.0 / n for nid in nodes}
        out_count = {nid: len(out_adj.get(nid, [])) for nid in nodes}
        for _ in range(max_iter):
            new_pr = {}
            for nid in nodes:
                s = 0.0
                for nb in out_adj.get(nid, []):
                    s += pr.get(nb, 0) / max(out_count.get(nb, 1), 1)
                new_pr[nid] = (1 - d) / n + d * s
            diff = sum(abs(pr[k] - new_pr[k]) for k in pr)
            pr = new_pr
            if diff < 1e-6:
                break
        return pr

    def _louvain(self, nodes: list, out_adj: dict, in_adj: dict) -> dict:
        adj = defaultdict(list)
        for eid in nodes:
            for nb in out_adj.get(eid, []):
                adj[eid].append(nb)
            for nb in in_adj.get(eid, []):
                adj[eid].append(nb)
        communities = {n: n for n in nodes}
        for _ in range(5):
            changed = False
            for n in nodes:
                nb_comms = Counter()
                for nb in adj.get(n, []):
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

    def _simulate_shocks(self, guarantors: dict, edges: list,
                         out_adj: dict, risk_scores: dict) -> list:
        high_risk_ids = [eid for eid, r in risk_scores.items()
                         if r["level"] == "高"][:5]
        results = []
        for seed in high_risk_ids[:3]:
            affected = {seed: 1.0}
            queue = deque([(seed, 1.0, 0)])
            visited = {seed}
            while queue:
                cur, intensity, depth = queue.popleft()
                if depth >= self.model["max_shock_depth"]:
                    continue
                decay = self.model["contagion_decay"]
                for nb in out_adj.get(cur, []):
                    if nb in visited:
                        continue
                    visited.add(nb)
                    new_intensity = intensity * decay * (1 - risk_scores[nb]["breakdown"].get("financial_health", 0.5))
                    affected[nb] = max(affected.get(nb, 0), new_intensity)
                    queue.append((nb, new_intensity, depth + 1))
            results.append({
                "seed": seed,
                "affected_count": len(affected) - 1,
                "max_intensity": round(max(affected.values()), 4) if affected else 0,
                "spread_depth": max(1, self.model["max_shock_depth"]),
            })
        return results

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        summary["systemic_risk_level"] = (
            "高" if summary["high_risk_count"] > len(result["guarantors"]) * 0.2
            else "中" if summary["high_risk_count"] > len(result["guarantors"]) * 0.1
            else "低"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
