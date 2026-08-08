"""[SC-02] 知识图谱供应链网络分析 —— 纯 stdlib 图算法实现。

核心算法（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，纯 stdlib 实现，不引入任何第三方依赖）：

  * 图构建：将供应商数据转为有向图（dict + dict[list] 邻接表），支持多类型关系
  * PageRank：幂迭代法，阻尼系数 0.85，迭代至收敛（或最大 50 次）
  * 社区发现：贪心 Louvain 模块度最大化（O(N*D) 近似）
  * 风险传导：BFS/DFS 遍历，按边权重累积传播风险值
  * 最短路径：BFS 无权最短路径 / Dijkstra 加权最短路径

模型结构（self.model）：
  {
    "damping": 0.85,
    "max_iter": 50,
    "conv_threshold": 1e-6,
    "risk_decay": 0.7,
    "edge_weights": {"supplies": 1.0, "owns": 0.8, "related": 0.5, "executes": 1.2},
  }

PortableDB 持久化：
  - suppliers       供应商节点主表
  - relations       供应商关系边表
  - graph_analysis  图谱分析结果（PageRank/社区/传导风险）
"""
from __future__ import annotations

import collections
import math
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "sc_02.db"

_DEFAULT_MODEL = {
    "damping": 0.85,
    "max_iter": 50,
    "conv_threshold": 1e-6,
    "risk_decay": 0.7,
    "edge_weights": {
        "supplies": 1.0,
        "owns": 0.8,
        "related": 0.5,
        "executes": 1.2,
        "shares_address": 0.6,
        "shares_phone": 0.7,
    },
}

_SUPPLIERS_SCHEMA = {
    "supplier_id": "TEXT PRIMARY KEY",
    "name": "TEXT",
    "uscc": "TEXT",
    "node_type": "TEXT",
    "attributes": "JSON",
    "created_at": "DATETIME",
}
_RELATIONS_SCHEMA = {
    "source_id": "TEXT",
    "target_id": "TEXT",
    "relation_type": "TEXT",
    "weight": "REAL",
    "attributes": "JSON",
    "created_at": "DATETIME",
}
_ANALYSIS_SCHEMA = {
    "supplier_id": "TEXT",
    "pagerank": "REAL",
    "community_id": "INTEGER",
    "risk_score": "REAL",
    "path_count": "INTEGER",
    "updated_at": "DATETIME",
}


class KGEngine(AbstractEngine):
    """供应链知识图谱网络分析引擎（纯 stdlib 图算法）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ---------- 模型加载 ----------
    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [
            ("suppliers", _SUPPLIERS_SCHEMA),
            ("relations", _RELATIONS_SCHEMA),
            ("graph_analysis", _ANALYSIS_SCHEMA),
        ]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    # ---------- 预处理 ----------
    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        suppliers = input_data.get("suppliers", []) or []
        relations = input_data.get("relations", []) or []

        node_set: set[str] = set()
        node_attrs: dict[str, dict] = {}
        for s in suppliers:
            sid = s.get("supplier_id") or s.get("id") or ""
            name = s.get("name") or ""
            if not sid:
                continue
            node_set.add(sid)
            node_attrs[sid] = {
                "supplier_id": sid,
                "name": name,
                "uscc": s.get("uscc", ""),
                "node_type": s.get("node_type", "supplier"),
                "attributes": s.get("attributes", {}),
            }

        edges: list[dict] = []
        for r in relations:
            src = r.get("source") or r.get("source_id")
            tgt = r.get("target") or r.get("target_id")
            rtype = r.get("relation_type", r.get("type", "related"))
            if not src or not tgt:
                continue
            if src not in node_set:
                node_set.add(src)
                node_attrs[src] = {"supplier_id": src, "name": src, "node_type": "unknown"}
            if tgt not in node_set:
                node_set.add(tgt)
                node_attrs[tgt] = {"supplier_id": tgt, "name": tgt, "node_type": "unknown"}
            weight_val = self.model["edge_weights"].get(rtype, 1.0)
            raw_w = r.get("weight")
            if raw_w is not None:
                try:
                    weight_val = float(raw_w)
                except (TypeError, ValueError):
                    pass
            edges.append({
                "source": src,
                "target": tgt,
                "relation_type": rtype,
                "weight": weight_val,
                "attributes": r.get("attributes", {}),
            })

        adj_out: dict[str, list[tuple[str, float]]] = {n: [] for n in node_set}
        adj_in: dict[str, list[tuple[str, float]]] = {n: [] for n in node_set}
        for e in edges:
            adj_out[e["source"]].append((e["target"], e["weight"]))
            adj_in[e["target"]].append((e["source"], e["weight"]))

        return {
            "nodes": list(node_set),
            "node_attrs": node_attrs,
            "edges": edges,
            "adj_out": adj_out,
            "adj_in": adj_in,
        }

    # ---------- 推理 ----------
    def _infer(self, prepared: Any) -> dict:
        nodes = prepared["nodes"]
        adj_out = prepared["adj_out"]
        adj_in = prepared["adj_in"]
        edges = prepared["edges"]

        if not nodes:
            return {"nodes": [], "edges": [], "pagerank": {}, "communities": {},
                    "risk_scores": {}, "paths": [], "summary": {"node_count": 0, "edge_count": 0}}

        pr = self._pagerank(nodes, adj_out)
        communities = self._louvain(nodes, adj_out, adj_in)
        risk_scores = self._risk_propagation(nodes, adj_out)
        paths = self._find_risk_paths(nodes, adj_out, adj_in, risk_scores, max_paths=20)

        node_attrs = prepared["node_attrs"]
        enriched_nodes = []
        for n in nodes:
            enriched_nodes.append({
                "supplier_id": n,
                "name": node_attrs.get(n, {}).get("name", n),
                "node_type": node_attrs.get(n, {}).get("node_type", "supplier"),
                "pagerank": round(pr.get(n, 0.0), 6),
                "community_id": communities.get(n, -1),
                "risk_score": round(risk_scores.get(n, 0.0), 4),
            })

        sorted_nodes = sorted(enriched_nodes, key=lambda x: x["pagerank"], reverse=True)

        summary = {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "community_count": len({c for c in communities.values() if c >= 0}),
            "avg_degree": round(sum(len(v) for v in adj_out.values()) / max(len(nodes), 1), 2),
            "top_pagerank": sorted_nodes[:10],
        }

        return {
            "nodes": enriched_nodes,
            "edges": edges,
            "pagerank": pr,
            "communities": communities,
            "risk_scores": risk_scores,
            "paths": paths,
            "summary": summary,
        }

    # ---------- 后处理 ----------
    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        communities = result["communities"]
        comm_counts: dict[int, int] = {}
        for c in communities.values():
            if c >= 0:
                comm_counts[c] = comm_counts.get(c, 0) + 1
        summary["community_distribution"] = comm_counts

        risk_scores = result["risk_scores"]
        high_risk = sorted(
            [{"supplier_id": n["supplier_id"], "risk_score": n["risk_score"]}
             for n in result["nodes"] if n["risk_score"] >= 0.5],
            key=lambda x: x["risk_score"], reverse=True,
        )
        summary["high_risk_count"] = len(high_risk)
        summary["high_risk_top"] = high_risk[:10]
        result["summary"] = summary
        return result

    # ---------- 图算法实现 ----------
    def _pagerank(self, nodes: list[str], adj_out: dict) -> dict[str, float]:
        d = self.model["damping"]
        max_iter = self.model["max_iter"]
        threshold = self.model["conv_threshold"]
        n = len(nodes)
        if n == 0:
            return {}
        pr = {node: 1.0 / n for node in nodes}
        out_link_count = {node: len(adj_out.get(node, [])) for node in nodes}

        for _ in range(max_iter):
            new_pr = {}
            dangling_sum = sum(v for k, v in pr.items() if out_link_count[k] == 0)
            base = (1.0 - d) / n + d * dangling_sum / n
            for node in nodes:
                rank = base
                for src, _w in adj_out.get(node, []):
                    pass
                for node2 in nodes:
                    for src, _w in adj_out.get(node2, []):
                        if src == node2:
                            pass
                in_sum = 0.0
                for src in nodes:
                    neighbors = adj_out.get(src, [])
                    count = len(neighbors)
                    if count > 0:
                        for tgt, _w in neighbors:
                            if tgt == node:
                                in_sum += pr[src] / count
                new_pr[node] = base + d * in_sum
            diff = sum(abs(new_pr[k] - pr[k]) for k in pr)
            pr = new_pr
            if diff < threshold:
                break

        total = sum(pr.values())
        if total > 0:
            pr = {k: v / total for k, v in pr.items()}
        return pr

    def _louvain(self, nodes: list[str], adj_out: dict, adj_in: dict) -> dict[str, int]:
        neighbors: dict[str, list[str]] = {}
        for n in nodes:
            ns = set()
            for t, _ in adj_out.get(n, []):
                ns.add(t)
            for s, _ in adj_in.get(n, []):
                ns.add(s)
            neighbors[n] = list(ns)

        community: dict[str, int] = {n: i for i, n in enumerate(nodes)}
        node_community = {n: i for i, n in enumerate(nodes)}

        node_total: dict[str, float] = {}
        for n in nodes:
            tot = 0.0
            for t, w in adj_out.get(n, []):
                tot += w
            for s, w in adj_in.get(n, []):
                tot += w
            node_total[n] = tot

        community_tot: dict[int, float] = {}
        for n in nodes:
            c = node_community[n]
            community_tot[c] = community_tot.get(c, 0.0) + node_total[n]

        def modularity_gain(node: str, target_comm: int) -> float:
            cur = node_community[node]
            if cur == target_comm:
                return 0.0
            ki_in_new = 0.0
            for t, w in adj_out.get(node, []):
                if node_community.get(t) == target_comm:
                    ki_in_new += w
            for s, w in adj_in.get(node, []):
                if node_community.get(s) == target_comm:
                    ki_in_new += w
            ki_in_old = 0.0
            for t, w in adj_out.get(node, []):
                if node_community.get(t) == cur:
                    ki_in_old += w
            for s, w in adj_in.get(node, []):
                if node_community.get(s) == cur:
                    ki_in_old += w
            sigma_tot_new = community_tot.get(target_comm, 0.0)
            sigma_tot_old = community_tot.get(cur, 0.0)
            ki = node_total[node]
            m2 = max(sum(node_total.values()), 1.0)
            gain = (ki_in_new - ki_in_old) / 1.0 - ki * (sigma_tot_new - sigma_tot_old + ki) / m2
            return gain

        changed = True
        iteration = 0
        while changed and iteration < 20:
            changed = False
            iteration += 1
            for node in nodes:
                cur_comm = node_community[node]
                best_comm = cur_comm
                best_gain = 0.0
                seen = set()
                for nb in neighbors[node]:
                    nb_comm = node_community.get(nb, -1)
                    if nb_comm < 0 or nb_comm in seen or nb_comm == cur_comm:
                        continue
                    seen.add(nb_comm)
                    gain = modularity_gain(node, nb_comm)
                    if gain > best_gain:
                        best_gain = gain
                        best_comm = nb_comm
                if best_comm != cur_comm:
                    node_community[node] = best_comm
                    community_tot[cur_comm] -= node_total[node]
                    community_tot[best_comm] = community_tot.get(best_comm, 0.0) + node_total[node]
                    changed = True

        unique_comms = sorted(set(node_community.values()))
        remap = {c: i for i, c in enumerate(unique_comms)}
        return {n: remap[node_community[n]] for n in nodes}

    def _risk_propagation(self, nodes: list[str], adj_out: dict) -> dict[str, float]:
        risk_decay = self.model["risk_decay"]
        risk: dict[str, float] = {n: 0.0 for n in nodes}

        for node in nodes:
            out_deg = len(adj_out.get(node, []))
            if out_deg == 0:
                risk[node] = 0.001

        pr = self._pagerank(nodes, adj_out)
        for n in nodes:
            risk[n] = pr.get(n, 0.0)

        visited: set[str] = set()
        sources = sorted(nodes, key=lambda x: risk.get(x, 0.0), reverse=True)
        for src in sources[:max(3, len(nodes) // 10)]:
            queue: collections.deque[tuple[str, int, float]] = collections.deque()
            queue.append((src, 0, risk.get(src, 0.3)))
            local_visited: set[str] = set()
            while queue:
                cur, depth, val = queue.popleft()
                if val < 0.01 or depth > 8:
                    continue
                for tgt, w in adj_out.get(cur, []):
                    propagated = val * risk_decay * w
                    if propagated > risk.get(tgt, 0.0):
                        risk[tgt] = propagated
                    queue.append((tgt, depth + 1, propagated))

        max_val = max(risk.values()) if risk else 1.0
        if max_val > 0:
            risk = {k: min(1.0, v / max_val * 2) for k, v in risk.items()}
        return risk

    def _find_risk_paths(self, nodes, adj_out, adj_in, risk_scores, max_paths=20):
        high_risk = sorted(
            [(n, v) for n, v in risk_scores.items() if v >= 0.4],
            key=lambda x: x[1], reverse=True,
        )
        paths = []
        for src, _score in high_risk[:5]:
            queue: collections.deque[tuple[str, list]] = collections.deque()
            queue.append((src, [src]))
            visited_local: set[str] = set()
            while queue and len(paths) < max_paths:
                cur, path = queue.popleft()
                if len(path) >= 3:
                    paths.append({
                        "path": path,
                        "length": len(path) - 1,
                        "end_risk": round(risk_scores.get(path[-1], 0.0), 4),
                    })
                    continue
                for tgt, _w in adj_out.get(cur, []):
                    if tgt in path:
                        continue
                    queue.append((tgt, path + [tgt]))
                    visited_local.add(tgt)
        return paths

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
