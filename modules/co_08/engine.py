"""[CO-08] 知识图谱数据流分析引擎 —— 纯 stdlib SQL血缘解析 + 图算法。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * SQL 血缘解析（正则 + 关键字匹配）：
      - 提取 FROM / JOIN / INTO / UPDATE 的表名引用
      - 提取 SELECT 字段与子查询别名
      - 支持多语句（分号分隔）
  * 数据血缘图构建：
      - 实体类型：System / Dataset / Column / Process / Location
      - 关系类型：PRODUCES / CONSUMES / TRANSFORMS / DERIVED_FROM
      - 邻接表（有向）+ 实体属性（位置/敏感等级）
  * 跨境传输识别：
      - 数据源 location.country ≠ 数据目标 location.country
      - 标记涉及敏感数据（CO-07 L3+）的跨境传输为高风险
  * 影响分析（BFS 反向溯源 + 正向影响）：
      - 上游影响：从目标节点 BFS 反向遍历所有上游依赖
      - 下游影响：从源节点 BFS 正向遍历所有下游消费者
  * 路径风险评分：路径上所有节点的敏感等级最高值 × 跨境标记权重

模型结构（self.model）：
  {
    "entities": {entity_id: {...}},
    "edges": [(src, dst, type, attrs)],
    "country_rules": {...},
  }
"""
from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "co_08.db"

_LOCATIONS_SCHEMA = {
    "location_id": "TEXT",
    "name": "TEXT",
    "country": "TEXT",
    "region": "TEXT",
    "is_cross_border": "INTEGER",
    "created_at": "DATETIME",
}
_ENTITIES_SCHEMA = {
    "entity_id": "TEXT",
    "entity_type": "TEXT",
    "name": "TEXT",
    "location_id": "TEXT",
    "sensitive_level": "TEXT",
    "owner": "TEXT",
    "created_at": "DATETIME",
}
_EDGES_SCHEMA = {
    "edge_id": "TEXT",
    "src_id": "TEXT",
    "dst_id": "TEXT",
    "edge_type": "TEXT",
    "process_id": "TEXT",
    "is_cross_border": "INTEGER",
    "risk_level": "TEXT",
    "created_at": "DATETIME",
}
_FLOWS_SCHEMA = {
    "flow_id": "TEXT",
    "src_id": "TEXT",
    "dst_id": "TEXT",
    "path": "JSON",
    "hops": "INTEGER",
    "is_cross_border": "INTEGER",
    "sensitive_types": "JSON",
    "risk_score": "REAL",
    "risk_level": "TEXT",
    "compliance_tags": "JSON",
    "created_at": "DATETIME",
}


_SQL_TABLE_RE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE)\s+([`\"\w.\[\]]+)",
    re.IGNORECASE,
)
_SQL_SUBQUERY_RE = re.compile(
    r"\b(FROM|JOIN)\s*\(([^)]*)\)\s*(?:AS\s+)?(\w+)",
    re.IGNORECASE,
)
_SQL_INSERT_INTO_RE = re.compile(
    r"\bINSERT\s+(?:INTO\s+)?([`\"\w.\[\]]+)",
    re.IGNORECASE,
)
_SQL_CREATE_AS_RE = re.compile(
    r"\bCREATE\s+(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\w.\[\]]+)\s+AS",
    re.IGNORECASE,
)


def _strip_table_alias(name: str) -> str:
    return name.strip().strip("`\"[]").split(".")[-1].lower()


def _parse_sql_tables(sql: str) -> dict[str, set[str]]:
    """解析 SQL 语句中的表引用，返回 {source_tables, target_tables}。"""
    if not sql:
        return {"sources": set(), "targets": set()}
    sources: set[str] = set()
    targets: set[str] = set()

    clean = re.sub(r"--[^\n]*", "", sql)
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)

    for m in _SQL_CREATE_AS_RE.finditer(clean):
        targets.add(_strip_table_alias(m.group(1)))
    for m in _SQL_INSERT_INTO_RE.finditer(clean):
        targets.add(_strip_table_alias(m.group(1)))

    for m in _SQL_TABLE_RE.finditer(clean):
        kw = m.group(0).split()[0].upper()
        tbl = _strip_table_alias(m.group(1))
        if tbl and not tbl.isdigit():
            if kw in ("INTO", "UPDATE"):
                targets.add(tbl)
            else:
                sources.add(tbl)

    return {"sources": sources, "targets": targets}


class KGEngine(AbstractEngine):
    """CO-08 知识图谱数据流分析引擎（纯 stdlib SQL血缘 + 图算法）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        """初始化 PortableDB 表结构 + 跨境规则字典。"""
        self.db = PortableDB(self.db_path)
        for table, schema in [
            ("locations", _LOCATIONS_SCHEMA),
            ("entities", _ENTITIES_SCHEMA),
            ("edges", _EDGES_SCHEMA),
            ("flows", _FLOWS_SCHEMA),
        ]:
            if table not in self.db.tables():
                self.db.create_table(table, schema)

        self.model = {
            "entities": {},
            "adj": defaultdict(dict),
            "adj_rev": defaultdict(dict),
            "countries": {},
        }

    def _preprocess(self, input_data: Any) -> Any:
        """解析输入的数据源、ETL作业、API调用 → 构建血缘图。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        raw_systems = input_data.get("systems", [])
        raw_datasets = input_data.get("datasets", [])
        raw_locations = input_data.get("locations", [])
        raw_processes = input_data.get("processes", [])
        target_analysis = input_data.get("target", {})

        for loc in raw_locations:
            loc_id = loc.get("location_id") or loc.get("id", "")
            if loc_id:
                self.model["countries"][loc_id] = loc.get("country", "")
                self.db.insert("locations", {
                    "location_id": loc_id,
                    "name": loc.get("name", loc_id),
                    "country": loc.get("country", ""),
                    "region": loc.get("region", ""),
                    "is_cross_border": 0,
                    "created_at": datetime.now(),
                })

        for sys in raw_systems:
            eid = sys.get("system_id") or sys.get("id", "")
            if eid:
                self.model["entities"][eid.lower()] = {
                    "entity_id": eid,
                    "entity_type": "System",
                    "name": sys.get("name", eid),
                    "location_id": sys.get("location_id", ""),
                    "sensitive_level": sys.get("sensitive_level", "L1"),
                    "owner": sys.get("owner", ""),
                }

        entities_map: dict[str, dict] = {}
        for ds in raw_datasets:
            eid = ds.get("dataset_id") or ds.get("id", "")
            if not eid:
                continue
            entity = {
                "entity_id": eid,
                "entity_type": "Dataset",
                "name": ds.get("name", eid),
                "location_id": ds.get("location_id", ""),
                "sensitive_level": ds.get("sensitive_level", ds.get("level", "L1")),
                "owner": ds.get("owner", ""),
                "source_system_id": ds.get("system_id", ""),
                "sources": set(),
                "targets": set(),
            }
            sql = ds.get("sql", "") or ""
            parsed = _parse_sql_tables(sql)
            for s in parsed["sources"]:
                entity["sources"].add(s)
            for t in parsed["targets"]:
                entity["targets"].add(t)
            entities_map[eid] = entity
            self.model["entities"][eid.lower()] = {
                "entity_id": eid,
                "entity_type": "Dataset",
                "name": entity["name"],
                "location_id": entity["location_id"],
                "sensitive_level": entity["sensitive_level"],
                "owner": entity["owner"],
            }

        raw_edges: list[dict] = []
        for ds in raw_datasets:
            ds_id = ds.get("dataset_id") or ds.get("id", "")
            sys_id = ds.get("system_id")
            if sys_id and ds_id:
                raw_edges.append({"src": sys_id, "dst": ds_id, "type": "PRODUCES"})
            for src_table in ds.get("sources", []):
                raw_edges.append({"src": src_table, "dst": ds_id, "type": "DERIVED_FROM"})
            for proc in raw_processes:
                proc_id = proc.get("process_id", "")
                if proc.get("output_dataset") == ds_id:
                    for inp in proc.get("input_datasets", []):
                        raw_edges.append({
                            "src": inp, "dst": ds_id,
                            "type": "TRANSFORMS", "process_id": proc_id,
                        })
                        if inp != proc.get("output_dataset"):
                            pass

        for e in raw_edges:
            src = e["src"].lower()
            dst = e["dst"].lower()
            etype = e["type"]
            self.model["adj"][src][dst] = {
                "edge_type": etype,
                "process_id": e.get("process_id", ""),
            }
            self.model["adj_rev"][dst][src] = {
                "edge_type": etype,
                "process_id": e.get("process_id", ""),
            }

        return {
            "entities": self.model["entities"],
            "adj": dict(self.model["adj"]),
            "adj_rev": dict(self.model["adj_rev"]),
            "target": target_analysis,
            "raw_datasets": raw_datasets,
        }

    def _infer(self, prepared: Any) -> Any:
        """核心推理：跨境传输检测 + 路径风险评分 + 影响分析。"""
        adj = prepared["adj"]
        adj_rev = prepared["adj_rev"]
        entities = prepared["entities"]
        countries = self.model["countries"]
        target = prepared.get("target", {})

        cross_border_flows = self._detect_cross_border(adj, entities, countries)
        all_paths = self._compute_all_paths(adj, adj_rev, entities, countries)

        upstream_impact: dict[str, list[dict]] = {}
        downstream_impact: dict[str, list[dict]] = {}
        if target:
            tid = target.get("entity_id", "").lower()
            max_depth = int(target.get("max_depth", 4))
            upstream_impact[tid] = self._bfs_trace(adj_rev, tid, max_depth)
            downstream_impact[tid] = self._bfs_trace(adj, tid, max_depth)

        risk_flows = self._score_flows(all_paths, entities, countries)

        return {
            "entities": entities,
            "flows": risk_flows,
            "cross_border_flows": cross_border_flows,
            "upstream_impact": upstream_impact,
            "downstream_impact": downstream_impact,
            "target": target,
        }

    def _detect_cross_border(self, adj: dict, entities: dict,
                             countries: dict) -> list[dict]:
        """检测跨境数据流：src 与 dst 的 location.country 不同。"""
        flows: list[dict] = []
        for src, neighbors in adj.items():
            src_loc = entities.get(src, {}).get("location_id", "")
            src_country = countries.get(src_loc, "")
            for dst, edge_info in neighbors.items():
                dst_loc = entities.get(dst, {}).get("location_id", "")
                dst_country = countries.get(dst_loc, "")
                if src_country and dst_country and src_country != dst_country:
                    flows.append({
                        "src_id": src,
                        "dst_id": dst,
                        "edge_type": edge_info["edge_type"],
                        "src_country": src_country,
                        "dst_country": dst_country,
                        "sensitive_level": entities.get(dst, {}).get("sensitive_level", "L0"),
                    })
        return flows

    def _compute_all_paths(self, adj: dict, adj_rev: dict, entities: dict,
                           countries: dict) -> list[dict]:
        """从所有实体出发 BFS 计算 2-4 跳路径，用于影响分析。"""
        max_hops = 4
        flows: list[dict] = []
        seen_pairs: set[tuple[str, str]] = set()

        for start_id in list(adj.keys())[:50]:
            queue: deque = deque([(start_id, 0, [start_id])])
            visited: set[str] = {start_id}
            while queue:
                current, hops, path = queue.popleft()
                if hops >= max_hops:
                    continue
                for neighbor in adj.get(current, {}):
                    if neighbor in visited and neighbor != start_id:
                        continue
                    new_path = path + [neighbor]
                    pair = (start_id, neighbor)
                    if pair not in seen_pairs and len(new_path) >= 3:
                        seen_pairs.add(pair)
                        flows.append({
                            "src_id": start_id,
                            "dst_id": neighbor,
                            "path": new_path,
                            "hops": len(new_path) - 1,
                        })
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, hops + 1, new_path))
        return flows

    def _bfs_trace(self, graph: dict, start_id: str, max_hops: int) -> list[dict]:
        """从 start_id 在指定方向 BFS 遍历，返回可达节点列表。"""
        results: list[dict] = []
        visited: dict[str, int] = {start_id: 0}
        queue: deque = deque([(start_id, 0)])
        while queue:
            current, hops = queue.popleft()
            if hops >= max_hops:
                continue
            for neighbor in graph.get(current, {}):
                if neighbor not in visited:
                    visited[neighbor] = hops + 1
                    results.append({"entity_id": neighbor, "hops": hops + 1})
                    queue.append((neighbor, hops + 1))
        return results

    def _score_flows(self, paths: list[dict], entities: dict,
                     countries: dict) -> list[dict]:
        """对每条路径计算风险评分：敏感等级 + 跨境标记 + 长度惩罚。"""
        level_scores = {"L0": 0, "L1": 10, "L2": 30, "L3": 60, "L4": 90}
        compliance_map = {
            "GDPR-Art.44": {"type": "cross_border_scc", "score": 10},
            "PIPL": {"type": "cross_border_security_assessment", "score": 15},
        }
        flows_with_risk: list[dict] = []
        for p in paths:
            path_ids = p["path"]
            sensitive_levels = [
                level_scores.get(entities.get(e, {}).get("sensitive_level", "L0"), 0)
                for e in path_ids
            ]
            max_sensitive = max(sensitive_levels) if sensitive_levels else 0
            avg_sensitive = sum(sensitive_levels) / len(sensitive_levels) if sensitive_levels else 0

            cross_border = False
            for i in range(len(path_ids) - 1):
                s_loc = entities.get(path_ids[i], {}).get("location_id", "")
                s_c = countries.get(s_loc, "")
                d_loc = entities.get(path_ids[i + 1], {}).get("location_id", "")
                d_c = countries.get(d_loc, "")
                if s_c and d_c and s_c != d_c:
                    cross_border = True
                    break

            cb_bonus = 20 if cross_border else 0
            length_penalty = p["hops"] * 2
            risk_score = min(max_sensitive + avg_sensitive + cb_bonus - length_penalty, 100)
            risk_level = self._risk_level(risk_score)

            flows_with_risk.append({
                **p,
                "is_cross_border": 1 if cross_border else 0,
                "max_sensitive_level": max_sensitive,
                "risk_score": round(risk_score, 2),
                "risk_level": risk_level,
                "compliance_tags": self._compliance_tags(cross_border, risk_level),
            })
        flows_with_risk.sort(key=lambda f: -f["risk_score"])
        return flows_with_risk

    def _risk_level(self, score: float) -> str:
        if score >= 80:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 40:
            return "medium"
        return "low"

    def _compliance_tags(self, cross_border: bool, risk_level: str) -> list[str]:
        tags: list[str] = []
        if cross_border:
            tags.append("cross_border_transfer")
            tags.append("GDPR-Art.44")
            tags.append("PIPL")
        if risk_level in ("high", "critical"):
            tags.append("needs_audit")
        return tags

    def _postprocess(self, result: Any) -> Any:
        """持久化流 + 生成统计摘要。"""
        flows = result.get("flows", [])
        cross_border = result.get("cross_border_flows", [])

        for f in flows:
            self.db.insert("flows", {
                "flow_id": f"{f['src_id']}->{f['dst_id']}",
                "src_id": f["src_id"],
                "dst_id": f["dst_id"],
                "path": f["path"],
                "hops": f["hops"],
                "is_cross_border": f.get("is_cross_border", 0),
                "sensitive_types": [],
                "risk_score": f["risk_score"],
                "risk_level": f["risk_level"],
                "compliance_tags": f["compliance_tags"],
                "created_at": datetime.now(),
            })

        level_counts: dict[str, int] = defaultdict(int)
        for f in flows:
            level_counts[f["risk_level"]] += 1

        result["statistics"] = {
            "total_entities": len(result.get("entities", {})),
            "total_flows": len(flows),
            "cross_border_count": len(cross_border),
            "by_risk_level": dict(level_counts),
            "high_risk_flows": sum(1 for f in flows if f["risk_level"] in ("high", "critical")),
        }
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
