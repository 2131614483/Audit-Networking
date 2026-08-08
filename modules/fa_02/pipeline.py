"""[FA-02] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(分级) → apply_custom_rules(业务规则)
  → output(持久化 PortableDB + format_output)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import MLEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = MLEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 合并 fixtures + 增量学习记录
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；增量学习记录已在 engine._load_model 中合并。"""
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把标准化结果写回 PortableDB standardization_results 表。"""
        db = self.engine.db
        if db is None:
            return
        for f in result.get("fields", []):
            db.insert("standardization_results", {
                "source": f.get("source"),
                "raw_name": f.get("raw_name"),
                "standard_name": f.get("standard_name") or f.get("best_match"),
                "confidence": float(f.get("confidence", 0.0)),
                "subject_code": f.get("subject_code"),
                "tier": f.get("tier"),
                "created_at": datetime.now(),
                "payload": {
                    "top3_candidates": f.get("top3_candidates", []),
                    "cleaned": f.get("cleaned"),
                    "review_reason": f.get("review_reason"),
                },
            })
