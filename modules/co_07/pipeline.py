"""[CO-07] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析数据源扫描结果 + 清空旧持久化) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(四级分级) → apply_custom_rules(业务规则)
  → output(格式化对外结构)
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
        # 显式触发模型加载：初始化 PortableDB + 敏感模式规则
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：归一化输入为 {assets: [...]}，清空旧持久化（审计追溯一致）。"""
        db = self.engine.db
        if db is not None:
            for t in ("assets", "fields"):
                if t in db.tables():
                    db.delete(t, "1=1")
        # 归一化：裸列表 / 别名键 → {assets: [...]}
        if isinstance(input_data, list):
            return {"assets": input_data}
        if isinstance(input_data, dict) and "assets" not in input_data:
            for key in ("data_sources", "sources", "scan_results", "datasets"):
                if key in input_data:
                    return {"assets": input_data[key]}
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外结构。"""
        return format_output(result)
