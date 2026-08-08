"""[FA-05] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析发函交易/验证请求) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(完整性分级) → apply_custom_rules(篡改/共识规则)
  → output(注入区块详情 → format_output 存证报告)
"""
from __future__ import annotations

from typing import Any

from .engine import BlockchainEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = BlockchainEngine(config)
        # 显式触发模型加载：初始化模拟区块链账本 + 创世块
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：把输入归一化为 engine 可处理的 dict。

        支持：
          * {"transactions": [...], "mode": ".."} —— 直接透传
          * [ {...}, {...} ]                       —— 列表包装为 transactions
          * {"confirmation_id": ..}                —— 单笔发函包装为列表
        """
        if isinstance(input_data, dict):
            if "transactions" in input_data or "mode" in input_data:
                txs = input_data.get("transactions")
                if txs is not None and not isinstance(txs, list):
                    txs = [txs] if isinstance(txs, dict) else []
                elif txs is None:
                    txs = []
                return {**input_data, "transactions": [
                    t for t in txs if isinstance(t, dict)
                ]}
            if "confirmation_id" in input_data:
                return {"transactions": [input_data]}
            return {"transactions": []}
        if isinstance(input_data, list):
            return {"transactions": [t for t in input_data if isinstance(t, dict)]}
        raise ValueError("input_data 必须为 dict 或 list，含 transactions")

    def _output(self, result: Any) -> Any:
        """结果输出：注入区块详情后格式化为对外存证报告。"""
        if isinstance(result, dict) and "certificate" in result:
            chain = self.engine.model.get("chain", [])
            result["chain_blocks"] = [
                {
                    "index": b.get("index"),
                    "timestamp": b.get("timestamp"),
                    "merkle_root": b.get("merkle_root"),
                    "prev_hash": b.get("prev_hash"),
                    "hash": b.get("hash"),
                    "tx_count": len(b.get("transactions", [])),
                    "tx_ids": [t.get("tx_id") for t in b.get("transactions", [])],
                }
                for b in chain
            ]
        return format_output(result)
