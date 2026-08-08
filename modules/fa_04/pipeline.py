"""[FA-04] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析函证请求/回函) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(状态分级) → apply_custom_rules(催函/差异规则)
  → output(format_output 函证管理报告)
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
        # 显式触发模型加载：状态机 / 模板库 / 催函规则
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：把输入归一化为 {confirmations: [...]} 结构。

        支持：
          * {"confirmations": [...]} —— 直接透传
          * [ {...}, {...} ]        —— 列表包装为 confirmations
          * {"confirmation_id": ..} —— 单张函证包装为列表
        """
        if isinstance(input_data, dict):
            if "confirmations" in input_data:
                confs = input_data["confirmations"]
                if not isinstance(confs, list):
                    confs = [confs] if isinstance(confs, dict) else []
                return {**input_data, "confirmations": [
                    c for c in confs if isinstance(c, dict)
                ]}
            if "confirmation_id" in input_data:
                return {"confirmations": [input_data]}
            return {"confirmations": []}
        if isinstance(input_data, list):
            return {"confirmations": [c for c in input_data if isinstance(c, dict)]}
        raise ValueError("input_data 必须为 dict 或 list，含 confirmations")

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外函证管理报告。"""
        return format_output(result)
