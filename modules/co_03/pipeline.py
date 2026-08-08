"""[CO-03] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(法规变更 + 受影响程序筛选标准化) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(更新优先级分级) → apply_custom_rules(业务规则)
  → output(format_output 更新报告)
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
        # 显式触发模型加载（程序模板库 / 领域映射 / 更新历史）
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：标准化法规变更输入与受影响程序筛选条件。

        兼容裸字符串（视为法规变更内容）与 dict 输入；规范化 affected_prog_ids
        与 change_type，保证下游 engine._preprocess 拿到结构稳定的输入。
        """
        if isinstance(input_data, str):
            input_data = {"regulation_change": input_data}
        if not isinstance(input_data, dict):
            return input_data

        data = dict(input_data)
        data.setdefault("action", "analyze_change")
        data.setdefault("regulation_change", "")
        data.setdefault("regulation_title", "")

        # affected_prog_ids 规范化为列表
        ids = data.get("affected_prog_ids") or []
        if not isinstance(ids, list):
            ids = [str(ids)]
        data["affected_prog_ids"] = [str(i) for i in ids]

        # change_type 校验
        valid_types = {"major", "minor", "patch"}
        ct = data.get("change_type", "minor")
        data["change_type"] = ct if ct in valid_types else "minor"

        data.setdefault("prog_id", "")
        data.setdefault("target_version", "")
        return data

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外更新报告。"""
        return format_output(result)
