"""[SC-02] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析供应商/关系并持久化) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(分级+集中度) → apply_custom_rules(业务规则)
  → output(持久化图谱分析结果 + format_output)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = KGEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 图算法参数
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析 suppliers/relations 并写入 PortableDB（审计追溯）。"""
        if not isinstance(input_data, dict):
            return input_data
        suppliers = input_data.get("suppliers", []) or []
        relations = input_data.get("relations", []) or []
        db = self.engine.db
        if db is None:
            return input_data
        # 清空旧数据（每次 run 重新写入，保证与输入一致）
        db.delete("suppliers", "1=1")
        db.delete("relations", "1=1")
        for s in suppliers:
            if not isinstance(s, dict):
                continue
            sid = s.get("supplier_id") or s.get("id") or ""
            if not sid:
                continue
            db.insert("suppliers", {
                "supplier_id": sid,
                "name": str(s.get("name", "")),
                "uscc": str(s.get("uscc", "")),
                "node_type": str(s.get("node_type", "supplier")),
                "attributes": s.get("attributes", {}),
                "created_at": datetime.now(),
            })
        for r in relations:
            if not isinstance(r, dict):
                continue
            src = r.get("source") or r.get("source_id")
            tgt = r.get("target") or r.get("target_id")
            if not src or not tgt:
                continue
            rtype = r.get("relation_type", r.get("type", "related"))
            raw_w = r.get("weight")
            try:
                weight = float(raw_w) if raw_w is not None else 1.0
            except (TypeError, ValueError):
                weight = 1.0
            db.insert("relations", {
                "source_id": src,
                "target_id": tgt,
                "relation_type": str(rtype),
                "weight": weight,
                "attributes": r.get("attributes", {}),
                "created_at": datetime.now(),
            })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化图谱分析到 PortableDB + 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把图谱分析结果（PageRank/社区/风险）写回 PortableDB graph_analysis 表。"""
        db = self.engine.db
        if db is None:
            return
        scan_id = (
            f"KG-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            f"-{uuid.uuid4().hex[:6]}"
        )
        db.delete("graph_analysis", "1=1")
        for n in result.get("nodes", []):
            db.insert("graph_analysis", {
                "supplier_id": n.get("supplier_id"),
                "pagerank": float(n.get("pagerank", 0.0)),
                "community_id": int(n.get("community_id", -1)),
                "risk_score": float(n.get("risk_score", 0.0)),
                "path_count": 0,
                "updated_at": datetime.now(),
            })
        # scan_id 记录在 summary 供追溯（不入库避免 schema 变更）
        summary = result.get("summary", {})
        if isinstance(summary, dict):
            summary["scan_id"] = scan_id
