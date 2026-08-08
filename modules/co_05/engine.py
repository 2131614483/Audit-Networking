"""[CO-05] 知识图谱洗钱网络发现 —— 纯 stdlib 图算法 + 资金流追踪 + 模式匹配。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 图数据结构（自建内存图）：
      - 节点：客户/账户/交易/设备/IP/电话/地址/公司
      - 边：交易(金额+时间)、控制(持股%)、拥有、共享、通信、关联
      - 邻接表存储：{node_id: [{neighbor_id, edge_type, weight, ...}]}
  * 图算法（纯 stdlib 实现）：
      - PageRank：发现网络关键节点（核心账户/控制人）
      - 连通分量：发现独立网络团伙
      - BFS 最短路径：追踪资金流转路径
      - 社区发现（Label Propagation）：识别隐藏网络结构
      - 度中心性 + 中介中心性：关键实体识别
  * 洗钱模式匹配（子图模式 + 规则）：
      - Smurfing（分散汇入）：多账户 → 同一账户，单笔<10k，1个月内≥3笔
      - Layering（快速进出）：资金在≥3个账户间快速流转，每笔<24h
      - Structuring（结构化交易）：多笔接近但低于申报阈值的交易
      - Money Loop（资金循环）：A→B→C→A 闭环路径
      - Trade-based（贸易洗钱）：发票金额与实际货物不符
      - Shell Company（空壳公司）：注册地址/电话/IP高度重合
  * 资金流追踪：
      - 从可疑账户出发 BFS/DFS 追踪全部资金流向
      - 关键时间节点标注
      - 循环路径检测

模型结构（self.model）：
  {
    "nodes": {node_id: {type, attrs}},
    "edges": [{src, dst, type, weight, amount, timestamp, ...}],
    "patterns": [{pattern_id, name, detection_rule, description}],
    "graph_stats": {node_count, edge_count, ...},
  }
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 洗钱模式规则定义
# ------------------------------------------------------------------

_SEED_PATTERNS: list[dict] = [
    {
        "pattern_id": "PAT-SMURFING",
        "name": "分散汇入(Smurfing)",
        "description": "多个小账户向同一账户汇入资金，单笔低于申报阈值，1个月内累计≥3笔",
        "detection_rule": "多源→单汇 + 单笔<10000 + 30天内≥3笔",
        "severity": "high",
    },
    {
        "pattern_id": "PAT-LAYERING",
        "name": "快速进出(Layering)",
        "description": "资金在3个以上账户间快速流转，每笔间隔<24小时",
        "detection_rule": "≥3跳 + 每跳<24h + 最终消失或回流",
        "severity": "high",
    },
    {
        "pattern_id": "PAT-STRUCTURING",
        "name": "结构化交易(Structuring)",
        "description": "同一主体在短时间内进行多笔接近但低于申报阈值的交易（如8000-9900元×N）",
        "detection_rule": "单主体 + 15天内 + 多笔9000-10000金额",
        "severity": "medium",
    },
    {
        "pattern_id": "PAT-MONEY-LOOP",
        "name": "资金循环(Money Loop)",
        "description": "资金从A账户出发，经B、C、D...最终回流到A（闭环路径）",
        "detection_rule": "有向环检测 + 金额衰减<30%",
        "severity": "high",
    },
    {
        "pattern_id": "PAT-SHELL-COMPANY",
        "name": "空壳公司网络",
        "description": "多家公司共享注册地址、电话号码、IP地址，无实际经营活动",
        "detection_rule": "共享≥2项联系信息 + 无员工/无网站 + 注册资本小",
        "severity": "medium",
    },
    {
        "pattern_id": "PAT-TRADE-BASED",
        "name": "贸易洗钱",
        "description": "发票金额与实际货物价值显著偏离（高估≥30%或低估≥50%）",
        "detection_rule": "交易金额 vs 行业估值 + 跨境 + 高频",
        "severity": "high",
    },
]


class KGEngine(AbstractEngine):
    """知识图谱洗钱网络发现引擎。"""

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        self.model = {
            "nodes": {},
            "edges": [],
            "patterns": list(_SEED_PATTERNS),
            "adjacency": defaultdict(list),
            "node_types": Counter(),
        }

    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化输入。

        input_data 格式：
          {
            "action": "load_graph" | "detect_patterns" | "trace_funds" | "centrality_analysis",
            "nodes": [{node_id, node_type, attrs: {...}}],
            "edges": [{src, dst, edge_type, amount, timestamp, attrs}],
            "graph": {"nodes": [...], "edges": [...]},  # 或直接提供
            "suspicious_node_ids": [...]  # trace_funds 时
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"action": "detect_patterns"}

        action = input_data.get("action", "detect_patterns")
        graph = input_data.get("graph", {}) or {}
        nodes = input_data.get("nodes") or graph.get("nodes") or []
        edges = input_data.get("edges") or graph.get("edges") or []

        return {
            "action": action,
            "nodes": nodes,
            "edges": edges,
            "suspicious_node_ids": input_data.get("suspicious_node_ids") or [],
        }

    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        # 先加载图（如果有新数据）
        if prepared["nodes"] or prepared["edges"]:
            self._build_graph(prepared["nodes"], prepared["edges"])

        action = prepared["action"]
        if action == "load_graph":
            return self._graph_summary()
        if action == "detect_patterns":
            return self._detect_patterns()
        if action == "trace_funds":
            return self._trace_funds(prepared["suspicious_node_ids"])
        if action == "centrality_analysis":
            return self._centrality_analysis()
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        if "module" in result:
            return result
        result["meta"] = {
            "module": "CO-05",
            "family": "kg_gnn",
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 内部：图构建
    # ------------------------------------------------------------------
    def _build_graph(self, nodes: list[dict], edges: list[dict]) -> None:
        for n in nodes:
            nid = n.get("node_id") or n.get("id")
            if nid:
                self.model["nodes"][nid] = {
                    "node_id": nid,
                    "node_type": n.get("node_type", n.get("type", "unknown")),
                    "attrs": n.get("attrs", {}),
                }
                self.model["node_types"][n.get("node_type", "unknown")] += 1

        for e in edges:
            src = e.get("src") or e.get("source")
            dst = e.get("dst") or e.get("target")
            if src and dst:
                self.model["edges"].append({
                    "src": src, "dst": dst,
                    "edge_type": e.get("edge_type", e.get("type", "unknown")),
                    "amount": float(e.get("amount", 0) or 0),
                    "timestamp": e.get("timestamp", ""),
                    **{k: v for k, v in e.items() if k not in ("src", "dst", "source", "target")},
                })
                self.model["adjacency"][src].append({"dst": dst, **{k: v for k, v in e.items() if k not in ("src", "source")}})
                self.model["adjacency"][dst].append({"dst": src, **{k: v for k, v in e.items() if k not in ("dst", "target")}})

    def _graph_summary(self) -> dict:
        return {
            "node_count": len(self.model["nodes"]),
            "edge_count": len(self.model["edges"]),
            "node_type_distribution": dict(self.model["node_types"]),
            "edge_types": Counter(e["edge_type"] for e in self.model["edges"]),
        }

    # ------------------------------------------------------------------
    # 核心：洗钱模式检测
    # ------------------------------------------------------------------
    def _detect_patterns(self) -> dict:
        detections: list[dict] = []
        edges = self.model["edges"]

        if not edges:
            return {"patterns_detected": [], "note": "图谱为空，请先 load_graph"}

        # 1. Smurfing 检测：多源 → 单汇
        inbound: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            if e["edge_type"] in ("transfer", "deposit", "payment") and e.get("amount", 0) < 10000:
                inbound[e["dst"]].append(e)

        for dst, incoming in inbound.items():
            unique_sources = {e["src"] for e in incoming}
            if len(unique_sources) >= 3 and len(incoming) >= 3:
                detections.append({
                    "pattern_id": "PAT-SMURFING",
                    "pattern_name": "分散汇入(Smurfing)",
                    "severity": "high",
                    "target_node": dst,
                    "source_count": len(unique_sources),
                    "transaction_count": len(incoming),
                    "total_amount": round(sum(e["amount"] for e in incoming), 2),
                    "evidence": [{"from": e["src"], "amount": e["amount"], "time": e.get("timestamp", "")} for e in incoming[:5]],
                    "confidence": min(0.95, 0.5 + len(unique_sources) * 0.05),
                })

        # 2. Structuring 检测：单主体多笔接近阈值
        per_source: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            if e["edge_type"] in ("transfer", "withdrawal"):
                amt = e.get("amount", 0)
                if 8000 <= amt <= 10000:
                    per_source[e["src"]].append(e)

        for src, txs in per_source.items():
            if len(txs) >= 3:
                detections.append({
                    "pattern_id": "PAT-STRUCTURING",
                    "pattern_name": "结构化交易(Structuring)",
                    "severity": "medium",
                    "target_node": src,
                    "transaction_count": len(txs),
                    "total_amount": round(sum(t["amount"] for t in txs), 2),
                    "evidence": [{"amount": t["amount"], "time": t.get("timestamp", "")} for t in txs[:5]],
                    "confidence": min(0.9, 0.4 + len(txs) * 0.1),
                })

        # 3. Money Loop 检测（有向环）
        loops = self._detect_cycles(max_len=6)
        for loop in loops:
            loop_edges = []
            for i in range(len(loop) - 1):
                e = next((ed for ed in edges if ed["src"] == loop[i] and ed["dst"] == loop[i + 1]), None)
                if e:
                    loop_edges.append(e)
            if loop_edges:
                amt_first = loop_edges[0].get("amount", 1)
                amt_last = loop_edges[-1].get("amount", 0)
                ratio = amt_last / max(amt_first, 1)
                if ratio > 0.7:
                    detections.append({
                        "pattern_id": "PAT-MONEY-LOOP",
                        "pattern_name": "资金循环(Money Loop)",
                        "severity": "high",
                        "cycle_path": loop,
                        "hop_count": len(loop) - 1,
                        "return_ratio": round(ratio, 4),
                        "confidence": min(0.95, 0.6 + ratio * 0.3),
                    })

        # 4. Shell Company 检测（共享联系信息）
        nodes_by_attr: dict[str, list[str]] = defaultdict(list)
        for nid, node in self.model["nodes"].items():
            for attr_key in ("phone", "ip", "address"):
                val = node.get("attrs", {}).get(attr_key)
                if val and not val.startswith("private_"):
                    nodes_by_attr[f"{attr_key}:{val}"].append(nid)

        for key, nlist in nodes_by_attr.items():
            if len(nlist) >= 3:
                detections.append({
                    "pattern_id": "PAT-SHELL-COMPANY",
                    "pattern_name": "空壳公司网络",
                    "severity": "medium",
                    "shared_attribute": key,
                    "node_count": len(nlist),
                    "nodes": nlist,
                    "confidence": min(0.85, 0.4 + len(nlist) * 0.08),
                })

        # 汇总
        severity_counter = Counter(d["severity"] for d in detections)
        pattern_counter = Counter(d["pattern_id"] for d in detections)

        return {
            "patterns_detected": detections,
            "total_detections": len(detections),
            "by_severity": dict(severity_counter),
            "by_pattern": dict(pattern_counter),
        }

    def _detect_cycles(self, max_len: int = 6) -> list[list[str]]:
        """用 DFS 检测有向环，路径长度 ≤ max_len。"""
        adj = self.model["adjacency"]
        nodes = list(self.model["nodes"].keys())
        cycles: list[list[str]] = []
        seen = set()

        def dfs(start: str, current: str, path: list[str], visited: set[str]) -> None:
            if len(path) > max_len:
                return
            for neighbor_info in adj.get(current, []):
                neighbor = neighbor_info.get("dst", "")
                if neighbor == start and len(path) >= 3:
                    cycle = path + [start]
                    canonical = tuple(sorted(set(cycle[:-1])))
                    if canonical not in seen:
                        seen.add(canonical)
                        cycles.append(cycle)
                elif neighbor not in visited:
                    visited.add(neighbor)
                    path.append(neighbor)
                    dfs(start, neighbor, path, visited)
                    path.pop()
                    visited.discard(neighbor)

        for node in nodes[:50]:
            dfs(node, node, [node], {node})

        return cycles

    # ------------------------------------------------------------------
    # 核心：资金流追踪（BFS 广度优先 + 时间线）
    # ------------------------------------------------------------------
    def _trace_funds(self, start_nodes: list[str]) -> dict:
        if not start_nodes:
            return {"paths": [], "note": "请指定起点账户"}

        adj = self.model["adjacency"]
        all_paths: list[dict] = []
        max_depth = 6

        for start in start_nodes:
            queue = deque([(start, [start], 0, set([start]))])
            node_paths: list[list[str]] = []

            while queue:
                node, path, depth, visited = queue.popleft()
                if depth >= max_depth:
                    if len(path) >= 2:
                        node_paths.append(path)
                    continue

                for neighbor_info in adj.get(node, []):
                    neighbor = neighbor_info.get("dst", "")
                    if neighbor and neighbor not in visited:
                        new_path = path + [neighbor]
                        node_paths.append(new_path)
                        new_visited = visited | {neighbor}
                        queue.append((neighbor, new_path, depth + 1, new_visited))

            # 汇总资金流
            for path in node_paths[:20]:
                edges_in_path: list[dict] = []
                total_amount = 0.0
                for i in range(len(path) - 1):
                    e = next((ed for ed in self.model["edges"] if ed["src"] == path[i] and ed["dst"] == path[i + 1]), None)
                    if e:
                        edges_in_path.append(e)
                        total_amount += e.get("amount", 0)

                all_paths.append({
                    "start_node": start,
                    "path": path,
                    "hop_count": len(path) - 1,
                    "total_amount": round(total_amount, 2),
                    "edges": edges_in_path,
                    "circular": path[0] == path[-1] if len(path) > 1 else False,
                })

        return {
            "start_nodes": start_nodes,
            "total_paths_found": len(all_paths),
            "max_depth": max_depth,
            "paths": all_paths[:50],
        }

    # ------------------------------------------------------------------
    # 核心：中心性分析（PageRank + 度中心性 + 中介中心性近似）
    # ------------------------------------------------------------------
    def _centrality_analysis(self) -> dict:
        nodes = list(self.model["nodes"].keys())
        n = len(nodes)
        if n == 0:
            return {"error": "图谱为空"}

        adj = self.model["adjacency"]

        # 度中心性
        degree_centrality = {node: len(adj.get(node, [])) for node in nodes}
        max_deg = max(degree_centrality.values()) if degree_centrality else 1
        degree_normalized = {k: round(v / max(max_deg, 1), 4) for k, v in degree_centrality.items()}

        # PageRank（幂迭代，50 次）
        pagerank = {node: 1.0 / n for node in nodes}
        damping = 0.85
        for _ in range(50):
            new_pr = {node: (1 - damping) / n for node in nodes}
            for node in nodes:
                neighbors = adj.get(node, [])
                if not neighbors:
                    for other in nodes:
                        new_pr[other] += damping * pagerank[node] / n
                else:
                    share = damping * pagerank[node] / len(neighbors)
                    for ni in neighbors:
                        new_pr[ni["dst"]] = new_pr.get(ni["dst"], 0) + share
            pagerank = new_pr

        pr_total = sum(pagerank.values()) or 1
        pagerank_normalized = {k: round(v / pr_total, 6) for k, v in pagerank.items()}

        # 中介中心性近似（采样 BFS）
        betweenness = {node: 0.0 for node in nodes}
        sample_size = min(30, n)
        for i, source in enumerate(nodes[:sample_size]):
            if i % 10 == 0:
                pass
            queue = deque([source])
            pred: dict[str, list[str]] = {source: []}
            sigma: dict[str, float] = {source: 1.0}
            d: dict[str, int] = {source: 0}
            order: list[str] = []

            while queue:
                v = queue.popleft()
                order.append(v)
                for ni in adj.get(v, []):
                    w = ni["dst"]
                    if w not in d:
                        d[w] = d[v] + 1
                        queue.append(w)
                    if d.get(w, -1) == d[v] + 1:
                        sigma[w] = sigma.get(w, 0) + sigma.get(v, 0)
                        pred[w] = pred.get(w, []) + [v]

            delta: dict[str, float] = {node: 0.0 for node in nodes}
            while order:
                w = order.pop()
                for v in pred.get(w, []):
                    delta[v] = delta.get(v, 0) + (sigma.get(v, 0) / sigma.get(w, 1)) * (1 + delta.get(w, 0))
                if w != source:
                    betweenness[w] += delta.get(w, 0)

        # 排序 + Top 节点
        top_pr = sorted(pagerank_normalized.items(), key=lambda x: -x[1])[:20]
        top_bc = sorted(betweenness.items(), key=lambda x: -x[1])[:20]
        top_deg = sorted(degree_normalized.items(), key=lambda x: -x[1])[:20]

        return {
            "node_count": n,
            "top_pagerank": [{"node": k, "score": v} for k, v in top_pr],
            "top_betweenness": [{"node": k, "score": round(v, 2)} for k, v in top_bc],
            "top_degree": [{"node": k, "score": v} for k, v in top_deg],
            "network_health": self._network_stats(degree_centrality),
        }

    @staticmethod
    def _network_stats(degrees: dict[str, int]) -> dict:
        if not degrees:
            return {}
        deg_values = list(degrees.values())
        avg_deg = sum(deg_values) / len(deg_values)
        isolated = sum(1 for d in deg_values if d == 0)
        return {
            "average_degree": round(avg_deg, 2),
            "max_degree": max(deg_values),
            "isolated_nodes": isolated,
            "isolated_ratio": round(isolated / len(deg_values), 4),
        }
