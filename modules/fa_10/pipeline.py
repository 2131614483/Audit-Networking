"""[FA-10] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(分级) → apply_custom_rules(业务规则)
  → output(持久化 PortableDB + format_output)
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
        self.engine = MLEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 类型定义
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；若输入为空可从 fixtures 加载种子数据。"""
        if input_data is None:
            return {}
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：engine 已持久化到 PortableDB，此处格式化对外结构。"""
        return format_output(result)
