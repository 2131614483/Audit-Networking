"""[IA-01] 执行管道 —— 采集 → 处理 → 输出三阶段骨架。

可在此编排 engine 与 custom_* 的调用顺序。默认串联 engine.execute。
"""
from __future__ import annotations

from typing import Any

from .engine import LLMEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = LLMEngine(config)

    def run(self, input_data: Any) -> Any:
        # TODO[pipeline]: 按需调整阶段顺序
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        # TODO[pipeline]: 数据采集 / 接入共享平台 ADL
        return input_data

    def _output(self, result: Any) -> Any:
        # TODO[pipeline]: 结果输出 / 回写 ADL
        return format_output(result)
