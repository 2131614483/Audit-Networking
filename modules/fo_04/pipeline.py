"""[FO-04] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入取证数据 + 持久化原始物) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(完整性分级) → apply_custom_rules(业务规则)
  → output(持久化取证结果 + format_output)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import CVEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output

_EVIDENCE_SCHEMA = {
    "evidence_id": "TEXT",
    "filename": "TEXT",
    "file_type": "TEXT",
    "size": "INTEGER",
    "content_hash": "TEXT",
    "chain_hash": "TEXT",
    "timestamp": "TEXT",
    "author": "TEXT",
    "source": "TEXT",
    "tags": "JSON",
    "integrity_level": "TEXT",
    "collected_at": "DATETIME",
}

_TIMELINE_SCHEMA = {
    "evidence_id": "TEXT",
    "timestamp": "TEXT",
    "file_type": "TEXT",
    "source": "TEXT",
    "author": "TEXT",
    "event_order": "INTEGER",
}


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = CVEngine(config)
        self.engine.setup()
        self._init_tables()

    def _init_tables(self) -> None:
        """初始化 PortableDB 表（建表，供 _collect / _persist 使用）。"""
        db = self.engine.db
        if db is None:
            return
        if "evidence_items" not in db.tables():
            db.create_table("evidence_items", _EVIDENCE_SCHEMA)
        if "forensic_timeline" not in db.tables():
            db.create_table("forensic_timeline", _TIMELINE_SCHEMA)

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        # 保留引擎未处理但规则需要的输入字段（如 expected_hash）
        self._merge_input_metadata(result, input_data)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _merge_input_metadata(self, result: Any, input_data: Any) -> None:
        """把输入中引擎未输出的字段合并到结果（供 custom_rules 使用）。"""
        if not isinstance(input_data, dict):
            return
        input_items = input_data.get("evidence_items", []) or []
        result_items = result.get("items", [])
        input_map = {
            it.get("evidence_id"): it
            for it in input_items if isinstance(it, dict)
        }
        for item in result_items:
            eid = item.get("evidence_id")
            src = input_map.get(eid)
            if src:
                for k, v in src.items():
                    if k not in item:
                        item[k] = v

    def close(self) -> None:
        """关闭引擎释放 db 连接。"""
        self.engine.close()

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；同时把原始取证物写入 PortableDB（审计追溯）。"""
        if not isinstance(input_data, dict):
            return input_data
        db = self.engine.db
        if db is None:
            return input_data
        # 清空旧数据（每次 run 重新写入，保证与输入一致）
        db.delete("evidence_items", "1=1")
        db.delete("forensic_timeline", "1=1")
        items = input_data.get("evidence_items", []) or []
        for it in items:
            if not isinstance(it, dict):
                continue
            db.insert("evidence_items", {
                "evidence_id": str(it.get("evidence_id", "")),
                "filename": str(it.get("filename", "")),
                "file_type": str(it.get("file_type", "")),
                "size": int(it.get("size", 0) or 0),
                "content_hash": "",
                "chain_hash": "",
                "timestamp": str(
                    it.get("timestamp", "") or it.get("created_at", "")
                ),
                "author": str(it.get("author", "")),
                "source": str(it.get("source", "")),
                "tags": it.get("tags", []) or [],
                "integrity_level": "",
                "collected_at": datetime.now(),
            })
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把取证结果写回 PortableDB（哈希链 + 时间线）。"""
        db = self.engine.db
        if db is None or "evidence_items" not in db.tables():
            return
        # 更新取证物的哈希与链信息
        for item in result.get("items", []):
            eid = item.get("evidence_id")
            if not eid:
                continue
            db.update(
                "evidence_items",
                {
                    "content_hash": item.get("content_hash", ""),
                    "chain_hash": item.get("chain_hash", ""),
                    "integrity_level": result.get("summary", {}).get(
                        "integrity_level", ""
                    ),
                },
                where="evidence_id = ?",
                params=[eid],
            )
        # 写入时间线
        if "forensic_timeline" in db.tables():
            db.delete("forensic_timeline", "1=1")
            for i, ev in enumerate(result.get("timeline", [])):
                db.insert("forensic_timeline", {
                    "evidence_id": ev.get("evidence_id", ""),
                    "timestamp": ev.get("time", ""),
                    "file_type": ev.get("file_type", ""),
                    "source": ev.get("source", ""),
                    "author": ev.get("author", ""),
                    "event_order": i,
                })
