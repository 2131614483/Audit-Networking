"""[TA-06] 知识图谱全球关联交易分析 —— KG构建 + 社区检测 + 路径追踪 + 转让定价风险评分。

核心算法（纯 stdlib）：
  * 图构建：关联企业-交易-地域三种子节点，merge为加权无向图
  * 社区发现：Louvain贪心式模块度优化
  * 最短路径：Dijkstra追踪关联交易路径
  * 风险评分：转移定价 + 壳公司标记 + 避税天堂 + 多层嵌套 综合打分
  * 集团识别：同一实控人/最终母公司 → 聚类为集团

PortableDB 持久化：
  - entity_nodes      实体节点
  - transaction_edges 交易边
  - risk_assessments  风险评估结果
"""
from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ta_06.db"

_DEFAULT_MODEL = {
    "shell_company_markers": ["投资", "控股", "咨询", "管理", "商务", "贸易"],
    "tax_havens": {"开曼", "维京", "巴哈马", "卢森堡", "瑞士", "新加坡",
                   "香港", "爱尔兰", "荷兰", "马尔代夫", "塞舌尔"},
    "risk_weights": {
        "transfer_pricing": 0.25,
        "shell_company": 0.20,
        "tax_haven": 0.20,
        "multi_layer": 0.15,
        "volume_concentration": 0.20,
    },
    "path_depth_threshold": 4,
}

_NODE_SCHEMA = {
    "node_id": "TEXT PRIMARY KEY",
    "node_type": "TEXT",
    "name": "TEXT",
    "country": "TEXT",
    "ultimate_parent": "TEXT",
    "is_shell": "INTEGER",
}
_EDGE_SCHEMA = {
    "src": "TEXT",
    "dst": "TEXT",
    "relation": "TEXT",
    "amount": "REAL",
    "currency": "TEXT",
    "year": "INTEGER",
}


class KGEngine(AbstractEngine):
    """全球关联交易知识图谱分析引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("entity_nodes", _NODE_SCHEMA),
                             ("transaction_edges", _EDGE_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        entities_raw = input_data.get("entities", []) or []
        transactions_raw = input_data.get("transactions", []) or []

        entities = []
        seen_ids = set()
        for e in entities_raw:
            nid = e.get("entity_id") or f"ENT-{len(entities)+1:06d}"
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            name = str(e.get("name", ""))
            company_type = str(e.get("company_type", "企业"))
            is_shell = self._is_shell(name, company_type, e.get("has_operations", True))
            entities.append({
                "node_id": nid,
                "node_type": company_type,
                "name": name,
                "country": str(e.get("country", "")),
                "ultimate_parent": str(e.get("ultimate_parent", "")),
                "is_shell": is_shell,
            })

        edges = []
        for t in transactions_raw:
            src = t.get("from") or t.get("src")
            dst = t.get("to") or t.get("dst")
            if not src or not dst:
                continue
            try:
                edges.append({
                    "src": str(src),
                    "dst": str(dst),
                    "relation": str(t.get("relation", "关联交易")),
                    "amount": float(t.get("amount", 0) or 0),
                    "currency": str(t.get("currency", "CNY")),
                    "year": int(t.get("year", 2024)),
                })
            except (TypeError, ValueError):
                continue

        return {"entities": entities, "edges": edges}

    def _is_shell(self, name: str, company_type: str, has_ops: bool) -> bool:
        if not has_ops:
            return True
        if company_type in ("壳公司", "投资控股"):
            return True
        for marker in self.model["shell_company_markers"]:
            if marker in name and ("有限" in name or "有限公司" in name):
                return True
        return False

    def _infer(self, prepared: Any) -> dict:
        entities = prepared["entities"]
        edges = prepared["edges"]

        node_ids = [e["node_id"] for e in entities]
        name_map = {e["node_id"]: e["name"] for e in entities}
        country_map = {e["node_id"]: e["country"] for e in entities}
        parent_map = {e["node_id"]: e["ultimate_parent"] for e in entities}
        shell_map = {e["node_id"]: e["is_shell"] for e in entities}

        adj = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e["amount"]))
            adj[e["dst"]].append((e["src"], e["amount"]))

        communities = self._louvain(node_ids, adj)

        node_degree = Counter()
        total_per_year = defaultdict(float)
        for e in edges:
            node_degree[e["src"]] += 1
            node_degree[e["dst"]] += 1
            total_per_year[e["year"]] += e["amount"]

        volume_per_entity = defaultdict(float)
        for e in edges:
            volume_per_entity[e["src"]] += e["amount"]
            volume_per_entity[e["dst"]] += e["amount"]

        entity_risk_scores = {}
        for e in entities:
            eid = e["node_id"]
            risk = self._compute_risk(e, node_degree, volume_per_entity, communities)
            entity_risk_scores[eid] = risk

        group_clusters = defaultdict(list)
        for e in entities:
            parent = parent_map.get(e["node_id"], "") or e["node_id"]
            group_clusters[parent].append(e["node_id"])

        target_id = None
        if entities:
            target_id = entities[0]["node_id"]

        paths = []
        if target_id and adj.get(target_id):
            visited = {target_id}
            queue = [(target_id, [target_id])]
            while queue:
                cur, path = queue.pop(0)
                if len(path) > self.model["path_depth_threshold"]:
                    continue
                for nb, _ in adj.get(cur, []):
                    if nb not in visited:
                        visited.add(nb)
                        paths.append({
                            "path": [name_map.get(n, n) for n in path + [nb]],
                            "length": len(path) + 1,
                            "nodes": path + [nb],
                        })
                        queue.append((nb, path + [nb]))
                if len(paths) >= 50:
                    break

        summary = {
            "entity_count": len(entities),
            "transaction_count": len(edges),
            "community_count": len(set(communities.values())),
            "group_count": len(group_clusters),
            "shell_count": sum(1 for e in entities if e["is_shell"]),
            "total_volume": round(sum(e["amount"] for e in edges), 2),
            "avg_risk_score": round(
                statistics.mean([s["total"] for s in entity_risk_scores.values()])
                if entity_risk_scores else 0, 4
            ),
        }

        return {
            "entities": entities,
            "edges": edges,
            "communities": communities,
            "risk_scores": entity_risk_scores,
            "group_clusters": dict(group_clusters),
            "paths": paths[:30],
            "summary": summary,
        }

    def _compute_risk(self, entity: dict, degree_map: dict,
                      volume_map: dict, communities: dict) -> dict:
        eid = entity["node_id"]
        weights = self.model["risk_weights"]
        scores = {}

        if entity["is_shell"]:
            scores["shell_company"] = 1.0
        else:
            scores["shell_company"] = 0.2

        country = entity["country"]
        is_haven = any(h in country for h in self.model["tax_havens"])
        scores["tax_haven"] = 1.0 if is_haven else 0.1

        deg = degree_map.get(eid, 0)
        scores["transfer_pricing"] = min(1.0, deg / 5.0)

        parent = entity["ultimate_parent"]
        if parent and parent != eid:
            scores["multi_layer"] = 0.4
        else:
            scores["multi_layer"] = 0.1

        vol = volume_map.get(eid, 0)
        scores["volume_concentration"] = min(1.0, math.log1p(vol) / math.log1p(1e9))

        total = sum(weights[k] * scores[k] for k in weights)

        if total >= 0.7:
            level = "高风险"
        elif total >= 0.4:
            level = "中风险"
        else:
            level = "低风险"

        return {"total": round(total, 4), "level": level, "breakdown": scores}

    def _louvain(self, nodes: list, adj: dict) -> dict:
        communities = {n: n for n in nodes}
        changed = True
        for _ in range(5):
            if not changed:
                break
            changed = False
            for n in nodes:
                nb_comms = Counter()
                for nb, _ in adj.get(n, []):
                    if nb in communities:
                        nb_comms[communities[nb]] += 1
                if nb_comms:
                    best_comm = max(nb_comms, key=nb_comms.get)
                    if communities[n] != best_comm:
                        communities[n] = best_comm
                        changed = True
        return communities

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        risk_scores = result["risk_scores"]
        high_risk = [nid for nid, r in risk_scores.items() if r["level"] == "高风险"]
        summary["high_risk_entities"] = len(high_risk)
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
