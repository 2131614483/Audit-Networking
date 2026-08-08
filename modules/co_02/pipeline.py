"""[CO-02] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(法规文本 + 企业画像标准化) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(影响分级) → apply_custom_rules(业务规则)
  → output(format_output 影响评估报告)
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
        # 显式触发模型加载（词典 / 处罚模式 / 对标案例）
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：标准化法规文本与企业画像输入。

        兼容裸字符串（视为法规全文）与 dict 输入；补齐 enterprise 默认字段，
        保证下游 engine._preprocess 拿到结构稳定的输入。
        """
        if isinstance(input_data, str):
            input_data = {"regulation_text": input_data}
        if not isinstance(input_data, dict):
            return input_data

        data = dict(input_data)
        data.setdefault("action", "assess")
        data.setdefault("regulation_title", "")
        data.setdefault("regulation_text", "")

        # 企业画像规范化
        enterprise = data.get("enterprise")
        if not isinstance(enterprise, dict):
            enterprise = {"existing_policies": [str(enterprise)] if enterprise else []}
        enterprise = dict(enterprise)
        enterprise.setdefault("industry", "all")
        enterprise.setdefault("size", "medium")
        enterprise.setdefault("country", "")
        enterprise.setdefault("existing_policies", [])
        enterprise.setdefault("systems", [])
        # existing_policies 统一为字符串列表
        eps = enterprise["existing_policies"]
        if not isinstance(eps, list):
            eps = [str(eps)]
        enterprise["existing_policies"] = [str(p) for p in eps]
        data["enterprise"] = enterprise
        return data

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外影响评估报告。"""
        return format_output(result)
