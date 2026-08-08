"""[FO-01] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入数据 + 持久化交易) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(分级) → apply_custom_rules(业务规则)
  → output(持久化扫描结果 + format_output)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .engine import MLEngine, _parse_amount, _parse_hour
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = MLEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 导入 fraud_patterns fixtures
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；同时把交易写入 PortableDB transactions 表（审计追溯）。"""
        if isinstance(input_data, dict) and "transactions" in input_data:
            txs = input_data["transactions"]
        elif isinstance(input_data, list):
            txs = input_data
        else:
            txs = []
        db = self.engine.db
        if db is not None:
            # 清空旧交易（每次 run 重新写入，保证与输入一致）
            db.delete("transactions", "1=1")
            for i, t in enumerate(txs):
                if not isinstance(t, dict):
                    continue
                tx_id = str(t.get("tx_id") or t.get("id") or f"TX{i + 1:04d}")
                db.insert("transactions", {
                    "tx_id": tx_id,
                    "amount": _parse_amount(t.get("amount")),
                    "tx_date": str(t.get("date") or t.get("tx_date") or ""),
                    "tx_time": str(t.get("time") or t.get("tx_time") or ""),
                    "hour": _parse_hour(t.get("time") or t.get("tx_time")) or 0,
                    "counterparty": str(
                        t.get("counterparty") or t.get("party") or ""
                    ),
                    "counterparty_address": str(
                        t.get("counterparty_address") or t.get("address") or ""
                    ),
                    "counterparty_phone": str(
                        t.get("counterparty_phone") or t.get("phone") or ""
                    ),
                    "counterparty_legal_rep": str(
                        t.get("counterparty_legal_rep") or t.get("legal_rep") or ""
                    ),
                    "account_id": str(t.get("account_id", "")),
                    "description": str(t.get("description", "")),
                    "is_related_party": 1 if t.get("is_related_party") else 0,
                    "tx_type": str(t.get("tx_type", "transfer")),
                    "payload": t,
                })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把扫描结果与命中标记写回 PortableDB scan_results / fraud_flags 表。"""
        db = self.engine.db
        if db is None:
            return
        scan_id = (
            f"SCAN-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            f"-{uuid.uuid4().hex[:6]}"
        )
        # 清空旧扫描结果（每次 run 重新写入）
        db.delete("fraud_flags", "1=1")
        db.delete("scan_results", "1=1")

        weights = self.engine.model.get("layer_weights", {})

        # 写入可疑交易扫描结果
        for s in result.get("suspicious_transactions", []):
            db.insert("scan_results", {
                "scan_id": scan_id,
                "tx_id": s.get("tx_id"),
                "risk_score": float(s.get("risk_score", 0)),
                "risk_level": s.get("risk_level"),
                "hit_layers": s.get("hit_layers", []),
                "evidence_chain": s.get("evidence_chain", []),
                "matched_patterns": s.get("matched_patterns", []),
                "created_at": datetime.now(),
            })

        # 写入 fraud_flags（按层分解）
        flags_data = result.get("flags", {})
        for tx_id, f in flags_data.items():
            evidence = f.get("evidence_chain", [])
            if f.get("statistical"):
                stat_ev = [
                    e for e in evidence
                    if "Benford" in e or "Z-Score" in e or "IQR" in e
                ]
                db.insert("fraud_flags", {
                    "tx_id": tx_id,
                    "layer": "statistical",
                    "sub_layer": "benford_zscore_iqr",
                    "evidence": "; ".join(stat_ev),
                    "score_contribution": float(
                        weights.get("statistical", 0.30)
                    ),
                    "created_at": datetime.now(),
                })
            if f.get("unsupervised"):
                unsup_ev = [
                    e for e in evidence
                    if "iForest" in e or "重构" in e
                ]
                db.insert("fraud_flags", {
                    "tx_id": tx_id,
                    "layer": "unsupervised",
                    "sub_layer": "iso_forest",
                    "evidence": "; ".join(unsup_ev),
                    "score_contribution": float(
                        weights.get("unsupervised", 0.25)
                    ),
                    "created_at": datetime.now(),
                })
            if f.get("supervised_details"):
                sup_ev = [
                    e for e in evidence if "命中规则" in e
                ]
                db.insert("fraud_flags", {
                    "tx_id": tx_id,
                    "layer": "supervised",
                    "sub_layer": "rule_match",
                    "evidence": "; ".join(sup_ev),
                    "score_contribution": float(
                        weights.get("supervised", 0.30)
                    ),
                    "created_at": datetime.now(),
                })
            if f.get("graph"):
                graph_ev = [
                    e for e in evidence if "图谱" in e
                ]
                db.insert("fraud_flags", {
                    "tx_id": tx_id,
                    "layer": "graph",
                    "sub_layer": "hidden_link",
                    "evidence": "; ".join(graph_ev),
                    "score_contribution": float(
                        weights.get("graph", 0.15)
                    ),
                    "created_at": datetime.now(),
                })
