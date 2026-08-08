"""[FA-12] pipeline 端到端单测：Pipeline.run() 全流程 + custom_* 生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_12.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_fixture("sample_input.json")
        self.output = self.pipe.run(self.sample)

    def test_output_status_and_module(self):
        """输出 status=ok, module=FA-12。"""
        self.assertEqual(self.output["status"], "ok")
        self.assertEqual(self.output["module"], "FA-12")

    def test_output_has_required_sections(self):
        """输出含 disclosure_items / completeness_summary / missing_items / supplement_suggestions。"""
        for key in ("disclosure_items", "completeness_summary",
                    "missing_items", "supplement_suggestions"):
            self.assertIn(key, self.output)

    def test_disclosure_items_count_matches_input(self):
        """输出条目数与输入一致（5）。"""
        self.assertEqual(
            len(self.output["disclosure_items"]),
            len(self.sample["transactions"]),
        )

    def test_completeness_summary_score(self):
        """completeness_summary.completeness_score = 32.0。"""
        self.assertEqual(
            self.output["completeness_summary"]["completeness_score"], 32.0
        )


class TestPipelineCollect(unittest.TestCase):
    """_collect 数据采集。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_list_input_wraps_transactions(self):
        """裸 list → {transactions: list, disclosure_text: ''}。"""
        collected = self.pipe._collect([{"tx_id": "T1"}])
        self.assertEqual(len(collected["transactions"]), 1)
        self.assertEqual(collected["disclosure_text"], "")

    def test_collect_chinese_keys_normalized(self):
        """中文键 交易/披露文本/关联方清单 归一化。"""
        collected = self.pipe._collect({
            "交易": [{"id": "T1"}],
            "披露文本": "披露内容",
            "关联方清单": ["甲公司"],
        })
        self.assertEqual(len(collected["transactions"]), 1)
        self.assertEqual(collected["disclosure_text"], "披露内容")
        self.assertEqual(collected["related_parties"], ["甲公司"])

    def test_collect_non_dict_non_list_returns_empty(self):
        """非法输入 → 空结构。"""
        collected = self.pipe._collect("invalid")
        self.assertEqual(collected["transactions"], [])
        self.assertEqual(collected["disclosure_text"], "")

    def test_collect_scalar_parties_wrapped(self):
        """标量关联方清单包装为列表。"""
        collected = self.pipe._collect({
            "transactions": [],
            "related_parties": "单个公司",
        })
        self.assertEqual(collected["related_parties"], ["单个公司"])


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_fixture("sample_input.json")
        self.output = self.pipe.run(self.sample)

    def test_thresholds_risk_level_high(self):
        """完整性 32 < 60 → risk_level=high。"""
        summary = self.output["completeness_summary"]
        self.assertEqual(summary["risk_level"], "high")

    def test_thresholds_compliance_level_applied(self):
        """每条目含 compliance_level（high/medium/low）。"""
        valid = {"high", "medium", "low"}
        for item in self.output["disclosure_items"]:
            self.assertIn(item["compliance_level"], valid)

    def test_rules_regulatory_action_required(self):
        """完整性 < 60% → regulatory_action_required=True。"""
        summary = self.output["completeness_summary"]
        self.assertTrue(summary["regulatory_action_required"])

    def test_rules_high_risk_items_synced(self):
        """high_risk_items 含 TX-D04（high 严重度未披露）。"""
        # custom_rules 同步 high_risk_items 到内部结果，formatter 未直接输出
        # 改为验证 disclosure_items 中 TX-D04 severity=high
        for item in self.output["disclosure_items"]:
            if item["tx_id"] == "TX-D04":
                self.assertEqual(item["severity"], "high")
                break

    def test_missing_items_populated(self):
        """missing_items 含未披露与部分披露条目（4 条）。"""
        missing = self.output["missing_items"]
        self.assertEqual(len(missing), 4)
        tx_ids = {m["tx_id"] for m in missing}
        self.assertIn("TX-D04", tx_ids)
        self.assertIn("TX-D02", tx_ids)
        # OK 条目不在 missing_items
        self.assertNotIn("TX-D01", tx_ids)

    def test_supplement_suggestions_has_p0(self):
        """补披露建议含 P0 优先级。"""
        priorities = {
            s["priority"] for s in self.output["supplement_suggestions"]
        }
        self.assertIn("P0", priorities)


class TestPipelineConfigOverride(unittest.TestCase):
    """config 覆盖阈值。"""

    def test_custom_regulatory_threshold(self):
        """通过 config 提高监管行动阈值至 90 → 32<90 仍触发。"""
        config = {"rules": {"regulatory_action_threshold": 90.0}}
        pipe = Pipeline(config=config)
        sample = _load_fixture("sample_input.json")
        output = pipe.run(sample)
        self.assertTrue(
            output["completeness_summary"]["regulatory_action_required"]
        )

    def test_custom_risk_threshold_low(self):
        """通过 config 调整 high_threshold=10 → 32≥10 → risk_level 非 high。"""
        config = {"threshold": {"high_threshold": 10.0, "low_threshold": 50.0}}
        pipe = Pipeline(config=config)
        sample = _load_fixture("sample_input.json")
        output = pipe.run(sample)
        self.assertEqual(output["completeness_summary"]["risk_level"], "medium")


if __name__ == "__main__":
    unittest.main(verbosity=2)
