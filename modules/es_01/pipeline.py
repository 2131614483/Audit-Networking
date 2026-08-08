"""[ES-01] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析多源 ESG 原始数据 → 规整为数据源列表)
  → engine.execute(预处理→多模态解析→指标融合→质量评分→后处理)
  → apply_thresholds(置信度分级) → apply_custom_rules(业务规则告警)
  → output(format_output 输出 ESG 采集报告)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import CVEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = CVEngine(config)
        # 显式触发模型加载：注册多模态解析器 + 加载 GRI 指标标准库
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：从输入中抽取多源 ESG 原始数据，规整为数据源列表。

        支持的输入形态：
          * {"data_sources": [...]} / {"sources": [...]}  → 取列表
          * [item, item, ...]                              → 直接作为列表
          * 单个数据源 dict                                → 包成单元素列表
        每个 item 至少补全 timestamp / period / entity 缺省值，便于审计追溯。
        """
        if isinstance(input_data, dict):
            if "data_sources" in input_data and isinstance(input_data["data_sources"], list):
                items = input_data["data_sources"]
            elif "sources" in input_data and isinstance(input_data["sources"], list):
                items = input_data["sources"]
            else:
                items = [input_data]
        elif isinstance(input_data, list):
            items = input_data
        else:
            items = []

        now = datetime.now().isoformat()
        normalized = []
        for it in items:
            if not isinstance(it, dict):
                continue
            it.setdefault("data_type", "structured")
            it.setdefault("source", "未知")
            it.setdefault("timestamp", now)
            it.setdefault("period", "年度")
            it.setdefault("entity", "")
            it.setdefault("unit", "")
            normalized.append(it)
        return normalized

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外 ESG 采集报告。"""
        return format_output(result)
