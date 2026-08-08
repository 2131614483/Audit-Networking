"""[FA-11] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析关联交易/可比价格/历史价格) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(偏离率分级) → apply_custom_rules(业务规则)
  → output(format_output)
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
        # MLEngine 以 name 构造，config 透传至 self.engine.config 供 custom_* 读取
        self.engine = MLEngine(config if isinstance(config, dict) else "fa_11")
        if isinstance(config, dict):
            self.engine.config = config
        # 显式触发模型加载：初始化行业容忍度 _industry_bias
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析关联交易、可比公司价格、历史价格趋势。

        兼容多种输入形态：
          * dict 含 transactions/peers/history → 原样补全默认值
          * dict 含中文键 交易/可比数据/历史价格 → 归一化为英文键
          * 裸 list → 视为 transactions 列表
        """
        if isinstance(input_data, list):
            return {
                "transactions": input_data,
                "peers": [],
                "history": [],
                "context": {},
            }
        if not isinstance(input_data, dict):
            return {
                "transactions": [], "peers": [], "history": [], "context": {},
            }

        txs = input_data.get("transactions", input_data.get("交易", []))
        peers = input_data.get("peers", input_data.get("可比数据", []))
        history = input_data.get("history", input_data.get("历史价格", []))
        context = input_data.get("context", {})
        if not isinstance(txs, list):
            txs = [txs] if txs else []
        if not isinstance(peers, list):
            peers = [peers] if peers else []
        if not isinstance(history, list):
            history = [history] if history else []
        return {
            "transactions": txs,
            "peers": peers,
            "history": history,
            "context": context if isinstance(context, dict) else {},
        }

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外结构。"""
        return format_output(result)
