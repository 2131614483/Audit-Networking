"""[FA-12] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析账簿关联交易/披露文本/关联方清单) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(完整性风险分级) → apply_custom_rules(业务规则)
  → output(format_output)
"""
from __future__ import annotations

from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        # KGEngine 以 name 构造，config 透传至 self.engine.config 供 custom_* 读取
        self.engine = KGEngine(config if isinstance(config, dict) else "fa_12")
        if isinstance(config, dict):
            self.engine.config = config
        # 显式触发模型加载：编译关联方识别正则 _hints
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析账簿关联交易、披露文本、关联方清单。

        兼容多种输入形态：
          * dict 含 transactions/disclosure_text/related_parties → 原样补全默认值
          * dict 含中文键 交易/披露文本/关联方清单 → 归一化为英文键
          * 裸 list → 视为 transactions 列表（披露文本为空）
        """
        if isinstance(input_data, list):
            return {
                "transactions": input_data,
                "disclosure_text": "",
                "related_parties": [],
                "context": {},
            }
        if not isinstance(input_data, dict):
            return {
                "transactions": [], "disclosure_text": "",
                "related_parties": [], "context": {},
            }

        txs = input_data.get(
            "transactions", input_data.get("交易", [])
        )
        disclosure = input_data.get(
            "disclosure_text", input_data.get("披露文本", "")
        )
        parties = input_data.get(
            "related_parties", input_data.get("关联方清单", [])
        )
        context = input_data.get("context", {})
        if not isinstance(txs, list):
            txs = [txs] if txs else []
        if not isinstance(parties, list):
            parties = [parties] if parties else []
        return {
            "transactions": txs,
            "disclosure_text": str(disclosure) if disclosure else "",
            "related_parties": parties,
            "context": context if isinstance(context, dict) else {},
        }

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外披露完整性报告。"""
        return format_output(result)
