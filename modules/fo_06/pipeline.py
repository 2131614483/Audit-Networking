"""[FO-06] 执行管道 —— 采集 → 处理 → 输出三阶段。"""
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
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        if not isinstance(input_data, dict):
            return {}
        return {
            "evidence": input_data.get("evidence", input_data.get("证据", [])),
            "cases": input_data.get("cases", input_data.get("案件", [])),
        }

    def _output(self, result: Any) -> Any:
        return format_output(result)
