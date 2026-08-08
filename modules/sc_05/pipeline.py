"""[SC-05] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析市场价/采购查询 + 持久化历史价) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(偏离分级) → apply_custom_rules(业务规则)
  → output(持久化基准/对标结果 + format_output)
"""
from __future__ import annotations

from typing import Any

from .engine import MLEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = MLEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 建表
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析市场历史价与采购对标查询，写入 price_histories 表（审计追溯）。"""
        if isinstance(input_data, dict):
            histories = input_data.get("price_history", []) or []
            queries = input_data.get("benchmark_queries", []) or []
        elif isinstance(input_data, list):
            histories = input_data
            queries = []
            input_data = {"price_history": histories, "benchmark_queries": []}
        else:
            histories = []
            queries = []
            input_data = {"price_history": [], "benchmark_queries": []}

        db = self.engine.db
        if db is not None:
            # 清空旧历史价（每次 run 重新写入）
            db.delete("price_histories", "1=1")
            for i, h in enumerate(histories):
                if not isinstance(h, dict):
                    continue
                try:
                    price = float(h.get("price", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if price <= 0:
                    continue
                record_id = str(
                    h.get("record_id") or f"H-{i + 1:06d}"
                )
                db.insert("price_histories", {
                    "record_id": record_id,
                    "category": str(h.get("category", "")),
                    "price": price,
                    "source": str(h.get("source", "市场")),
                    "record_date": str(h.get("record_date", "") or ""),
                })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化基准与对标结果 + 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把品类基准与对标结果写回 PortableDB。"""
        db = self.engine.db
        if db is None:
            return
        # 品类基准
        db.delete("category_baselines", "1=1")
        for cat, bl in result.get("baselines", {}).items():
            db.insert("category_baselines", {
                "category": cat,
                "baseline_price": float(bl.get("baseline_price", 0)),
                "low_bound": float(bl.get("low_bound", 0)),
                "high_bound": float(bl.get("high_bound", 0)),
                "percentiles": bl.get("percentiles", {}),
                "trend_slope": float(bl.get("trend_slope", 0)),
                "trend_r2": float(bl.get("trend_r2", 0)),
                "sample_count": int(bl.get("sample_count", 0)),
            })
        # 对标结果
        db.delete("benchmark_results", "1=1")
        for r in result.get("results", []):
            db.insert("benchmark_results", {
                "benchmark_id": r.get("benchmark_id"),
                "category": r.get("category"),
                "test_price": float(r.get("test_price", 0) or 0),
                "deviation_pct": (
                    float(r["deviation_pct"]) if r.get("deviation_pct") is not None
                    else None
                ),
                "position": r.get("position") or r.get("status"),
                "assessment": r.get("assessment", ""),
            })
