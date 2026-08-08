"""[FO-02] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析实体/交易 + 持久化到 PortableDB) → engine.execute(图构建→推理→后处理)
  → apply_thresholds(网络风险分级) → apply_custom_rules(业务规则)
  → output(持久化模式 + format_output 格式化舞弊网络报告)
"""
from __future__ import annotations

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
        # 显式触发模型加载：初始化 PortableDB + 默认模型
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> dict:
        """数据采集：解析实体与交易边，持久化到 PortableDB（审计追溯）。"""
        if not isinstance(input_data, dict):
            return {"entities": [], "transactions": []}

        db = self.engine.db
        if db is not None:
            # 建表（幂等）
            db.create_table("fraud_entities", {
                "entity_id": "TEXT", "name": "TEXT", "type": "TEXT",
                "industry": "TEXT", "country": "TEXT", "regist_date": "TEXT",
            })
            db.create_table("fraud_transactions", {
                "src": "TEXT", "dst": "TEXT", "amount": "REAL",
                "time": "TEXT", "txn_type": "TEXT", "note": "TEXT",
            })
            # 清空旧数据（每次 run 重新写入）
            db.delete("fraud_entities", "1=1")
            db.delete("fraud_transactions", "1=1")

            for e in input_data.get("entities", []) or []:
                if not isinstance(e, dict):
                    continue
                eid = e.get("entity_id") or str(e.get("name", ""))
                if not eid:
                    continue
                db.insert("fraud_entities", {
                    "entity_id": eid,
                    "name": str(e.get("name", "")),
                    "type": str(e.get("type", "公司")),
                    "industry": str(e.get("industry", "")),
                    "country": str(e.get("country", "")),
                    "regist_date": str(e.get("regist_date", "")),
                })
            for t in input_data.get("transactions", []) or []:
                if not isinstance(t, dict):
                    continue
                src = t.get("from") or t.get("src")
                dst = t.get("to") or t.get("dst")
                if not src or not dst:
                    continue
                try:
                    amount = float(t.get("amount", 0) or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                db.insert("fraud_transactions", {
                    "src": str(src), "dst": str(dst), "amount": amount,
                    "time": str(t.get("time", t.get("timestamp", ""))),
                    "txn_type": str(t.get("txn_type", "转账")),
                    "note": str(t.get("note", "")),
                })

        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化发现的模式到 PortableDB + 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把发现的舞弊模式写回 PortableDB fraud_patterns 表。"""
        db = self.engine.db
        if db is None:
            return
        db.create_table("fraud_patterns", {
            "pattern_type": "TEXT", "entities_involved": "JSON",
            "severity": "TEXT", "extra": "JSON", "created_at": "DATETIME",
        })
        db.delete("fraud_patterns", "1=1")
        for p in result.get("patterns", []) or []:
            if not isinstance(p, dict):
                continue
            db.insert("fraud_patterns", {
                "pattern_type": p.get("type", ""),
                "entities_involved": p.get("entities_involved", []),
                "severity": p.get("severity", ""),
                "extra": {k: v for k, v in p.items()
                          if k not in ("type", "entities_involved", "severity")},
                "created_at": datetime.now(),
            })
