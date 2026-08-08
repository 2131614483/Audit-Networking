"""[SC-03] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析供应商指标并持久化) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(分级+风险档) → apply_custom_rules(业务规则)
  → output(持久化预警记录 + format_output)
"""
from __future__ import annotations

import uuid
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
        # 显式触发模型加载：初始化 PortableDB + 监控参数
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析 suppliers 指标时序并写入 PortableDB（审计追溯）。"""
        if not isinstance(input_data, dict):
            return input_data
        suppliers = input_data.get("suppliers", []) or []
        db = self.engine.db
        if db is None:
            return input_data
        # 清空旧指标（每次 run 重新写入，保证与输入一致）
        db.delete("supplier_metrics", "1=1")
        for s in suppliers:
            if not isinstance(s, dict):
                continue
            sid = s.get("supplier_id") or ""
            if not sid:
                continue
            metrics = s.get("metrics", {}) or {}
            for mname, values in metrics.items():
                if not isinstance(values, (list, tuple)):
                    continue
                for i, v in enumerate(values):
                    if v is None:
                        continue
                    try:
                        val = float(v)
                    except (TypeError, ValueError):
                        continue
                    db.insert("supplier_metrics", {
                        "supplier_id": sid,
                        "metric_name": str(mname),
                        "metric_value": val,
                        "timestamp": f"t{i}",
                    })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化预警到 PortableDB + 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把预警记录写回 PortableDB risk_alerts 表。"""
        db = self.engine.db
        if db is None:
            return
        scan_id = (
            f"MON-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            f"-{uuid.uuid4().hex[:6]}"
        )
        db.delete("risk_alerts", "1=1")
        for s in result.get("suppliers", []):
            sid = s.get("supplier_id")
            overall = float(s.get("overall_risk_score", 0.0))
            level = s.get("alert_level", "")
            alerts = s.get("alerts", []) or []
            if not alerts:
                # 无明细告警也记录一条总览（便于追溯）
                db.insert("risk_alerts", {
                    "supplier_id": sid,
                    "metric_name": "",
                    "alert_level": level,
                    "alert_score": overall,
                    "description": "overall_summary",
                    "details": {"scan_id": scan_id},
                    "created_at": datetime.now(),
                })
            for alert in alerts:
                if not isinstance(alert, dict):
                    continue
                db.insert("risk_alerts", {
                    "supplier_id": sid,
                    "metric_name": alert.get("metric_name", ""),
                    "alert_level": level,
                    "alert_score": overall,
                    "description": str(alert.get("type", "")),
                    "details": alert,
                    "created_at": datetime.now(),
                })
        summary = result.get("summary", {})
        if isinstance(summary, dict):
            summary["scan_id"] = scan_id
