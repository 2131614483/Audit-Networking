"""[SC-04] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析采购记录 + 持久化订单) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(异常分级) → apply_custom_rules(业务规则)
  → output(持久化异常结果 + format_output)
"""
from __future__ import annotations

from datetime import datetime
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
        """数据采集：解析采购订单记录，并写入 PortableDB purchase_orders 表（审计追溯）。"""
        if isinstance(input_data, dict):
            orders = input_data.get("orders", []) or []
        elif isinstance(input_data, list):
            orders = input_data
            input_data = {"orders": orders}
        else:
            orders = []
            input_data = {"orders": []}

        db = self.engine.db
        if db is not None:
            # 清空旧订单（每次 run 重新写入，保证与输入一致）
            db.delete("purchase_orders", "1=1")
            for i, o in enumerate(orders):
                if not isinstance(o, dict):
                    continue
                try:
                    unit_price = float(o.get("unit_price", 0) or 0)
                    qty = float(o.get("quantity", 1) or 1)
                    total = float(
                        o.get("total_amount", unit_price * qty) or 0
                    )
                except (TypeError, ValueError):
                    continue
                order_id = str(o.get("order_id") or f"O-{i + 1:06d}")
                db.insert("purchase_orders", {
                    "order_id": order_id,
                    "supplier_id": str(o.get("supplier_id", "")),
                    "category": str(o.get("category", "uncategorized")),
                    "unit_price": unit_price,
                    "quantity": qty,
                    "total_amount": total,
                    "order_date": str(o.get("order_date", "") or ""),
                })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB anomaly_results 表 + 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把异常检测结果写回 PortableDB anomaly_results 表。"""
        db = self.engine.db
        if db is None:
            return
        db.delete("anomaly_results", "1=1")
        now = datetime.now()
        for r in result.get("results", []):
            db.insert("anomaly_results", {
                "order_id": r.get("order_id"),
                "supplier_id": r.get("supplier_id"),
                "category": r.get("category"),
                "anomaly_score": float(r.get("anomaly_score", 0)),
                "anomaly_level": r.get("anomaly_level"),
                "indicators": r.get("indicators", {}),
                "detected_at": now,
            })
