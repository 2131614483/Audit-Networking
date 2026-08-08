"""[FA-09] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入数据归一化) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(等级划分/通过判定) → apply_custom_rules(业务规则)
  → output(format_output)
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
        # 显式触发模型加载：编译 AUDIT_STANDARDS 正则
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：归一化输入结构（兼容中英文键、裸 list、None）。"""
        if input_data is None:
            return {}
        if isinstance(input_data, list):
            return {"workpapers": input_data}
        if not isinstance(input_data, dict):
            return {"workpapers": input_data}
        # 兼容中英文键
        out = {
            "workpapers": input_data.get("workpapers", input_data.get("底稿", [])),
            "context": input_data.get("context", input_data.get("上下文", {})),
        }
        # 透传额外字段
        for k, v in input_data.items():
            if k not in ("workpapers", "底稿", "context", "上下文"):
                out.setdefault(k, v)
        return out

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外输出结构。"""
        return format_output(result)
