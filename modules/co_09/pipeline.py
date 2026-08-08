"""[CO-09] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(归一化隐私政策/数据处理记录/同意记录 → policies) → engine.execute
  → apply_thresholds(合规分级) → apply_custom_rules(违规标记)
  → output(format_output 隐私合规报告)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import LLMEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output

# 输入中可映射为 policies 的字段别名
_POLICY_ALIASES = (
    "privacy_policies",
    "data_processing_records",
    "consent_records",
    "policies",
)


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = LLMEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 建表
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：把隐私政策/数据处理记录/同意记录归一化为 {policies: [...]}。

        兼容输入形态：
          - {"policies": [...]}               直接透传
          - [policy, ...]                     裸列表包装为 policies
          - {"privacy_policies": [...]}       别名映射
          - {"data_processing_records": [...]} 数据处理记录映射为 policy
          - {"consent_records": [...]}        同意记录映射为 policy
          - 单条 policy dict（含 text/content）包装为列表
        """
        if isinstance(input_data, list):
            return {"policies": input_data}

        if isinstance(input_data, dict):
            if "policies" in input_data:
                return input_data

            merged: list[dict] = []
            for key in _POLICY_ALIASES:
                items = input_data.get(key)
                if not items:
                    continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if key in ("data_processing_records", "consent_records"):
                        # 数据处理记录/同意记录：text/content → policy text
                        text = (it.get("description") or it.get("content")
                                or it.get("text") or "")
                        merged.append({
                            "policy_id": it.get("record_id")
                                         or it.get("policy_id")
                                         or it.get("id", ""),
                            "name": it.get("name") or it.get("purpose", ""),
                            "publisher": it.get("data_controller")
                                         or it.get("processor", ""),
                            "language": it.get("language", "zh"),
                            "text": text,
                        })
                    else:
                        merged.append(it)
            if merged:
                return {"policies": merged}

            # 单条政策
            if "text" in input_data or "content" in input_data:
                return {"policies": [input_data]}

        raise ValueError(
            "输入需为 policies 列表，或含 policies/privacy_policies/"
            "data_processing_records/consent_records 字段的 dict"
        )

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外隐私合规报告（engine 已持久化 policies/findings 明细）。"""
        summary = result.get("summary", {})
        summary["generated_at"] = datetime.now().isoformat()
        return format_output(result)
