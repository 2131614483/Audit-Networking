"""[FA-10] 知识图谱关联方发现引擎 —— 纯 stdlib 图算法 + BFS 多跳隐藏关联发现。

算法设计（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，不引入任何第三方依赖）：

  * 数据建模：实体（公司/自然人/地址/电话/银行账户）+ 关系（法人/股东/高管/
    地址/电话/账户/担保/合同），用 dict+set 构建邻接表
  * 派生共享关系：两家公司连接同一地址/电话/账户实体 → 派生 address_share /
    phone_share / account_share 直接边（缩短 BFS 路径，匹配业务"4跳"口径）
  * BFS 多跳发现：从目标实体出发，collections.deque 做 BFS 遍历 3-6 跳路径，
    发现隐藏关联（共享地址/电话/法人/股东/高管/银行账户）
  * 关联强度：path_strength = avg(关系权重) × (1.0 / hops)，
    权重序：法人(1.0) > 股东(0.9) > 高管(0.8) > 账户(0.7) > 担保(0.6)
            > 地址(0.5) > 电话(0.4) > 合同(0.3)
  * 环路检测：发现循环持股 / 交叉担保等异常结构

模型结构（self.model）：
  {
    "entity_types":   {type: 显示名},                  # 实体类型定义
    "relation_types": {type: {weight, display}},       # 关系类型定义+权重
    "graph":          {entity_id: {neighbor_id: rel_type}},  # 邻接表（双向）
    "directed":       {src: {dst: rel_type}},           # 有向关系（环路检测用）
    "entities":       {entity_id: entity_dict},         # 实体详情
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

# 模块根目录（用于定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fa_10.db"

# BFS 默认最大跳数（3-6 跳隐藏关联发现的核心区间）
_DEFAULT_MAX_HOPS = 5
# 默认最低关联强度：低于此值视为弱关联噪声
_MIN_STRENGTH = 0.1

# 实体类型定义
ENTITY_TYPES: dict[str, str] = {
    "company": "公司",
    "person": "自然人",
    "address": "地址",
    "phone": "电话",
    "account": "银行账户",
}

# 关系类型定义：type → {weight, display, bidirectional}
# 权重序：法人 > 股东 > 高管 > 账户 > 担保 > 地址 > 电话 > 合同
RELATION_TYPES: dict[str, dict[str, Any]] = {
    "legal_rep":     {"weight": 1.0, "display": "法定代表人", "bidirectional": True},
    "shareholder":   {"weight": 0.9, "display": "股东",       "bidirectional": True},
    "executive":     {"weight": 0.8, "display": "高管",       "bidirectional": True},
    "account":       {"weight": 0.7, "display": "银行账户",   "bidirectional": True},
    "guarantee":     {"weight": 0.6, "display": "担保",       "bidirectional": True},
    "address":       {"weight": 0.5, "display": "地址",       "bidirectional": True},
    "phone":         {"weight": 0.4, "display": "电话",       "bidirectional": True},
    "contract":      {"weight": 0.3, "display": "合同",       "bidirectional": True},
    # 派生关系类型（_preprocess 中自动生成，不来自输入）
    "address_share": {"weight": 0.5, "display": "共享地址",   "bidirectional": True},
    "phone_share":   {"weight": 0.4, "display": "共享电话",   "bidirectional": True},
    "account_share": {"weight": 0.7, "display": "共享账户",   "bidirectional": True},
}

# PortableDB 表 schema
_ENTITY_SCHEMA = {
    "entity_id": "TEXT",
    "entity_type": "TEXT",
    "name": "TEXT",
    "normalized_name": "TEXT",
    "uscc": "TEXT",           # 统一社会信用代码
    "id_card": "TEXT",        # 身份证号
    "phone": "TEXT",
    "address": "TEXT",
    "bank_account": "TEXT",
    "source": "TEXT",
    "raw": "JSON",
}
_RELATION_SCHEMA = {
    "src_entity_id": "TEXT",
    "dst_entity_id": "TEXT",
    "relation_type": "TEXT",
    "weight": "REAL",
    "source": "TEXT",
    "raw": "JSON",
}
_HIDDEN_LINK_SCHEMA = {
    "target_entity_id": "TEXT",
    "related_entity_id": "TEXT",
    "hops": "INTEGER",
    "strength": "REAL",
    "path": "JSON",
    "relation_types": "JSON",
    "is_hidden": "INTEGER",
    "rule_tags": "JSON",
    "created_at": "DATETIME",
}
_SCAN_RESULT_SCHEMA = {
    "target_entity_id": "TEXT",
    "total_related": "INTEGER",
    "hidden_count": "INTEGER",
    "strong_count": "INTEGER",
    "max_hops": "INTEGER",
    "statistics": "JSON",
    "created_at": "DATETIME",
}


def _normalize_name(name: str) -> str:
    """名称标准化：去首尾空格 + 统一全角/半角 + 去标点 + 小写。"""
    if not isinstance(name, str):
        name = str(name)
    name = name.strip()
    # 全角空格 → 半角
    name = name.replace("\u3000", " ")
    # 去标点（保留中英文/数字/下划线/空格）
    name = re.sub(r"[^\w\u4e00-\u9fff\s]", "", name, flags=re.UNICODE)
    # 多空格合一
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def _normalize_uscc(code: str) -> str:
    """统一社会信用代码标准化：去空格、统一大写、去标点。"""
    if not isinstance(code, str):
        code = str(code) if code else ""
    return re.sub(r"[^\w]", "", code).upper()


def _normalize_id_card(card: str) -> str:
    """身份证号标准化：去空格、统一大写。"""
    if not isinstance(card, str):
        card = str(card) if card else ""
    return re.sub(r"[^\w]", "", card).upper()


def _normalize_phone(phone: str) -> str:
    """电话号码标准化：只保留数字。"""
    if not isinstance(phone, str):
        phone = str(phone) if phone else ""
    return re.sub(r"\D", "", phone)


def _normalize_account(acc: str) -> str:
    """银行账户标准化：只保留数字字母。"""
    if not isinstance(acc, str):
        acc = str(acc) if acc else ""
    return re.sub(r"[^\w]", "", acc)


class MLEngine(AbstractEngine):
    """知识图谱关联方发现引擎（纯 stdlib 实现）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改：预处理 → 推理 → 后处理。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        # 允许 config 覆盖 fixtures / db 路径，便于测试隔离
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载实体类型/关系类型定义 + PortableDB 初始化。

        建表：entities（实体）/ relations（关系）/ hidden_links（隐藏关联）/ scan_results（扫描结果）。
        """
        # 1. 初始化 PortableDB（中心化公用辐射）
        self.db = PortableDB(self.db_path)

        # 2. 建表（若不存在）
        if "entities" not in self.db.tables():
            self.db.create_table("entities", _ENTITY_SCHEMA)
        if "relations" not in self.db.tables():
            self.db.create_table("relations", _RELATION_SCHEMA)
        if "hidden_links" not in self.db.tables():
            self.db.create_table("hidden_links", _HIDDEN_LINK_SCHEMA)
        if "scan_results" not in self.db.tables():
            self.db.create_table("scan_results", _SCAN_RESULT_SCHEMA)

        # 3. 模型 = 类型定义（图数据在 _preprocess / _infer 中构建）
        self.model = {
            "entity_types": dict(ENTITY_TYPES),
            "relation_types": {k: dict(v) for k, v in RELATION_TYPES.items()},
            "graph": {},
            "directed": {},
            "entities": {},
        }

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """提取多源实体与关系数据，清洗去重，构建邻接表。

        清洗项：统一社会信用代码、身份证号、名称标准化、电话/账户归一化。
        派生：两家公司连接同一地址/电话/账户实体 → 派生 address_share / phone_share /
        account_share 直接边。
        """
        # 懒加载：若未显式 setup()，execute() 时自动加载模型
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 entities / relations 列表")

        raw_entities = input_data.get("entities", [])
        raw_relations = input_data.get("relations", [])
        target_entity_id = input_data.get("target_entity_id") or input_data.get("target_entity_ids")
        max_hops = int(input_data.get("max_hops", _DEFAULT_MAX_HOPS))
        min_strength = float(input_data.get("min_strength", _MIN_STRENGTH))

        # 1. 实体清洗去重（entity_id 唯一）
        entities: dict[str, dict] = {}
        for e in raw_entities:
            if not isinstance(e, dict) or "entity_id" not in e:
                continue
            eid = str(e["entity_id"])
            etype = e.get("entity_type", "unknown")
            name = e.get("name", "")
            entities[eid] = {
                "entity_id": eid,
                "entity_type": etype,
                "name": name,
                "normalized_name": _normalize_name(name),
                "uscc": _normalize_uscc(e.get("uscc", "")),
                "id_card": _normalize_id_card(e.get("id_card", "")),
                "phone": _normalize_phone(e.get("phone", "")),
                "address": e.get("address", ""),
                "bank_account": _normalize_account(e.get("bank_account", "")),
                "source": e.get("source", "unknown"),
                "raw": e,
            }

        # 2. 关系清洗去重（src-dst-type 唯一），持久化到 DB
        relations: list[dict] = []
        seen_rels: set[tuple[str, str, str]] = set()
        for r in raw_relations:
            if not isinstance(r, dict):
                continue
            src = str(r.get("src_entity_id", ""))
            dst = str(r.get("dst_entity_id", ""))
            rtype = r.get("relation_type", "")
            if not src or not dst or not rtype:
                continue
            key = (src, dst, rtype)
            if key in seen_rels:
                continue
            seen_rels.add(key)
            weight = float(r.get("weight", RELATION_TYPES.get(rtype, {}).get("weight", 0.5)))
            relations.append({
                "src_entity_id": src,
                "dst_entity_id": dst,
                "relation_type": rtype,
                "weight": weight,
                "source": r.get("source", "unknown"),
                "raw": r,
            })

        # 3. 派生共享关系：同一地址/电话/账户实体连接多家公司 → 派生直接边
        derived = self._derive_share_relations(entities, relations)
        relations.extend(derived)

        # 4. 持久化到 PortableDB（entities + relations）
        self._persist_entities(entities)
        self._persist_relations(relations)

        # 5. 目标实体归一化（支持单个 id 或列表）
        if isinstance(target_entity_id, list):
            target_ids = [str(t) for t in target_entity_id]
        elif target_entity_id:
            target_ids = [str(target_entity_id)]
        else:
            target_ids = []

        return {
            "entities": entities,
            "relations": relations,
            "target_entity_ids": target_ids,
            "max_hops": max_hops,
            "min_strength": min_strength,
        }

    def _derive_share_relations(self, entities: dict, relations: list[dict]) -> list[dict]:
        """派生共享关系：两家公司连接同一地址/电话/账户实体 → 直接边。

        派生类型：
          - address  → address_share（公司↔公司）
          - phone    → phone_share（公司↔公司）
          - account  → account_share（公司↔公司）
        """
        # 按"共享实体类型"分组：{entity_id: [company_id, ...]}
        share_groups: dict[str, dict[str, list[str]]] = {
            "address": defaultdict(list),
            "phone": defaultdict(list),
            "account": defaultdict(list),
        }
        for rel in relations:
            rtype = rel["relation_type"]
            if rtype not in share_groups:
                continue
            src = rel["src_entity_id"]
            dst = rel["dst_entity_id"]
            # 公司 → 共享实体（地址/电话/账户）
            if entities.get(src, {}).get("entity_type") == "company":
                share_groups[rtype][dst].append(src)

        derived: list[dict] = []
        seen_pairs: set[tuple[str, str, str]] = set()
        for rtype, groups in share_groups.items():
            derived_type = f"{rtype}_share"
            weight = RELATION_TYPES.get(derived_type, {}).get("weight", 0.5)
            for _shared_eid, companies in groups.items():
                if len(companies) < 2:
                    continue
                # 两两配对公司 → 派生共享边
                for i in range(len(companies)):
                    for j in range(i + 1, len(companies)):
                        a, b = companies[i], companies[j]
                        pair = (a, b, derived_type)
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        derived.append({
                            "src_entity_id": a,
                            "dst_entity_id": b,
                            "relation_type": derived_type,
                            "weight": weight,
                            "source": "derived",
                            "raw": {"derived_from": rtype, "shared_entity": _shared_eid},
                        })
        return derived

    def _persist_entities(self, entities: dict[str, dict]) -> None:
        """持久化实体到 PortableDB entities 表。"""
        if self.db is None:
            return
        for eid, e in entities.items():
            existing = self.db.get("entities", "entity_id = :eid", {"eid": eid})
            row = {
                "entity_id": eid,
                "entity_type": e["entity_type"],
                "name": e["name"],
                "normalized_name": e["normalized_name"],
                "uscc": e["uscc"],
                "id_card": e["id_card"],
                "phone": e["phone"],
                "address": e["address"],
                "bank_account": e["bank_account"],
                "source": e["source"],
                "raw": e["raw"],
            }
            if existing:
                self.db.update("entities", row, "entity_id = :eid", {"eid": eid})
            else:
                self.db.insert("entities", row)

    def _persist_relations(self, relations: list[dict]) -> None:
        """持久化关系到 PortableDB relations 表。"""
        if self.db is None:
            return
        for r in relations:
            self.db.insert("relations", {
                "src_entity_id": r["src_entity_id"],
                "dst_entity_id": r["dst_entity_id"],
                "relation_type": r["relation_type"],
                "weight": r["weight"],
                "source": r["source"],
                "raw": r["raw"],
            })

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """核心推理：图构建 → BFS 多跳发现 → 关联强度 → 环路检测。"""
        model = self.model or {}
        rel_types = model.get("relation_types", RELATION_TYPES)
        entities = prepared["entities"]
        relations = prepared["relations"]
        target_ids = prepared["target_entity_ids"]
        max_hops = prepared["max_hops"]
        min_strength = prepared["min_strength"]

        # ① 图构建：邻接表（双向，保留最高权重关系）+ 有向多关系图（环路检测用）
        # 双向邻接表：entity_id → {neighbor: rel_type}（同边多关系时保留权重最高者）
        graph: dict[str, dict[str, str]] = defaultdict(dict)
        # 有向多关系图：src → {dst: set(rel_type)}（保留所有关系类型，用于环路检测）
        directed_multi: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
        for r in relations:
            src, dst, rtype = r["src_entity_id"], r["dst_entity_id"], r["relation_type"]
            new_weight = rel_types.get(rtype, {}).get("weight", 0.5)
            # 双向邻接表：保留权重最高的关系类型
            for a, b in [(src, dst), (dst, src)]:
                existing = graph[a].get(b)
                if existing is None or new_weight > rel_types.get(existing, {}).get("weight", 0.5):
                    graph[a][b] = rtype
            # 有向多关系图：累积所有关系类型
            directed_multi[src][dst].add(rtype)

        # 同步到 model
        model["graph"] = dict(graph)
        model["directed_multi"] = dict(directed_multi)
        model["entities"] = entities

        # ② BFS 多跳发现 + ③ 关联强度计算
        all_related: dict[str, list[dict]] = {}
        cycles_per_target: dict[str, list[dict]] = {}
        for target_id in target_ids:
            if target_id not in entities:
                continue
            related = self._bfs_multi_hop(graph, target_id, max_hops, rel_types, min_strength)
            all_related[target_id] = related

            # ④ 环路检测（针对目标实体的关联子图）
            cycles = self._detect_cycles(directed_multi, target_id, related)
            cycles_per_target[target_id] = cycles

        return {
            "entities": entities,
            "relations": relations,
            "target_entity_ids": target_ids,
            "related_parties": all_related,
            "cycles_per_target": cycles_per_target,
            "max_hops": max_hops,
            "min_strength": min_strength,
        }

    def _bfs_multi_hop(self, graph: dict, start_id: str, max_hops: int,
                       rel_types: dict, min_strength: float) -> list[dict]:
        """BFS 多跳发现：从 start_id 出发，遍历 max_hops 跳路径，发现隐藏关联。

        返回关联方列表（不含 start_id 自身），每项含 hops / path / strength / relation_types。
        强度公式：strength = avg(路径关系权重) × (1.0 / hops)
        """
        # visited: entity_id → (最短跳数, 最短路径, 路径关系类型列表, 所有路径)
        visited: dict[str, dict] = {
            start_id: {"hops": 0, "best_path": [start_id], "best_rel_types": [], "all_paths": []}
        }
        queue: deque = deque()
        queue.append((start_id, 0, [start_id], []))

        while queue:
            current, hops, path, rel_types_on_path = queue.popleft()
            if hops >= max_hops:
                continue
            neighbors = graph.get(current, {})
            for neighbor, rel_type in neighbors.items():
                new_hops = hops + 1
                new_path = path + [neighbor]
                new_rel_types = rel_types_on_path + [rel_type]

                if neighbor not in visited:
                    # 首次访问：记录最短路径
                    visited[neighbor] = {
                        "hops": new_hops,
                        "best_path": new_path,
                        "best_rel_types": new_rel_types,
                        "all_paths": [new_path],
                    }
                    if new_hops < max_hops:
                        queue.append((neighbor, new_hops, new_path, new_rel_types))
                elif new_hops == visited[neighbor]["hops"]:
                    # 同跳数的替代路径
                    visited[neighbor]["all_paths"].append(new_path)
                    if new_hops < max_hops:
                        queue.append((neighbor, new_hops, new_path, new_rel_types))

        # 构建关联方列表（排除 start_id）
        related: list[dict] = []
        for eid, info in visited.items():
            if eid == start_id:
                continue
            hops = info["hops"]
            rel_types_on_path = info["best_rel_types"]
            # 关联强度 = avg(关系权重) × (1.0 / hops)
            weights = [rel_types.get(rt, {}).get("weight", 0.5) for rt in rel_types_on_path]
            avg_weight = sum(weights) / len(weights) if weights else 0.0
            strength = round(avg_weight * (1.0 / hops), 4) if hops > 0 else 0.0

            # 隐藏关联标记：hops >= 3 为隐藏关联（3-6 跳核心发现区间）
            is_hidden = hops >= 3

            related.append({
                "entity_id": eid,
                "entity_type": self.model["entities"].get(eid, {}).get("entity_type", "unknown"),
                "name": self.model["entities"].get(eid, {}).get("name", ""),
                "hops": hops,
                "strength": strength,
                "path": info["best_path"],
                "relation_types": rel_types_on_path,
                "all_paths": info["all_paths"],
                "is_hidden": is_hidden,
            })

        # 按强度降序排列
        related.sort(key=lambda x: (-x["strength"], x["hops"]))
        return related

    def _detect_cycles(self, directed_multi: dict, target_id: str,
                       related: list[dict]) -> list[dict]:
        """环路检测：发现循环持股 / 交叉担保等异常结构。

        检测逻辑：
          1. 循环持股：目标实体 T 可达关联方 R，且 R 有 shareholder 关系指向 T
          2. 交叉担保：T 可达 R，且 R 有 guarantee 关系指向 T
          3. 互保/互持：关联子图内任意两实体间存在双向 shareholder / guarantee

        参数 directed_multi: 有向多关系图 {src: {dst: set(rel_type)}}。
        """
        cycles: list[dict] = []
        related_ids = {r["entity_id"] for r in related}

        # 1. 目标实体参与的环路（R → T）
        for r in related:
            rid = r["entity_id"]
            back_rels = directed_multi.get(rid, {}).get(target_id, set())
            if "shareholder" in back_rels:
                cycles.append({
                    "type": "circular_shareholding",
                    "entities": [target_id, rid],
                    "description": f"循环持股：{target_id} 可达 {rid}，且 {rid} 持股 {target_id}",
                    "risk_level": "high",
                })
            if "guarantee" in back_rels:
                cycles.append({
                    "type": "cross_guarantee",
                    "entities": [target_id, rid],
                    "description": f"交叉担保：{target_id} 可达 {rid}，且 {rid} 担保 {target_id}",
                    "risk_level": "high",
                })

        # 2. 关联子图内的互保/互持（A → B 且 B → A）
        seen_pairs: set[tuple[str, str, str]] = set()
        for a_id in related_ids:
            for b_id, rels_ab in directed_multi.get(a_id, {}).items():
                if b_id not in related_ids and b_id != target_id:
                    continue
                rels_ba = directed_multi.get(b_id, {}).get(a_id, set())
                for check_type in ("shareholder", "guarantee"):
                    if check_type in rels_ab and check_type in rels_ba:
                        pair_key = tuple(sorted([a_id, b_id])) + (check_type,)
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)
                        cycle_type = "circular_shareholding" if check_type == "shareholder" else "cross_guarantee"
                        desc = "互持股权" if check_type == "shareholder" else "互保"
                        cycles.append({
                            "type": cycle_type,
                            "entities": [a_id, b_id],
                            "description": f"{desc}：{a_id} ↔ {b_id}",
                            "risk_level": "high",
                        })

        return cycles

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """输出关联方网络 + 隐藏关联标记 + 统计。"""
        related_parties = result.get("related_parties", {})
        cycles_per_target = result.get("cycles_per_target", {})
        entities = result.get("entities", {})

        # 为每个目标实体构建网络输出
        networks: list[dict] = []
        for target_id, related in related_parties.items():
            target_cycles = cycles_per_target.get(target_id, [])
            hidden_links = [r for r in related if r["is_hidden"]]
            # 强关联：strength >= 0.8（与 custom_thresholds 一致，此处预标记）
            strong = [r for r in related if r["strength"] >= 0.8]
            max_hop_found = max((r["hops"] for r in related), default=0)

            # 附加环路标记到关联方
            cycle_tags: dict[str, list[str]] = defaultdict(list)
            for c in target_cycles:
                for eid in c["entities"]:
                    if eid != target_id:
                        cycle_tags[eid].append(c["type"])

            for r in related:
                r["rule_tags"] = cycle_tags.get(r["entity_id"], [])

            network = {
                "target_entity_id": target_id,
                "target_name": entities.get(target_id, {}).get("name", ""),
                "related_parties": related,
                "hidden_links": hidden_links,
                "cycles": target_cycles,
                "statistics": {
                    "total_entities": len(entities),
                    "total_relations": len(result.get("relations", [])),
                    "related_count": len(related),
                    "hidden_count": len(hidden_links),
                    "strong_count": len(strong),
                    "max_hops": max_hop_found,
                    "cycle_count": len(target_cycles),
                },
            }
            networks.append(network)

        result["networks"] = networks
        # 持久化 hidden_links + scan_results 到 PortableDB
        self._persist_results(networks)
        return result

    def _persist_results(self, networks: list[dict]) -> None:
        """持久化隐藏关联 + 扫描结果到 PortableDB。"""
        if self.db is None:
            return
        now = datetime.now()
        for net in networks:
            target_id = net["target_entity_id"]
            for r in net["related_parties"]:
                self.db.insert("hidden_links", {
                    "target_entity_id": target_id,
                    "related_entity_id": r["entity_id"],
                    "hops": r["hops"],
                    "strength": r["strength"],
                    "path": r["path"],
                    "relation_types": r["relation_types"],
                    "is_hidden": 1 if r["is_hidden"] else 0,
                    "rule_tags": r.get("rule_tags", []),
                    "created_at": now,
                })
            stats = net["statistics"]
            self.db.insert("scan_results", {
                "target_entity_id": target_id,
                "total_related": stats["related_count"],
                "hidden_count": stats["hidden_count"],
                "strong_count": stats["strong_count"],
                "max_hops": stats["max_hops"],
                "statistics": {**stats, "cycles": len(net["cycles"])},
                "created_at": now,
            })

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 PortableDB 连接。"""
        if self.db is not None:
            self.db.close()
            self.db = None
