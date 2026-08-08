"""[CO-05] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析图谱节点/边 + 默认 action) → engine.execute(构建图→推理→后处理)
  → apply_thresholds(网络风险分级) → apply_custom_rules(业务规则)
  → output(格式化洗钱网络报告)
"""
from __future__ import annotations

from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = KGEngine(config)
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：归一化节点/边字段，设定默认 action。"""
        if not isinstance(input_data, dict):
            return {"action": "detect_patterns", "nodes": [], "edges": []}

        action = input_data.get("action", "detect_patterns")
        graph = input_data.get("graph", {}) or {}
        raw_nodes = input_data.get("nodes") or graph.get("nodes") or []
        raw_edges = input_data.get("edges") or graph.get("edges") or []

        # 归一化节点
        nodes = []
        for n in raw_nodes:
            if not isinstance(n, dict):
                continue
            nid = n.get("node_id") or n.get("id")
            if not nid:
                continue
            nodes.append({
                "node_id": str(nid),
                "node_type": n.get("node_type", n.get("type", "unknown")),
                "attrs": n.get("attrs", {}),
            })

        # 归一化边
        edges = []
        for e in raw_edges:
            if not isinstance(e, dict):
                continue
            src = e.get("src") or e.get("source")
            dst = e.get("dst") or e.get("target")
            if not src or not dst:
                continue
            edges.append({
                "src": str(src),
                "dst": str(dst),
                "edge_type": e.get("edge_type", e.get("type", "transfer")),
                "amount": float(e.get("amount", 0) or 0),
                "timestamp": str(e.get("timestamp", "")),
            })

        return {
            "action": action,
            "nodes": nodes,
            "edges": edges,
            "suspicious_node_ids": input_data.get("suspicious_node_ids", []),
        }

    def _output(self, result: Any) -> Any:
        """结果输出：格式化洗钱网络报告。"""
        return format_output(result)
