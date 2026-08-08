"""[FA-05] engine 单测：区块创建 / 哈希链 / Merkle 树 / 签名验证 / 篡改检测 / 共识。

unittest 风格（不依赖 pytest）。每个用例构造独立 engine（独立模拟账本）。
"""
from __future__ import annotations

import json
import unittest

from modules.fa_05.engine import (
    BlockchainEngine,
    _sha256,
    _merkle_root,
)


def _make_engine(**overrides) -> BlockchainEngine:
    config = {"threshold": {"high_trust_score": 0.95}}
    config.update(overrides)
    eng = BlockchainEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：模拟区块链账本初始化 + 创世块。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_genesis_block_created(self):
        """初始化后链含 1 个创世块（index=0）。"""
        chain = self.engine.model["chain"]
        self.assertEqual(len(chain), 1)
        self.assertEqual(chain[0]["index"], 0)

    def test_genesis_prev_hash_zeros(self):
        """创世块 prev_hash 为 64 个 0。"""
        genesis = self.engine.model["chain"][0]
        self.assertEqual(genesis["prev_hash"], "0" * 64)

    def test_genesis_hash_is_sha256_of_GENESIS(self):
        """创世块 hash = sha256('GENESIS')。"""
        genesis = self.engine.model["chain"][0]
        self.assertEqual(genesis["hash"], _sha256("GENESIS"))

    def test_genesis_has_no_transactions(self):
        """创世块无交易。"""
        self.assertEqual(self.engine.model["chain"][0]["transactions"], [])

    def test_model_defaults(self):
        """blocks_per_batch=1，pending_tx 初始为空。"""
        self.assertEqual(self.engine.model["blocks_per_batch"], 1)
        self.assertEqual(self.engine.model["pending_tx"], [])
        self.assertEqual(self.engine.model["bank_public_keys"], {})


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：发函交易标准化 + 哈希。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_preprocess_requires_dict(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess(["not", "dict"])

    def test_preprocess_normalizes_transactions(self):
        """交易标准化：tx_id / payload_hash / bank_id / action / timestamp。"""
        prepared = self.engine._preprocess({"transactions": [
            {"tx_id": "T1", "bank_id": "B1", "action": "initiate"},
        ]})
        tx = prepared["transactions"][0]
        self.assertEqual(tx["tx_id"], "T1")
        self.assertEqual(tx["bank_id"], "B1")
        self.assertEqual(tx["action"], "initiate")
        self.assertEqual(len(tx["payload_hash"]), 64)
        self.assertIn("timestamp", tx)
        self.assertEqual(prepared["mode"], "store")

    def test_preprocess_single_confirmation_dict(self):
        """含 confirmation_id 的单笔 dict 包装为列表。"""
        prepared = self.engine._preprocess({"confirmation_id": "CF1", "bank_id": "B1"})
        self.assertEqual(len(prepared["transactions"]), 1)

    def test_preprocess_payload_hash_deterministic(self):
        """相同 payload → 相同 payload_hash。"""
        p1 = self.engine._preprocess({"transactions": [{"tx_id": "T1", "balance": 100}]})
        p2 = self.engine._preprocess({"transactions": [{"tx_id": "T1", "balance": 100}]})
        self.assertEqual(p1["transactions"][0]["payload_hash"],
                         p2["transactions"][0]["payload_hash"])

    def test_preprocess_default_mode(self):
        """无 mode 字段 → 默认 store。"""
        prepared = self.engine._preprocess({"transactions": []})
        self.assertEqual(prepared["mode"], "store")

    def test_preprocess_default_bank_id(self):
        """无 bank_id → 默认 UNKNOWN。"""
        prepared = self.engine._preprocess({"transactions": [{"tx_id": "T1"}]})
        self.assertEqual(prepared["transactions"][0]["bank_id"], "UNKNOWN")


class TestEngineStore(unittest.TestCase):
    """_store：交易打包 → 区块写入。"""

    def test_store_creates_blocks(self):
        """3 笔交易 → 3 个新区块 + 创世块 = 4 块。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": f"T{i}", "bank_id": "B1"} for i in range(3)
        ]})
        self.assertEqual(result["blocks"], 4)
        self.assertEqual(eng.model["chain"][-1]["index"], 3)

    def test_store_transactions_total(self):
        """transactions_total 等于存入交易数。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
            {"tx_id": "T2", "bank_id": "B2"},
        ]})
        self.assertEqual(result["transactions_total"], 2)

    def test_store_chain_valid(self):
        """存入后链有效。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        self.assertTrue(result["chain_valid"])

    def test_store_sets_block_index_on_tx(self):
        """每笔交易被写入区块后获得 block_index / block_hash。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        block = eng.model["chain"][1]
        tx = block["transactions"][0]
        self.assertEqual(tx["block_index"], 1)
        self.assertEqual(tx["block_hash"], block["hash"])

    def test_store_empty_transactions(self):
        """空交易列表 → 仅创世块。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": []})
        self.assertEqual(result["blocks"], 1)
        self.assertEqual(result["transactions_total"], 0)

    def test_store_latest_hash_matches_last_block(self):
        """latest_hash 等于链尾区块 hash。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        self.assertEqual(result["latest_hash"], eng.model["chain"][-1]["hash"])


class TestEngineHashChain(unittest.TestCase):
    """哈希链 + Merkle 树。"""

    def test_block_hash_chaining(self):
        """区块 i 的 prev_hash == 区块 i-1 的 hash。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": f"T{i}", "bank_id": "B1"} for i in range(3)
        ]})
        chain = eng.model["chain"]
        for i in range(1, len(chain)):
            self.assertEqual(chain[i]["prev_hash"], chain[i - 1]["hash"])

    def test_block_hash_computed_correctly(self):
        """区块 hash = sha256(序列化区块内容，剔除回填的 block_index/block_hash)。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        block = eng.model["chain"][1]
        clean_txs = [
            {k: v for k, v in tx.items() if k not in ("block_index", "block_hash")}
            for tx in block["transactions"]
        ]
        raw = json.dumps({
            "index": block["index"], "timestamp": block["timestamp"],
            "transactions": clean_txs, "merkle_root": block["merkle_root"],
            "prev_hash": block["prev_hash"],
        }, sort_keys=True, ensure_ascii=False, default=str)
        self.assertEqual(block["hash"], _sha256(raw))

    def test_merkle_root_empty(self):
        """空哈希列表 → merkle_root = sha256('')。"""
        self.assertEqual(_merkle_root([]), _sha256(""))

    def test_merkle_root_single_tx(self):
        """单笔交易区块 → merkle_root = 该交易 payload_hash。"""
        eng = _make_engine()
        prepared = eng._preprocess({"transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        h = prepared["transactions"][0]["payload_hash"]
        self.assertEqual(_merkle_root([h]), h)

    def test_merkle_root_two_hashes(self):
        """两笔交易 → merkle_root = sha256(h1 + h2)。"""
        h1 = _sha256("a")
        h2 = _sha256("b")
        self.assertEqual(_merkle_root([h1, h2]), _sha256(h1 + h2))

    def test_block_merkle_root_matches(self):
        """区块 merkle_root 等于其交易哈希的 Merkle 根。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        block = eng.model["chain"][1]
        tx_hashes = [t["payload_hash"] for t in block["transactions"]]
        self.assertEqual(block["merkle_root"], _merkle_root(tx_hashes))


class TestEngineSign(unittest.TestCase):
    """_sign_response：银行模拟签名。"""

    def test_sign_adds_signature(self):
        """sign 模式 → 交易获得 signature / public_key_ref / signed_at。"""
        eng = _make_engine()
        eng.execute({"mode": "sign", "transactions": [
            {"tx_id": "S1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        block = eng.model["chain"][1]
        tx = block["transactions"][0]
        self.assertIn("signature", tx)
        self.assertEqual(len(tx["signature"]), 64)
        self.assertEqual(tx["public_key_ref"], "PUB-B1")
        self.assertIn("signed_at", tx)

    def test_sign_stores_public_key(self):
        """sign → bank_public_keys 记录 PUB-bank_id。"""
        eng = _make_engine()
        eng.execute({"mode": "sign", "transactions": [
            {"tx_id": "S1", "bank_id": "BANK-X", "confirmation_id": "CF1"},
        ]})
        self.assertIn("PUB-BANK-X", eng.model["bank_public_keys"])

    def test_sign_stores_transaction_on_chain(self):
        """sign 后交易上链（blocks 增加）。"""
        eng = _make_engine()
        result = eng.execute({"mode": "sign", "transactions": [
            {"tx_id": "S1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        self.assertEqual(result["blocks"], 2)
        self.assertEqual(result["transactions_total"], 1)


class TestEngineVerify(unittest.TestCase):
    """_verify：链上查证 + 签名验证。"""

    def test_verify_found_signed_tx(self):
        """sign 上链后 verify → found + signature_valid + verified。"""
        eng = _make_engine()
        eng.execute({"mode": "sign", "transactions": [
            {"tx_id": "V1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "V1"}]})
        self.assertTrue(result["found_on_chain"])
        self.assertTrue(result["signature_valid"])
        self.assertTrue(result["chain_valid"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["block_index"], 1)

    def test_verify_unsigned_tx_not_verified(self):
        """store（未签名）上链后 verify → found 但 signature_valid=False。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "U1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "U1"}]})
        self.assertTrue(result["found_on_chain"])
        self.assertFalse(result["signature_valid"])
        self.assertFalse(result["verified"])

    def test_verify_nonexistent_tx(self):
        """验证不存在的交易 → found_on_chain=False。"""
        eng = _make_engine()
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "NOPE"}]})
        self.assertFalse(result["found_on_chain"])
        self.assertIsNone(result["block_index"])
        self.assertFalse(result["verified"])

    def test_verify_chain_valid_after_multiple_stores(self):
        """多次 store 后链仍有效。"""
        eng = _make_engine()
        for i in range(3):
            eng.execute({"mode": "store", "transactions": [
                {"tx_id": f"T{i}", "bank_id": "B1"},
            ]})
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "T0"}]})
        self.assertTrue(result["chain_valid"])

    def test_verify_returns_merkle_root(self):
        """verify 返回所在区块的 merkle_root。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "V1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "V1"}]})
        self.assertIsNotNone(result["merkle_root"])


class TestEngineTamperDetection(unittest.TestCase):
    """篡改检测：_validate_chain。"""

    def test_validate_chain_unchanged_valid(self):
        """未篡改的链 → _validate_chain=True。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        self.assertTrue(eng._validate_chain())

    def test_tamper_transaction_breaks_chain(self):
        """篡改区块交易内容 → _validate_chain=False。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        self.assertTrue(eng._validate_chain())
        eng.model["chain"][1]["transactions"][0]["tx_id"] = "TAMPERED"
        self.assertFalse(eng._validate_chain())

    def test_tamper_block_hash_breaks_chain(self):
        """篡改区块 hash → _validate_chain=False。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
            {"tx_id": "T2", "bank_id": "B2"},
        ]})
        eng.model["chain"][1]["hash"] = "0" * 64
        self.assertFalse(eng._validate_chain())

    def test_tamper_merkle_root_breaks_chain(self):
        """篡改 merkle_root → _validate_chain=False。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        eng.model["chain"][1]["merkle_root"] = "tampered"
        self.assertFalse(eng._validate_chain())

    def test_verify_detects_tampered_chain(self):
        """篡改后 verify → chain_valid=False → verified=False。"""
        eng = _make_engine()
        eng.execute({"mode": "sign", "transactions": [
            {"tx_id": "V1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        eng.model["chain"][1]["transactions"][0]["tx_id"] = "TAMPERED"
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "V1"}]})
        self.assertFalse(result["chain_valid"])
        self.assertFalse(result["verified"])


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：存证证书。"""

    def test_postprocess_store_adds_certificate(self):
        """store 结果含 certificate（tx_ids / chain_height / merkle_root）。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        self.assertIn("certificate", result)
        self.assertEqual(result["certificate"]["tx_ids"], ["T1"])
        self.assertEqual(result["certificate"]["chain_height"], 1)

    def test_postprocess_verify_no_certificate(self):
        """verify 结果不含 certificate（原样返回）。"""
        eng = _make_engine()
        eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        result = eng.execute({"mode": "verify", "transactions": [{"tx_id": "T1"}]})
        self.assertNotIn("certificate", result)
        self.assertIn("verified", result)

    def test_postprocess_disclaimer_present(self):
        """store 结果含 disclaimer。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        self.assertIn("disclaimer", result)
        self.assertIn("区块链", result["disclaimer"])

    def test_certificate_chain_valid(self):
        """certificate.chain_valid 反映链有效性。"""
        eng = _make_engine()
        result = eng.execute({"mode": "store", "transactions": [
            {"tx_id": "T1", "bank_id": "B1"},
        ]})
        self.assertTrue(result["certificate"]["chain_valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
