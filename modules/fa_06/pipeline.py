"""[FA-06] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析函证回函与账面数据并逐项对齐) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(重要性分级) → apply_custom_rules(业务规则)
  → output(format_output 差异分析报告)
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
        # KGEngine 把传入值作为 name 并经 super().__init__ 写入 self.config
        self.engine = KGEngine(config)
        # 显式触发模型加载：加载差异容忍率规则库 + 编译差异模式正则
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析函证回函与账面（ledger）数据，逐项对齐为差异分析记录。

        支持的输入形态：
          * 裸 list：每元素为一条已含 book/reply 字段的记录
          * dict["items"] 或 dict["confirmations"]：函证回函记录列表
          * dict["ledger"]：{item_id: {book_amount, book_text, ...}} 账面数据，
            与 confirmations 按 item_id 合并
          * dict["materiality"]：全局重要性水平（记录未单独指定时回填）
        返回：list[dict]，每条含 item_id/subject/book_amount/reply_amount/
              book_text/reply_text/direction/materiality。
        """
        records: list = []
        global_materiality = 0.0
        ledger: dict = {}

        if isinstance(input_data, list):
            records = input_data
        elif isinstance(input_data, dict):
            global_materiality = float(input_data.get("materiality", 0) or 0)
            ledger = input_data.get("ledger", {}) or {}
            if isinstance(input_data.get("items"), list):
                records = input_data["items"]
            elif isinstance(input_data.get("confirmations"), list):
                records = input_data["confirmations"]
            else:
                records = []
        else:
            records = []

        # 合并账面数据 + 回填全局重要性水平
        merged: list[dict] = []
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                continue
            item = dict(rec)
            item_id = str(item.get("item_id") or item.get("id") or f"CF{i + 1:04d}")
            item["item_id"] = item_id
            # 合并 ledger（账面）数据
            if isinstance(ledger, dict) and item_id in ledger and isinstance(
                ledger[item_id], dict
            ):
                for k, v in ledger[item_id].items():
                    if k not in item or item.get(k) in (None, "", 0, 0.0):
                        item[k] = v
            # 回填全局重要性水平
            if not float(item.get("materiality", 0) or 0):
                item["materiality"] = global_materiality
            merged.append(item)
        return merged

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外差异分析报告。"""
        return format_output(result)
