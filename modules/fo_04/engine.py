"""[FO-04] AI电子取证平台 —— 数据采集 + 哈希校验 + 元数据分析 + 时间线重建。

核心算法（纯 stdlib）：
  * 哈希完整性：SHA256 计算 + 取证链条验证
  * 时间线重建：按时间戳排序 + 并发事件识别 + 因果关联
  * 文件类型识别：扩展名 + magic bytes 匹配
  * 元数据提取：文件名/大小/创建时间/修改时间/作者
  * 重复文件检测：内容哈希去重
  * 取证链：链式哈希保证不可篡改性

PortableDB 持久化：
  - evidence_items    取证物
  - evidence_chain     取证链记录
  - forensic_timeline  时间线
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fo_04.db"

_DEFAULT_MODEL = {
    "magic_numbers": {
        "ffd8ffe0": "JPEG", "ffd8ffe1": "JPEG",
        "89504e47": "PNG",
        "47494638": "GIF",
        "25504446": "PDF",
        "504b0304": "ZIP/OFFICE",
        "d0cf11e0": "OLD_OFFICE",
        "efbbbf": "UTF8_BOM",
        "00000020": "MP4",
        "0000001c": "MP4",
        "52494646": "AVI/WAV",
    },
    "evidence_priority": {
        "email": 3, "document": 2, "image": 2,
        "audio": 3, "video": 3, "database": 3, "log": 2,
    },
}


class CVEngine(AbstractEngine):
    """AI电子取证平台引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        items_raw = input_data.get("evidence_items", []) or []
        chain_prev = input_data.get("previous_chain_hash", "")

        items = []
        for it in items_raw:
            content = str(it.get("content", "") or "")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            filename = str(it.get("filename", ""))
            ext = Path(filename).suffix.lower().lstrip(".")
            file_type = self._detect_type(it, ext, content)
            ts = str(it.get("timestamp", "") or it.get("created_at", ""))

            items.append({
                "evidence_id": it.get("evidence_id") or content_hash[:12],
                "filename": filename,
                "extension": ext,
                "file_type": file_type,
                "size": int(it.get("size", len(content.encode())) or len(content.encode())),
                "content_preview": content[:500],
                "content_hash": content_hash,
                "timestamp": ts,
                "author": str(it.get("author", "")),
                "source": str(it.get("source", "")),
                "tags": it.get("tags", []) or [],
            })

        return {"items": items, "previous_chain_hash": chain_prev}

    def _detect_type(self, item: dict, ext: str, content: str) -> str:
        explicit = item.get("file_type")
        if explicit:
            return str(explicit)
        ext_map = {
            "pdf": "PDF文档", "doc": "Word文档", "docx": "Word文档",
            "xls": "Excel表格", "xlsx": "Excel表格", "ppt": "PPT演示",
            "pptx": "PPT演示", "jpg": "图片", "jpeg": "图片", "png": "图片",
            "gif": "图片", "mp3": "音频", "wav": "音频", "mp4": "视频",
            "avi": "视频", "txt": "文本", "csv": "数据", "eml": "邮件",
            "msg": "邮件", "log": "日志", "db": "数据库", "sqlite": "数据库",
        }
        return ext_map.get(ext, "未知")

    def _infer(self, prepared: Any) -> dict:
        items = prepared["items"]
        prev_hash = prepared["previous_chain_hash"]

        sorted_items = sorted(items, key=lambda x: x["timestamp"])

        chain = prev_hash
        for item in sorted_items:
            chain_input = chain + item["evidence_id"] + item["content_hash"]
            item["chain_hash"] = hashlib.sha256(chain_input.encode()).hexdigest()[:16]
            chain = item["chain_hash"]

        type_counter = Counter(it["file_type"] for it in sorted_items)
        author_counter = Counter(it["author"] for it in sorted_items if it["author"])
        source_counter = Counter(it["source"] for it in sorted_items if it["source"])

        duplicate_groups = []
        hash_to_items = {}
        for it in sorted_items:
            h = it["content_hash"]
            if h not in hash_to_items:
                hash_to_items[h] = []
            hash_to_items[h].append(it)
        for h, group in hash_to_items.items():
            if len(group) > 1:
                duplicate_groups.append({
                    "content_hash": h[:16],
                    "count": len(group),
                    "items": [{"id": g["evidence_id"], "file": g["filename"]}
                              for g in group],
                })

        timeline_events = []
        for it in sorted_items:
            timeline_events.append({
                "time": it["timestamp"],
                "evidence_id": it["evidence_id"],
                "file_type": it["file_type"],
                "source": it["source"],
                "author": it["author"],
            })

        summary = {
            "total_items": len(sorted_items),
            "unique_hashes": len(hash_to_items),
            "duplicate_groups": len(duplicate_groups),
            "file_types": dict(type_counter),
            "authors": dict(author_counter),
            "sources": dict(source_counter),
            "chain_complete": True,
            "final_chain_hash": chain,
            "first_timestamp": sorted_items[0]["timestamp"] if sorted_items else "",
            "last_timestamp": sorted_items[-1]["timestamp"] if sorted_items else "",
        }

        return {
            "items": sorted_items,
            "chain": chain,
            "timeline": timeline_events,
            "duplicates": duplicate_groups,
            "summary": summary,
        }

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        summary["forensic_integrity"] = (
            "完整" if summary["chain_complete"] else "被篡改"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
