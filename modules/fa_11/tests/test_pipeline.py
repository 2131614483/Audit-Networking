"""[FA-11] pipeline 端到端单测：Pipeline.run() 全流程 + custom_* 生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_11.pipeline import Pipeline

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
        """输出 status=ok, module=FA-11。"""
        self.assertEqual(self.output["status"], "ok")
        self.assertEqual(self.output["module"], "FA-11")

    def test_output_has_required_sections(self):
        """输出含 transactions / fairness_summary / deviation_analysis / adjustment_suggestions。"""
        for key in ("transactions", "fairness_summary",
                    "deviation_analysis", "adjustment_suggestions"):
            self.assertIn(key, self.output)

    def test_transactions_count_matches_input(self):
        """输出交易数与输入一致（5）。"""
        self.assertEqual(
            len(self.output["transactions"]),
            len(self.sample["transactions"]),
        )

    def test_fairness_summary_total(self):
        """fairness_summary.total_transactions = 5。"""
        self.assertEqual(
            self.output["fairness_summary"]["total_transactions"], 5
        )


class TestPipelineCollect(unittest.TestCase):
    """_collect 数据采集。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_list_input_wraps_transactions(self):
        """裸 list → {transactions: list, peers: [], history: []}。"""
        collected = self.pipe._collect([{"tx_id": "T1"}])
        self.assertEqual(len(collected["transactions"]), 1)
        self.assertEqual(collected["peers"], [])
        self.assertEqual(collected["history"], [])

    def test_collect_chinese_keys_normalized(self):
        """中文键 交易/可比数据/历史价格 归一化。"""
        collected = self.pipe._collect({
            "交易": [{"id": "T1"}],
            "可比数据": [{"price": 100}],
            "历史价格": [{"price": 90}],
        })
        self.assertEqual(len(collected["transactions"]), 1)
        self.assertEqual(len(collected["peers"]), 1)
        self.assertEqual(len(collected["history"]), 1)

    def test_collect_non_dict_non_list_returns_empty(self):
        """非法输入 → 空结构。"""
        collected = self.pipe._collect("invalid")
        self.assertEqual(collected["transactions"], [])
        self.assertEqual(collected["peers"], [])

    def test_collect_scalar_transaction_wrapped(self):
        """标量交易字段包装为单元素列表。"""
        collected = self.pipe._collect({"transactions": {"tx_id": "T1"}})
        self.assertEqual(len(collected["transactions"]), 1)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_fixture("sample_input.json")
        self.output = self.pipe.run(self.sample)

    def test_thresholds_deviation_grade_applied(self):
        """每笔交易含 deviation_grade（fair/deviated/significantly_deviated）。"""
        valid = {"fair", "deviated", "significantly_deviated"}
        for t in self.output["transactions"]:
            self.assertIn(t["deviation_grade"], valid)

    def test_thresholds_needs_adjustment_flag(self):
        """deviation ≥ 10% → needs_adjustment=True（RP-003 偏离 35%）。"""
        for t in self.output["transactions"]:
            if t["tx_id"] == "RP-003":
                self.assertTrue(t["needs_adjustment"])
                break

    def test_rules_transfer_pricing_risk_for_large_deviation(self):
        """偏离率 > 30% → transfer_pricing_risk=True（RP-003 偏离 35%）。"""
        for t in self.output["transactions"]:
            if t["tx_id"] == "RP-003":
                self.assertTrue(t["transfer_pricing_risk"])
                break

    def test_rules_mandatory_disclosure_for_large_amount(self):
        """金额 > 1000万 → mandatory_disclosure=True（RP-003=1500万）。"""
        for t in self.output["transactions"]:
            if t["tx_id"] == "RP-003":
                self.assertTrue(t["mandatory_disclosure"])
                break
        # 金额未超阈值的交易不触发
        for t in self.output["transactions"]:
            if t["tx_id"] == "RP-001":
                self.assertFalse(t["mandatory_disclosure"])
                break

    def test_rules_industry_adjusted_deviation_present(self):
        """每笔交易含 industry_adjusted_deviation 与 industry_tolerance。"""
        for t in self.output["transactions"]:
            self.assertIn("industry_adjusted_deviation", t)
            self.assertIn("industry_tolerance", t)

    def test_deviation_analysis_summary(self):
        """deviation_analysis 含 transfer_pricing_risk_count ≥ 1。"""
        analysis = self.output["deviation_analysis"]
        self.assertGreaterEqual(
            analysis["transfer_pricing_risk_count"], 1
        )
        self.assertGreaterEqual(
            analysis["mandatory_disclosure_count"], 1
        )


class TestPipelineConfigOverride(unittest.TestCase):
    """config 覆盖阈值。"""

    def test_custom_threshold_config(self):
        """通过 config 自定义 deviation_fair 阈值。"""
        config = {"threshold": {"deviation_fair": 0.001}}
        pipe = Pipeline(config=config)
        sample = _load_fixture("sample_input.json")
        output = pipe.run(sample)
        # deviation_fair=0.001 → 几乎所有交易都非 fair
        grades = {t["deviation_grade"] for t in output["transactions"]}
        # RP-001/RP-004 偏离 0，仍可能为 fair（0 < 0.001 不成立 → deviated）
        self.assertIn("deviated", grades)


if __name__ == "__main__":
    unittest.main(verbosity=2)
