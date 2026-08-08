"""[blockchain] IT-05 区块链审计日志存证。

纯 stdlib 实现的审计日志区块链存证引擎：
  - _load_model  : 初始化链状态 + 加载配置（链名/存证策略/验证规则）
  - _preprocess  : 输入审计日志/证据数据，SHA-256 哈希 → Merkle 树构建 → 区块打包
  - _infer       : 链上写入模拟（PoW简化 + 智能合约存证 + 多方节点确认）→ 存证证书生成
  - _postprocess : 输出存证证书（区块哈希/Merkle根/节点签名/可验证性）+ 验证能力
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta

from modules.shared.base_engine import AbstractEngine


_PROOF_OF_WORK_DIFFICULTY = 3
_TXN_VALID_STATES = {"committed", "uncommitted", "archived"}


class BlockchainEngine(AbstractEngine):
    """IT-05 区块链审计日志存证引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.chain_id = ""
        self.nodes = []
        self.blocks = []
        self.difficulty = 0
        self.next_index = 0

    def _load_model(self):
        self.chain_id = self.config.get("chain_id", f"AUDIT_CHAIN_{int(datetime.now().timestamp())}")
        self.nodes = self.config.get("nodes", [
            {"id": "NODE-01", "name": "审计节点A", "role": "validator"},
            {"id": "NODE-02", "name": "审计节点B", "role": "validator"},
            {"id": "NODE-03", "name": "监管节点", "role": "witness"},
        ])
        self.difficulty = self.config.get("difficulty", _PROOF_OF_WORK_DIFFICULTY)
        self.blocks = self.config.get("initial_blocks", [])
        self.next_index = len(self.blocks)
        if not self.blocks:
            genesis = self._create_genesis_block()
            self.blocks.append(genesis)
            self.next_index = 1

    def _create_genesis_block(self) -> dict:
        now = datetime.now()
        genesis_data = json.dumps({
            "chain_id": self.chain_id,
            "purpose": "审计日志存证区块链-创始块",
            "timestamp": now.isoformat(),
            "creator": "Audit Block Engine",
        }, ensure_ascii=False, sort_keys=True)
        prev_hash = "0" * 64
        merkle_root = self._merkle_root([genesis_data])
        nonce, block_hash = self._mine(0, prev_hash, merkle_root, now.isoformat(), [genesis_data])
        return {
            "index": 0,
            "timestamp": now.isoformat(),
            "transactions": [genesis_data],
            "merkle_root": merkle_root,
            "previous_hash": prev_hash,
            "nonce": nonce,
            "hash": block_hash,
            "difficulty": self.difficulty,
            "node_signatures": [{"node_id": n["id"], "signature": self._node_sign(n["id"], block_hash)} for n in self.nodes],
            "consensus_count": len(self.nodes),
        }

    def _node_sign(self, node_id: str, block_hash: str) -> str:
        raw = f"{node_id}:{block_hash}:{self.chain_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _merkle_root(self, data_list: list) -> str:
        if not data_list:
            return hashlib.sha256(b"empty").hexdigest()
        hashes = [hashlib.sha256(str(d).encode()).hexdigest() for d in data_list]
        while len(hashes) > 1:
            next_level = []
            for i in range(0, len(hashes), 2):
                a = hashes[i]
                b = hashes[i + 1] if i + 1 < len(hashes) else a
                combined = (a + b).encode()
                next_level.append(hashlib.sha256(combined).hexdigest())
            hashes = next_level
        return hashes[0]

    def _mine(self, index: int, prev_hash: str, merkle_root: str, timestamp: str, data: list) -> tuple[int, str]:
        target = "0" * self.difficulty
        nonce = 0
        while True:
            raw = f"{index}{prev_hash}{merkle_root}{timestamp}{nonce}".encode()
            h = hashlib.sha256(raw).hexdigest()
            if h.startswith(target):
                return nonce, h
            nonce += 1
            if nonce > 100000:
                return nonce, hashlib.sha256(raw).hexdigest()

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        transactions = []
        for it in items:
            if isinstance(it, str):
                tx_data = it
            elif isinstance(it, dict):
                tx_data = json.dumps(it, ensure_ascii=False, sort_keys=True)
            else:
                tx_data = str(it)
            tx_hash = hashlib.sha256(tx_data.encode()).hexdigest()
            transactions.append({
                "raw": tx_data,
                "hash": tx_hash,
                "timestamp": datetime.now().isoformat(),
                "type": it.get("type", "audit_log") if isinstance(it, dict) else "audit_log",
                "entity": it.get("entity", "") if isinstance(it, dict) else "",
            })
        return transactions

    def _infer(self, prepared):
        transactions = prepared
        if not transactions:
            return {"block": None, "certificates": []}
        tx_data_list = [json.dumps(t, ensure_ascii=False, sort_keys=True) for t in transactions]
        merkle_root = self._merkle_root(tx_data_list)
        prev_block = self.blocks[-1] if self.blocks else self._create_genesis_block()
        prev_hash = prev_block["hash"]
        now = datetime.now()
        index = self.next_index
        nonce, block_hash = self._mine(index, prev_hash, merkle_root, now.isoformat(), tx_data_list)
        signatures = [{"node_id": n["id"], "node_name": n["name"], "signature": self._node_sign(n["id"], block_hash)}
                      for n in self.nodes]
        block = {
            "index": index,
            "chain_id": self.chain_id,
            "timestamp": now.isoformat(),
            "transactions": tx_data_list,
            "transaction_count": len(tx_data_list),
            "merkle_root": merkle_root,
            "previous_hash": prev_hash,
            "nonce": nonce,
            "hash": block_hash,
            "difficulty": self.difficulty,
            "node_signatures": signatures,
            "consensus_count": len(self.nodes),
            "consensus_required": max(2, len(self.nodes) // 2 + 1),
            "consensus_achieved": len(signatures) >= max(2, len(self.nodes) // 2 + 1),
            "block_time": round(nonce * 0.001, 4),
        }
        self.blocks.append(block)
        self.next_index = index + 1
        certificates = []
        for tx in transactions:
            cert = self._generate_certificate(tx, block)
            certificates.append(cert)
        return {"block": block, "certificates": certificates, "generated_at": now.isoformat()}

    def _generate_certificate(self, tx: dict, block: dict) -> dict:
        tx_hash = tx["hash"]
        block_hash = block["hash"]
        merkle_proof = self._merkle_proof(block["transactions"], tx_hash)
        return {
            "certificate_id": f"CERT-{hashlib.md5(f'{tx_hash}{block_hash}'.encode()).hexdigest()[:10]}",
            "transaction_hash": tx_hash,
            "transaction_type": tx["type"],
            "entity": tx["entity"],
            "block_index": block["index"],
            "block_hash": block["hash"],
            "block_merkle_root": block["merkle_root"],
            "previous_block_hash": block["previous_hash"],
            "chain_id": block["chain_id"],
            "chain_position": f"{block['index']}/{self.next_index - 1}",
            "timestamp": block["timestamp"],
            "merkle_proof": merkle_proof,
            "node_signatures": block["node_signatures"],
            "consensus_achieved": block["consensus_achieved"],
            "verification_url": f"https://audit-chain.example.com/verify?tx={tx_hash}",
            "valid_from": block["timestamp"],
            "valid_to": (datetime.now() + timedelta(days=3650)).isoformat(),
        }

    def _merkle_proof(self, transactions: list, tx_hash: str) -> list:
        current_level = [hashlib.sha256(t.encode()).hexdigest() for t in transactions]
        proof = []
        target_idx = None
        for i, h in enumerate(current_level):
            if h == tx_hash or hashlib.sha256(transactions[i].encode()).hexdigest() == tx_hash:
                target_idx = i
                break
        if target_idx is None:
            target_idx = 0
        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                a = current_level[i]
                b = current_level[i + 1] if i + 1 < len(current_level) else a
                combined = (a + b).encode()
                next_level.append(hashlib.sha256(combined).hexdigest())
            partner_idx = target_idx + 1 if target_idx % 2 == 0 else target_idx - 1
            partner_hash = current_level[partner_idx] if partner_idx < len(current_level) else current_level[target_idx]
            proof.append({
                "level": len(proof),
                "partner_hash": partner_hash,
                "partner_position": "right" if target_idx % 2 == 0 else "left",
            })
            target_idx = target_idx // 2
            current_level = next_level
        return proof

    def verify_transaction(self, tx_hash: str) -> dict:
        for block in reversed(self.blocks):
            for tx in block["transactions"]:
                txh = hashlib.sha256(tx.encode()).hexdigest()
                if txh == tx_hash:
                    chain_valid = self._verify_chain()
                    proof_valid = self._verify_merkle_proof(block["transactions"], tx, block["merkle_root"])
                    block_valid = self._verify_block_hash(block)
                    return {
                        "found": True,
                        "block_index": block["index"],
                        "block_hash": block["hash"],
                        "timestamp": block["timestamp"],
                        "chain_valid": chain_valid,
                        "merkle_proof_valid": proof_valid,
                        "block_hash_valid": block_valid,
                        "consensus_valid": block["consensus_achieved"],
                        "verified_at": datetime.now().isoformat(),
                    }
        return {"found": False, "verified_at": datetime.now().isoformat()}

    def _verify_chain(self) -> bool:
        for i in range(1, len(self.blocks)):
            if self.blocks[i]["previous_hash"] != self.blocks[i - 1]["hash"]:
                return False
        return True

    def _verify_block_hash(self, block: dict) -> bool:
        target = "0" * block["difficulty"]
        raw = f"{block['index']}{block['previous_hash']}{block['merkle_root']}{block['timestamp']}{block['nonce']}".encode()
        computed = hashlib.sha256(raw).hexdigest()
        return computed == block["hash"] and computed.startswith(target)

    def _verify_merkle_proof(self, transactions: list, tx_data: str, merkle_root: str) -> bool:
        hashes = [hashlib.sha256(t.encode()).hexdigest() for t in transactions]
        while len(hashes) > 1:
            next_level = []
            for i in range(0, len(hashes), 2):
                a = hashes[i]
                b = hashes[i + 1] if i + 1 < len(hashes) else a
                next_level.append(hashlib.sha256((a + b).encode()).hexdigest())
            hashes = next_level
        return hashes[0] == merkle_root

    def _postprocess(self, result):
        if not result["block"]:
            return {"status": "empty", "message": "无待存证数据", "generated_at": result.get("generated_at", "")}
        block = result["block"]
        summary = {
            "chain_id": block["chain_id"],
            "block_index": block["index"],
            "block_hash": block["hash"],
            "merkle_root": block["merkle_root"],
            "transaction_count": block["transaction_count"],
            "consensus_count": block["consensus_count"],
            "consensus_achieved": block["consensus_achieved"],
            "difficulty": block["difficulty"],
            "total_blocks_in_chain": len(self.blocks),
            "generated_at": block["timestamp"],
        }
        return {
            "deposit": summary,
            "certificates": result["certificates"],
            "block": block,
            "chain_status": {
                "chain_id": self.chain_id,
                "total_blocks": len(self.blocks),
                "chain_valid": self._verify_chain(),
                "latest_hash": self.blocks[-1]["hash"],
            },
            "generated_at": result["generated_at"],
        }
