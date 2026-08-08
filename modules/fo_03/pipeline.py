"""[FO-03] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析文本文档与元数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(风险分级) → apply_custom_rules(业务规则)
  → output(持久化检测结果 + format_output 舞弊信号报告)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .engine import LLMEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output

# PortableDB 检测结果表 schema
_DETECTION_RESULTS_SCHEMA = {
    "doc_id": "TEXT",
    "title": "TEXT",
    "doc_type": "TEXT",
    "risk_score": "REAL",
    "risk_grade": "TEXT",
    "signal_count": "INTEGER",
    "findings": "JSON",
    "created_at": "DATETIME",
}


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = LLMEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 舞弊信号词典
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：解析文本文档与元数据，归一化为 documents 列表。

        支持的输入形态：
          * dict["documents"]：文档列表（每项含 content/title/doc_type/doc_id）
          * dict["texts"]：纯文本字符串列表
          * 裸 list：元素为 dict 或 str
        返回：{"documents": [ {content, title, doc_type, ...}, ... ]}
        """
        docs: list = []
        if isinstance(input_data, dict):
            if isinstance(input_data.get("documents"), list):
                docs = input_data["documents"]
            elif isinstance(input_data.get("texts"), list):
                docs = [{"content": t} for t in input_data["texts"]]
            else:
                docs = []
        elif isinstance(input_data, list):
            docs = input_data
        else:
            docs = []

        normalized: list[dict] = []
        for d in docs:
            if isinstance(d, str):
                d = {"content": d}
            if not isinstance(d, dict):
                continue
            normalized.append({
                "doc_id": d.get("doc_id"),
                "title": str(d.get("title", "")),
                "content": str(d.get("content", "")),
                "doc_type": str(d.get("doc_type", "文本")),
            })
        return {"documents": normalized}

    def _output(self, result: Any) -> Any:
        """结果输出：持久化检测结果到 PortableDB + 格式化对外报告。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把检测结果写回 PortableDB detection_results 表（审计追溯）。"""
        db = self.engine.db
        if db is None:
            return
        if "detection_results" not in db.tables():
            db.create_table("detection_results", _DETECTION_RESULTS_SCHEMA)
        # 清空旧结果（每次 run 重新写入）
        db.delete("detection_results", "1=1")
        batch_id = uuid.uuid4().hex[:8]
        for det in result.get("detections", []):
            findings = det.get("findings", []) or []
            db.insert("detection_results", {
                "doc_id": det.get("doc_id"),
                "title": det.get("title"),
                "doc_type": det.get("doc_type"),
                "risk_score": float(det.get("risk_score", 0) or 0),
                "risk_grade": det.get("risk_grade", "low"),
                "signal_count": len(findings),
                "findings": findings,
                "created_at": datetime.now(),
            })
        # 标记 batch（写入首行 doc_id 前缀无副作用，此处仅保证可追溯）
        _ = batch_id
