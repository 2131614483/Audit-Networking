"""统一输出格式化：区块链函证存证报告（区块详情 + 哈希链 + 验证状态 + 审计轨迹）。

输出结构：
  store 模式：
    {
      "status": "ok", "module": "FA-05", "mode": "store",
      "certificate": { tx_ids, chain_height, merkle_root, timestamp, chain_valid },
      "chain_summary": { blocks, transactions_total, latest_hash, latest_index },
      "blocks": [ {index, timestamp, merkle_root, prev_hash, hash, tx_count, tx_ids}, ... ],
      "audit_trail": [ ... ],
      "alerts": [ ... ], "integrity": { integrity_score, trust_level, verification_level }
    }
  verify 模式：
    {
      "status": "ok", "module": "FA-05", "mode": "verify",
      "verification": { tx_id, found_on_chain, block_index, signature_valid,
                        chain_valid, verified },
      "audit_trail": [ ... ],
      "alerts": [ ... ], "integrity": { ... }
    }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外区块链函证存证报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    grading = result.get("grading", {})
    integrity = {
        "integrity_score": grading.get("integrity_score", result.get("integrity_score")),
        "trust_level": grading.get("trust_level", result.get("trust_level")),
        "verification_level": grading.get(
            "verification_level", result.get("verification_level")
        ),
    }
    alerts = result.get("alerts", [])

    # verify 模式（结果含 verified 字段）
    if "verified" in result:
        audit_trail = _verify_audit_trail(result)
        return {
            "status": "ok",
            "module": "FA-05",
            "mode": "verify",
            "verification": {
                "tx_id": result.get("tx_id"),
                "found_on_chain": result.get("found_on_chain"),
                "block_index": result.get("block_index"),
                "merkle_root": result.get("merkle_root"),
                "signature_valid": result.get("signature_valid"),
                "chain_valid": result.get("chain_valid"),
                "verified": result.get("verified"),
            },
            "audit_trail": audit_trail,
            "alerts": alerts,
            "alert_count": len(alerts),
            "integrity": integrity,
            "tamper_alert": result.get("tamper_alert", False),
            "rejected": result.get("rejected", False),
        }

    # store / sign 模式（结果含 certificate）
    cert = result.get("certificate", {})
    chain_blocks = result.get("chain_blocks", [])
    blocks = [
        {
            "index": b.get("index"),
            "timestamp": b.get("timestamp"),
            "merkle_root": b.get("merkle_root"),
            "prev_hash": b.get("prev_hash"),
            "hash": b.get("hash"),
            "tx_count": b.get("tx_count", len(b.get("transactions", []))),
            "tx_ids": b.get("tx_ids", [t.get("tx_id") for t in b.get("transactions", [])]),
        }
        for b in chain_blocks
    ]
    # 哈希链：相邻区块 prev_hash ↔ hash
    hash_chain = []
    for i, b in enumerate(blocks):
        prev = blocks[i - 1]["hash"] if i > 0 else b.get("prev_hash")
        hash_chain.append({
            "block_index": b.get("index"),
            "prev_hash": b.get("prev_hash"),
            "hash": b.get("hash"),
            "linked": i == 0 or b.get("prev_hash") == prev,
        })

    audit_trail = _store_audit_trail(result, blocks)

    return {
        "status": "ok",
        "module": "FA-05",
        "mode": "store",
        "certificate": {
            "tx_ids": cert.get("tx_ids", []),
            "chain_height": cert.get("chain_height"),
            "merkle_root": cert.get("merkle_root"),
            "timestamp": cert.get("timestamp"),
            "chain_valid": cert.get("chain_valid", result.get("chain_valid")),
        },
        "chain_summary": {
            "blocks": result.get("blocks", len(blocks)),
            "transactions_total": result.get(
                "transactions_total", len(cert.get("tx_ids", []))
            ),
            "latest_hash": result.get("latest_hash"),
            "latest_index": result.get("latest_index"),
            "chain_valid": result.get("chain_valid", cert.get("chain_valid")),
        },
        "blocks": blocks,
        "hash_chain": hash_chain,
        "audit_trail": audit_trail,
        "alerts": alerts,
        "integrity": integrity,
        "tamper_alert": result.get("tamper_alert", False),
        "disclaimer": result.get("disclaimer", ""),
    }


def _store_audit_trail(result: dict, blocks: list) -> list:
    """构建存证审计轨迹（区块 → 交易 → 哈希）。"""
    trail = []
    for b in blocks:
        trail.append({
            "block_index": b.get("index"),
            "hash": b.get("hash"),
            "tx_ids": b.get("tx_ids", []),
            "timestamp": b.get("timestamp"),
        })
    return trail


def _verify_audit_trail(result: dict) -> list:
    """构建验证审计轨迹。"""
    return [
        {
            "tx_id": result.get("tx_id"),
            "found_on_chain": result.get("found_on_chain"),
            "block_index": result.get("block_index"),
            "signature_valid": result.get("signature_valid"),
            "chain_valid": result.get("chain_valid"),
        }
    ]
