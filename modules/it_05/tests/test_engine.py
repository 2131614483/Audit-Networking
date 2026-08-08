"""[IT-05] engine 单测：区块链存证 / Merkle 树 / PoW / 链验证。

BlockchainEngine 为纯 stdlib 实现（无 PortableDB 依赖），有状态（self.blocks）：
  * _preprocess : 审计日志 → SHA-256 哈希 → 交易列表
  * _infer      : Merkle 树构建 → PoW 挖矿 → 多方节点签名 → 存证证书
  * _postprocess: 输出存证证书 + 区块 + 链状态
注：difficulty=1 加速测试（默认 3）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from modules.it_05.engine import BlockchainEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> BlockchainEngine:
    eng = BlockchainEngine(config={"difficulty": 1, **overrides})
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 模型加载 / 创世块
# ----------------------------------------------------------------------
def test_model_loads_chain_and_genesis():
    """setup 后含 chain_id / 3 节点 / 创世块（index=0）。"""
    eng = _make_engine(chain_id="TEST_CHAIN")
    assert eng.chain_id == "TEST_CHAIN"
    assert len(eng.nodes) == 3
    assert len(eng.blocks) == 1  # 创世块
    assert eng.blocks[0]["index"] == 0
    assert eng.next_index == 1


def test_genesis_block_has_valid_hash():
    """创世块哈希满足 difficulty 前导零。"""
    eng = _make_engine(difficulty=2)
    genesis = eng.blocks[0]
    assert genesis["hash"].startswith("00")
    assert genesis["previous_hash"] == "0" * 64


def test_genesis_block_carries_node_signatures():
    """创世块含所有节点的签名。"""
    eng = _make_engine()
    genesis = eng.blocks[0]
    assert len(genesis["node_signatures"]) == 3
    for sig in genesis["node_signatures"]:
        assert "node_id" in sig
        assert len(sig["signature"]) == 16


def test_difficulty_configurable():
    """difficulty 可通过 config 覆盖。"""
    eng = _make_engine(difficulty=1)
    assert eng.difficulty == 1
    assert eng.blocks[0]["difficulty"] == 1


# ----------------------------------------------------------------------
# Merkle 树
# ----------------------------------------------------------------------
def test_merkle_root_empty_input():
    """空列表返回 'empty' 的哈希。"""
    eng = _make_engine()
    root = eng._merkle_root([])
    assert root == hashlib.sha256(b"empty").hexdigest()


def test_merkle_root_single_item():
    """单元素 Merkle 根 = 该元素的 SHA-256。"""
    eng = _make_engine()
    data = "test"
    expected = hashlib.sha256(data.encode()).hexdigest()
    assert eng._merkle_root([data]) == expected


def test_merkle_root_two_items():
    """两元素 Merkle 根 = SHA256(h1 + h2)。"""
    eng = _make_engine()
    h1 = hashlib.sha256(b"a").hexdigest()
    h2 = hashlib.sha256(b"b").hexdigest()
    expected = hashlib.sha256((h1 + h2).encode()).hexdigest()
    assert eng._merkle_root(["a", "b"]) == expected


def test_merkle_root_deterministic():
    """相同输入产生相同 Merkle 根。"""
    eng = _make_engine()
    data = ["x", "y", "z"]
    assert eng._merkle_root(data) == eng._merkle_root(data)


# ----------------------------------------------------------------------
# PoW 挖矿
# ----------------------------------------------------------------------
def test_mine_produces_valid_hash():
    """_mine 返回的 hash 满足 difficulty 前导零。"""
    eng = _make_engine(difficulty=2)
    nonce, h = eng._mine(1, "prev", "merkle", "2026-01-01", ["data"])
    assert h.startswith("00")
    # 验证 hash 可复现
    raw = f"1prevmerkle2026-01-01{nonce}".encode()
    assert hashlib.sha256(raw).hexdigest() == h


def test_node_sign_deterministic():
    """_node_sign 对相同输入返回相同签名（16 位 hex）。"""
    eng = _make_engine(chain_id="CHAIN")
    sig = eng._node_sign("NODE-01", "abc123")
    assert len(sig) == 16
    assert sig == eng._node_sign("NODE-01", "abc123")


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_dict_to_transaction():
    """dict 输入 → transaction（含 hash / raw / type / entity）。"""
    eng = _make_engine()
    txs = eng._preprocess([{"type": "audit_log", "entity": "u1", "action": "login"}])
    assert len(txs) == 1
    assert txs[0]["type"] == "audit_log"
    assert txs[0]["entity"] == "u1"
    assert len(txs[0]["hash"]) == 64  # SHA-256 hex


def test_preprocess_string_input():
    """字符串输入 → type=audit_log, entity=''。"""
    eng = _make_engine()
    txs = eng._preprocess(["raw log line"])
    assert txs[0]["type"] == "audit_log"
    assert txs[0]["entity"] == ""


def test_preprocess_dict_input_wrapped_as_list():
    """dict 输入被包装为单元素 list。"""
    eng = _make_engine()
    txs = eng._preprocess({"type": "x", "entity": "y"})
    assert len(txs) == 1


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_postprocessed_structure():
    """execute 返回 deposit / certificates / block / chain_status。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "deposit" in result
    assert "certificates" in result
    assert "block" in result
    assert "chain_status" in result


def test_execute_appends_block_to_chain():
    """execute 后链长度 +1（追加新区块）。"""
    eng = _make_engine()
    assert len(eng.blocks) == 1  # 创世块
    eng.execute(_sample())
    assert len(eng.blocks) == 2
    assert eng.next_index == 2


def test_block_links_to_previous():
    """新区块的 previous_hash = 上一块的 hash。"""
    eng = _make_engine()
    prev_hash = eng.blocks[-1]["hash"]
    eng.execute(_sample())
    assert eng.blocks[-1]["previous_hash"] == prev_hash


def test_block_has_consensus():
    """区块含 node_signatures + consensus_achieved=True（3 节点 >= 2）。"""
    eng = _make_engine()
    eng.execute(_sample())
    block = eng.blocks[-1]
    assert len(block["node_signatures"]) == 3
    assert block["consensus_count"] == 3
    assert block["consensus_achieved"] is True
    assert block["consensus_required"] == 2  # max(2, 3//2+1) = 2


def test_certificates_one_per_transaction():
    """每个交易生成一个存证证书。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert len(result["certificates"]) == 3
    for cert in result["certificates"]:
        assert cert["certificate_id"].startswith("CERT-")
        assert len(cert["transaction_hash"]) == 64
        assert cert["block_hash"] == result["block"]["hash"]
        assert "merkle_proof" in cert
        assert "verification_url" in cert


def test_certificate_merkle_proof_non_empty():
    """证书的 merkle_proof 非空（3 笔交易 → 至少 2 层）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for cert in result["certificates"]:
        assert len(cert["merkle_proof"]) > 0
        for step in cert["merkle_proof"]:
            assert "level" in step
            assert "partner_hash" in step
            assert "partner_position" in step


def test_deposit_summary_structure():
    """deposit 摘要含 chain_id / block_hash / merkle_root / consensus。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    d = result["deposit"]
    assert d["transaction_count"] == 3
    assert d["chain_id"] == eng.chain_id
    assert d["consensus_achieved"] is True
    assert d["total_blocks_in_chain"] == 2


# ----------------------------------------------------------------------
# verify_transaction
# ----------------------------------------------------------------------
def test_verify_transaction_found():
    """verify_transaction 对已存证的交易返回 found=True + 验证通过。

    注意：block["transactions"] 存的是 transaction dict 的 json 字符串，
    verify_transaction 用该字符串的 SHA-256 查找，而非 _preprocess 返回的 tx["hash"]
    （后者是对原始输入的 hash）。需用 block 内实际存储的 tx hash 验证。
    """
    eng = _make_engine()
    eng.execute(_sample())
    # 取 block 内存储的第一笔交易字符串的 hash
    tx_in_block = eng.blocks[-1]["transactions"][0]
    tx_hash = hashlib.sha256(tx_in_block.encode()).hexdigest()
    result = eng.verify_transaction(tx_hash)
    assert result["found"] is True
    assert result["chain_valid"] is True
    assert result["block_hash_valid"] is True
    assert result["consensus_valid"] is True


def test_verify_transaction_not_found():
    """verify_transaction 对未知 hash 返回 found=False。"""
    eng = _make_engine()
    result = eng.verify_transaction("nonexistent_hash_64_chars_" + "0" * 38)
    assert result["found"] is False


def test_verify_chain_after_multiple_blocks():
    """连续追加多个区块后链仍有效。"""
    eng = _make_engine()
    eng.execute(_sample())
    eng.execute([{"type": "log", "entity": "x", "action": "test"}])
    assert eng._verify_chain() is True
    assert len(eng.blocks) == 3


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_input_returns_empty_status():
    """空 list 输入返回 status=empty。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["status"] == "empty"
    assert eng.blocks == [eng.blocks[0]]  # 只有创世块


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 时 _infer 有兜底（创建创世块），不抛异常。"""
    eng = BlockchainEngine(config={"difficulty": 1})
    # 未 setup → blocks=[], next_index=0，但 _infer 兜底创建创世块作为 prev_block
    # 新区块 index=next_index=0，append 后 blocks 只有 1 个块
    result = eng.execute(_sample())
    assert len(eng.blocks) == 1
    assert eng.blocks[-1]["index"] == 0  # next_index 未 setup 时为 0
    assert result["deposit"]["transaction_count"] == 3
