"""[FA-05] 区块链银行函证 —— SHA-256 存证 + Merkle 树 + 模拟区块链账本 + 签名验证。

算法设计（纯 stdlib：hashlib / json / datetime）：

  * _load_model: 初始化模拟区块链账本（内存 dict + 磁盘持久化可选）
  * _preprocess: 对发函数据做 SHA-256 哈希 + 构建 Merkle 树根
  * _infer:
      ① 多交易打包 → 共识排序 → 区块写入
      ② 银行模拟签名（用确定性 hash 模拟）
      ③ 验证：区块哈希链 + 签名有效性 + 时间戳窗口
  * _postprocess: 返回存证证书（含区块高度/交易ID/根哈希/签名）+ 验证结果
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _merkle_root(hashes: list[str]) -> str:
    if not hashes:
        return _sha256("")
    level = list(hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            nxt.append(_sha256(level[i] + level[i + 1]))
        level = nxt
    return level[0]


class BlockchainEngine(AbstractEngine):
    """区块链银行函证引擎（纯 stdlib：SHA-256 + Merkle 树 + 链式区块存证）。"""

    def _load_model(self) -> None:
        self.model = {
            "chain": [],
            "pending_tx": [],
            "genesis_note": "IPO审计区块链函证存证网络 v1.0 创世区块",
            "bank_public_keys": {},
            "blocks_per_batch": 1,
        }
        self._append_genesis()

    def _append_genesis(self) -> None:
        chain = self.model["chain"]
        if not chain:
            chain.append({
                "index": 0,
                "timestamp": datetime.utcnow().isoformat(),
                "transactions": [],
                "merkle_root": _merkle_root([]),
                "prev_hash": "0" * 64,
                "hash": _sha256("GENESIS"),
                "note": self.model["genesis_note"],
            })

    def _preprocess(self, input_data: Any) -> Any:
        """对发函交易做标准化 + 哈希预处理。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")
        txs = input_data.get("transactions") or ([input_data] if "confirmation_id" in input_data else [])
        norm: list[dict] = []
        for i, tx in enumerate(txs):
            if not isinstance(tx, dict):
                continue
            payload = json.dumps(tx, sort_keys=True, default=str, ensure_ascii=False)
            tx_hash = _sha256(payload)
            norm.append({
                "tx_id": tx.get("tx_id", f"TX-{datetime.utcnow().timestamp():.0f}-{i}"),
                "type": tx.get("type", "confirmation"),
                "payload": tx,
                "payload_hash": tx_hash,
                "timestamp": datetime.utcnow().isoformat(),
                "bank_id": tx.get("bank_id", "UNKNOWN"),
                "action": tx.get("action", "initiate"),
            })
        return {"transactions": norm, "mode": input_data.get("mode", "store")}

    def _infer(self, prepared: Any) -> Any:
        mode = prepared["mode"]
        if mode == "verify":
            return self._verify(prepared)
        if mode == "sign":
            return self._sign_response(prepared)
        return self._store(prepared)

    def _store(self, prepared: Any) -> Any:
        chain = self.model["chain"]
        txs = prepared["transactions"]
        for tx in txs:
            self.model["pending_tx"].append(tx)
        while len(self.model["pending_tx"]) >= self.model["blocks_per_batch"] or (
            len(self.model["pending_tx"]) > 0 and len(txs) == 0
        ):
            batch: list[dict] = []
            for _ in range(min(self.model["blocks_per_batch"], len(self.model["pending_tx"]))):
                batch.append(self.model["pending_tx"].pop(0))
            self._mine_block(batch)
        return self._chain_summary()

    def _mine_block(self, txs: list[dict]) -> dict:
        chain = self.model["chain"]
        prev = chain[-1]
        merkle = _merkle_root([tx["payload_hash"] for tx in txs])
        index = prev["index"] + 1
        ts = datetime.utcnow().isoformat()
        raw = json.dumps({
            "index": index, "timestamp": ts, "transactions": txs,
            "merkle_root": merkle, "prev_hash": prev["hash"],
        }, sort_keys=True, ensure_ascii=False, default=str)
        block_hash = _sha256(raw)
        block = {
            "index": index, "timestamp": ts, "transactions": txs,
            "merkle_root": merkle, "prev_hash": prev["hash"], "hash": block_hash,
        }
        chain.append(block)
        for tx in txs:
            tx["block_index"] = index
            tx["block_hash"] = block_hash
        return block

    def _sign_response(self, prepared: Any) -> Any:
        txs = prepared["transactions"]
        signed: list[dict] = []
        for tx in txs:
            sign_payload = tx["payload_hash"] + tx["bank_id"] + tx["timestamp"]
            signature = _sha256(sign_payload + tx.get("bank_private_key", "SECRET"))
            bank_key = f"PUB-{tx['bank_id']}"
            self.model["bank_public_keys"][bank_key] = _sha256(tx.get("bank_private_key", "SECRET"))[:32]
            tx["signature"] = signature
            tx["public_key_ref"] = bank_key
            tx["signed_at"] = datetime.utcnow().isoformat()
            signed.append(tx)
        return self._store({"transactions": signed, "mode": "store"})

    def _verify(self, prepared: Any) -> Any:
        """验证某笔交易是否在链上 + 签名是否有效。"""
        tx_id = prepared.get("transactions", [{}])[0].get("tx_id", "")
        chain = self.model["chain"]
        found_block = None
        found_tx = None
        for block in chain:
            for tx in block.get("transactions", []):
                if tx.get("tx_id") == tx_id:
                    found_block = block
                    found_tx = tx
                    break
            if found_block:
                break
        sig_valid = False
        if found_tx and "signature" in found_tx:
            sign_payload = found_tx["payload_hash"] + found_tx["bank_id"] + found_tx["timestamp"]
            expected = _sha256(sign_payload + found_tx.get("bank_private_key", "SECRET"))
            sig_valid = expected == found_tx["signature"]
        chain_valid = self._validate_chain()
        return {
            "tx_id": tx_id,
            "found_on_chain": found_tx is not None,
            "block_index": found_block["index"] if found_block else None,
            "merkle_root": found_block["merkle_root"] if found_block else None,
            "signature_valid": sig_valid,
            "chain_valid": chain_valid,
            "verified": found_tx is not None and sig_valid and chain_valid,
        }

    def _validate_chain(self) -> bool:
        chain = self.model["chain"]
        for i in range(1, len(chain)):
            if chain[i]["prev_hash"] != chain[i - 1]["hash"]:
                return False
            # 区块哈希在 _mine_block 中于回填 block_index/block_hash 之前计算，
            # 校验时需剔除这两个回填字段以保持序列化一致。
            clean_txs = [
                {k: v for k, v in tx.items() if k not in ("block_index", "block_hash")}
                for tx in chain[i]["transactions"]
            ]
            raw = json.dumps({
                "index": chain[i]["index"], "timestamp": chain[i]["timestamp"],
                "transactions": clean_txs,
                "merkle_root": chain[i]["merkle_root"],
                "prev_hash": chain[i]["prev_hash"],
            }, sort_keys=True, ensure_ascii=False, default=str)
            if _sha256(raw) != chain[i]["hash"]:
                return False
        return True

    def _chain_summary(self) -> dict:
        chain = self.model["chain"]
        total_txs = sum(len(b.get("transactions", [])) for b in chain[1:])
        return {
            "blocks": len(chain),
            "transactions_total": total_txs,
            "latest_hash": chain[-1]["hash"],
            "latest_index": chain[-1]["index"],
            "chain_valid": self._validate_chain(),
        }

    def _postprocess(self, result: Any) -> Any:
        if "verified" in result:
            return result
        result["certificate"] = {
            "tx_ids": [t["tx_id"] for b in self.model["chain"][1:] for t in b["transactions"]],
            "chain_height": self.model["chain"][-1]["index"],
            "merkle_root": self.model["chain"][-1]["merkle_root"],
            "timestamp": self.model["chain"][-1]["timestamp"],
            "chain_valid": result.get("chain_valid", True),
        }
        result["disclaimer"] = "模拟区块链存证，生产环境需接入 Hyperledger Fabric / FISCO BCOS"
        return result
