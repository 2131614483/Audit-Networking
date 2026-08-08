"""[FA-05] pipeline 端到端单测：Pipeline.run() 全流程 + custom 生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestPipelineStoreEndToEnd(unittest.TestCase):
    """store 模式端到端。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_pipeline_store_with_sample_input(self):
        """sample_input store 端到端跑通，输出含 certificate / blocks。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "FA-05")
        self.assertEqual(output["mode"], "store")
        self.assertIn("certificate", output)
        self.assertIn("blocks", output)

    def test_pipeline_certificate_tx_ids(self):
        """certificate.tx_ids 与输入交易 ID 一致。"""
        sample = _load_sample_input()
        output = self.pipe.run(sample)
        self.assertEqual(
            output["certificate"]["tx_ids"],
            ["BC-TX-001", "BC-TX-002", "BC-TX-003"],
        )

    def test_pipeline_chain_summary(self):
        """chain_summary：blocks=4（创世+3），transactions_total=3。"""
        output = self.pipe.run(_load_sample_input())
        summary = output["chain_summary"]
        self.assertEqual(summary["blocks"], 4)
        self.assertEqual(summary["transactions_total"], 3)
        self.assertTrue(summary["chain_valid"])

    def test_pipeline_blocks_populated(self):
        """blocks 含 4 个区块（含创世块）。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(len(output["blocks"]), 4)
        self.assertEqual(output["blocks"][0]["index"], 0)
        self.assertEqual(output["blocks"][1]["tx_ids"], ["BC-TX-001"])

    def test_pipeline_hash_chain_all_linked(self):
        """哈希链所有区块 linked=True。"""
        output = self.pipe.run(_load_sample_input())
        for link in output["hash_chain"]:
            self.assertTrue(link["linked"])

    def test_pipeline_audit_trail_populated(self):
        """审计轨迹含每个区块一条记录。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(len(output["audit_trail"]), 4)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def test_pipeline_integrity_high_for_valid_chain(self):
        """有效链 → integrity_score=1.0, trust_level=high。"""
        pipe = Pipeline()
        output = pipe.run(_load_sample_input())
        self.assertEqual(output["integrity"]["integrity_score"], 1.0)
        self.assertEqual(output["integrity"]["trust_level"], "high")
        self.assertEqual(output["integrity"]["verification_level"], "verified")

    def test_pipeline_no_alerts_for_valid_store(self):
        """有效存证 → 无告警。"""
        pipe = Pipeline()
        output = pipe.run(_load_sample_input())
        self.assertEqual(output["alerts"], [])
        self.assertFalse(output["tamper_alert"])

    def test_pipeline_empty_chain_alert(self):
        """空链（无交易）→ empty_chain 告警。"""
        pipe = Pipeline()
        output = pipe.run({"mode": "store", "transactions": []})
        types = [a["type"] for a in output["alerts"]]
        self.assertIn("empty_chain", types)


class TestPipelineVerifyAndTamper(unittest.TestCase):
    """verify 模式 + 篡改告警。"""

    def test_pipeline_verify_signed_tx(self):
        """sign 上链后 verify → verified=True。"""
        pipe = Pipeline()
        pipe.engine.execute({"mode": "sign", "transactions": [
            {"tx_id": "PV1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]})
        output = pipe.run({"mode": "verify", "transactions": [{"tx_id": "PV1"}]})
        self.assertEqual(output["mode"], "verify")
        self.assertTrue(output["verification"]["verified"])
        self.assertTrue(output["verification"]["signature_valid"])

    def test_pipeline_tamper_alert_on_tampered_chain(self):
        """篡改区块 hash 后 verify → tamper_alert=True。"""
        pipe = Pipeline()
        pipe.engine.execute({"mode": "store", "transactions": [
            {"tx_id": "PT1", "bank_id": "B1"},
        ]})
        pipe.engine.model["chain"][1]["hash"] = "0" * 64
        output = pipe.run({"mode": "verify", "transactions": [{"tx_id": "PT1"}]})
        self.assertTrue(output["tamper_alert"])
        self.assertFalse(output["verification"]["chain_valid"])
        self.assertGreater(output["alert_count"], 0)

    def test_pipeline_verify_nonexistent_tx(self):
        """验证不存在的交易 → found_on_chain=False, verified=False。"""
        pipe = Pipeline()
        output = pipe.run({"mode": "verify", "transactions": [{"tx_id": "NOPE"}]})
        self.assertFalse(output["verification"]["found_on_chain"])
        self.assertFalse(output["verification"]["verified"])


class TestPipelineCollect(unittest.TestCase):
    """_collect 输入归一化。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_list_input(self):
        """list 输入包装为 transactions。"""
        collected = self.pipe._collect([
            {"tx_id": "X1", "bank_id": "B1"},
            {"tx_id": "X2", "bank_id": "B2"},
        ])
        self.assertEqual(len(collected["transactions"]), 2)

    def test_collect_single_confirmation(self):
        """单笔 confirmation_id dict 包装为列表。"""
        collected = self.pipe._collect({"confirmation_id": "CF1", "bank_id": "B1"})
        self.assertEqual(len(collected["transactions"]), 1)

    def test_collect_invalid_raises(self):
        """非法输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.pipe._collect(12345)


if __name__ == "__main__":
    unittest.main(verbosity=2)
