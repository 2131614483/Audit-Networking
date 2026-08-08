"""[CO-04] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析交易 + 客户数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(风险分级) → apply_custom_rules(业务规则)
  → output(格式化 AML 告警报告)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


def _parse_amount(value: Any) -> float:
    """金额转 float：支持字符串（含千分位/货币符号/万/亿单位）。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    s = re.sub(r"[¥$€£,\s]", "", s)
    multiplier = 1.0
    if s.endswith("万"):
        s = s[:-1]
        multiplier = 10000.0
    elif s.endswith("亿"):
        s = s[:-1]
        multiplier = 100000000.0
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def _parse_hour(value: Any) -> int:
    """从小时字段或时间字符串提取小时（缺失默认 12）。"""
    if value is None:
        return 12
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return 12
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time().hour
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).hour
    except ValueError:
        return 12


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
        """数据采集：解析交易金额/时间，归一化字段，透传给引擎。"""
        if isinstance(input_data, dict) and "transactions" in input_data:
            raw_txs = input_data["transactions"]
            customers = input_data.get("customers", [])
        elif isinstance(input_data, list):
            raw_txs = input_data
            customers = []
        else:
            raw_txs = []
            customers = []

        cleaned = []
        for i, t in enumerate(raw_txs):
            if not isinstance(t, dict):
                continue
            tx_id = str(t.get("tx_id") or t.get("id") or f"TX{i + 1:04d}")
            cleaned.append({
                "tx_id": tx_id,
                "customer_id": str(t.get("customer_id", "?")),
                "amount": _parse_amount(t.get("amount")),
                "channel": str(t.get("channel", "online")),
                "jurisdiction": str(t.get("jurisdiction", "")),
                "counterparty": str(t.get("counterparty", "")),
                "hour": _parse_hour(t.get("hour") or t.get("time")),
                "tx_type": str(t.get("tx_type", "transfer")),
                "tx_date": str(t.get("tx_date") or t.get("date", "")),
            })

        return {"transactions": cleaned, "customers": customers}

    def _output(self, result: Any) -> Any:
        """结果输出：格式化 AML 告警报告。"""
        return format_output(result)
