"""[FO-05] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入多语言文本 + 持久化原始文本) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(质量分级) → apply_custom_rules(业务规则)
  → output(持久化分析结果 + format_output)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import LLMEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output

_TEXT_SCHEMA = {
    "text_id": "TEXT",
    "content": "TEXT",
    "source_lang": "TEXT",
    "target_lang": "TEXT",
    "collected_at": "DATETIME",
}

_RESULT_SCHEMA = {
    "text_id": "TEXT",
    "detected_language": "TEXT",
    "translated_text": "TEXT",
    "quality_level": "TEXT",
    "translation_confidence": "REAL",
    "needs_review": "INTEGER",
    "created_at": "DATETIME",
}


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = LLMEngine(config)
        self.engine.setup()
        self._init_tables()

    def _init_tables(self) -> None:
        """初始化 PortableDB 表。"""
        db = self.engine.db
        if db is None:
            return
        if "source_texts" not in db.tables():
            db.create_table("source_texts", _TEXT_SCHEMA)
        if "analysis_results" not in db.tables():
            db.create_table("analysis_results", _RESULT_SCHEMA)

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；同时把原始文本写入 PortableDB（审计追溯）。"""
        if not isinstance(input_data, dict):
            return input_data
        db = self.engine.db
        if db is None:
            return input_data
        db.delete("source_texts", "1=1")
        db.delete("analysis_results", "1=1")
        texts = input_data.get("texts", []) or []
        for t in texts:
            if not isinstance(t, dict):
                continue
            db.insert("source_texts", {
                "text_id": str(t.get("text_id", "")),
                "content": str(t.get("content", "")),
                "source_lang": str(t.get("source_lang", "")),
                "target_lang": str(t.get("target_lang", "zh")),
                "collected_at": datetime.now(),
            })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB + 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把分析结果写回 PortableDB。"""
        db = self.engine.db
        if db is None or "analysis_results" not in db.tables():
            return
        db.delete("analysis_results", "1=1")
        for t in result.get("translations", []):
            db.insert("analysis_results", {
                "text_id": t.get("text_id", ""),
                "detected_language": t.get("detected_language", ""),
                "translated_text": t.get("translated_text", ""),
                "quality_level": t.get("quality_level", ""),
                "translation_confidence": float(
                    t.get("translation_confidence", 0.0)
                ),
                "needs_review": 1 if t.get("needs_review") else 0,
                "created_at": datetime.now(),
            })

    def close(self) -> None:
        """关闭引擎释放 db 连接。"""
        self.engine.close()
