"""统一输出格式化：取证物目录 + 哈希链 + 时间线 + 完整性状态。

输出结构：
  {
    "status": "ok",
    "module": "FO-04",
    "evidence_catalog": [ {evidence_id, filename, file_type, content_hash,
                           chain_hash, timestamp, author, source, ...}, ... ],
    "hash_chain": [ {evidence_id, content_hash, chain_hash}, ... ],
    "custody_trail": [ {time, evidence_id, file_type, source, author}, ... ],
    "duplicates": [ {content_hash, count, items}, ... ],
    "alerts": [ {type, evidence_id, message, ...}, ... ],
    "integrity_status": { forensic_integrity, integrity_score, integrity_level,
                          chain_complete, final_chain_hash, ... },
    "statistics": { total_items, unique_hashes, duplicate_groups, file_types,
                    authors, sources, alert_count, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    items = result.get("items", [])
    summary = result.get("summary", {})
    timeline = result.get("timeline", [])
    duplicates = result.get("duplicates", [])
    alerts = result.get("alerts", [])

    # 物证目录
    catalog = []
    for item in items:
        catalog.append({
            "evidence_id": item.get("evidence_id"),
            "filename": item.get("filename"),
            "file_type": item.get("file_type"),
            "size": item.get("size"),
            "content_hash": item.get("content_hash"),
            "chain_hash": item.get("chain_hash"),
            "timestamp": item.get("timestamp"),
            "author": item.get("author"),
            "source": item.get("source"),
            "tags": item.get("tags", []),
            "integrity_level": item.get("integrity_level", ""),
            "tamper_alert": item.get("tamper_alert", False),
            "metadata_incomplete": item.get("metadata_incomplete", False),
            "missing_fields": item.get("missing_fields", []),
        })

    # 哈希链
    hash_chain = [
        {
            "evidence_id": item.get("evidence_id"),
            "content_hash": item.get("content_hash"),
            "chain_hash": item.get("chain_hash"),
        }
        for item in items
    ]

    # 完整性状态
    integrity_status = {
        "forensic_integrity": summary.get("forensic_integrity", ""),
        "integrity_score": summary.get("integrity_score", 0.0),
        "integrity_level": summary.get("integrity_level", ""),
        "integrity_deductions": summary.get("integrity_deductions", []),
        "chain_complete": summary.get("chain_complete", True),
        "final_chain_hash": summary.get("final_chain_hash", ""),
    }

    # 统计
    output_stats = {
        "total_items": summary.get("total_items", 0),
        "unique_hashes": summary.get("unique_hashes", 0),
        "duplicate_groups": summary.get("duplicate_groups", 0),
        "file_types": summary.get("file_types", {}),
        "authors": summary.get("authors", {}),
        "sources": summary.get("sources", {}),
        "alert_count": summary.get("alert_count", 0),
        "tamper_alerts": summary.get("tamper_alerts", 0),
        "incomplete_evidence": summary.get("incomplete_evidence", 0),
        "custody_gaps": summary.get("custody_gaps", 0),
        "first_timestamp": summary.get("first_timestamp", ""),
        "last_timestamp": summary.get("last_timestamp", ""),
    }

    return {
        "status": "ok",
        "module": "FO-04",
        "evidence_catalog": catalog,
        "hash_chain": hash_chain,
        "custody_trail": timeline,
        "duplicates": duplicates,
        "alerts": alerts,
        "integrity_status": integrity_status,
        "statistics": output_stats,
    }
