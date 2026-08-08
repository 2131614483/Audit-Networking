"""[CO-08] 执行管道 —— 采集 → 处理 → 输出三阶段。"""
from __future__ import annotations

from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


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
        if not isinstance(input_data, dict):
            return {}
        return {
            "systems": input_data.get("systems", input_data.get("系统", [])),
            "datasets": input_data.get("datasets", input_data.get("数据集", [])),
            "locations": input_data.get("locations", input_data.get("位置", [])),
            "processes": input_data.get("processes", input_data.get("流程", [])),
            "target": input_data.get("target", input_data.get("目标", {})),
        }

    def _output(self, result: Any) -> Any:
        return format_output(result)
