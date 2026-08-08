"""[CO-04] pipeline 端到端单测：Pipeline.run() 全流程。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_04.pipeline import Pipeline, _parse_amount, _parse_hour

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _load_expected_output():
    with open(_FIXTURES / "expected_output.json", encoding="utf-8") as f:
        return json.load(f)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_pipeline_run_with_sample_input(self):
        """用 sample_input.json 端到端跑通，输出含告警 + 汇总。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-04")
        self.assertIn("alerts", output)
        self.assertIn("summary", output)

    def test_pipeline_detects_all_patterns(self):
        """sample_input 触发全部 5 种模式。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        patterns = set(output["summary"]["patterns"])
        self.assertEqual(len(patterns), 5)

    def test_pipeline_total_transactions_correct(self):
        """total_transactions = 输入交易数。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        self.assertEqual(
            output["summary"]["total_transactions"],
            len(data["transactions"]),
        )

    def test_pipeline_alerts_non_empty(self):
        """sample_input 含可疑交易 → 告警列表非空。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        self.assertGreater(len(output["alerts"]), 0)

    def test_pipeline_matches_expected_output(self):
        """输出与 expected_output.json 关键字段一致。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        expected = _load_expected_output()
        self.assertEqual(output["summary"]["total_sars"], expected["summary"]["total_sars"])
        self.assertEqual(output["summary"]["total_transactions"], expected["summary"]["total_transactions"])
        self.assertEqual(len(output["alerts"]), len(expected["alerts"]))
        # 第一个告警应为高风险地区（risk_score=90 最高）
        self.assertEqual(output["alerts"][0]["sar_id"], "SAR-HRISK-TX007")
        self.assertEqual(output["alerts"][0]["alert_level"], "critical")

    def test_pipeline_bare_list_input(self):
        """裸 list 输入也可处理。"""
        data = _load_sample_input()
        output = self.pipe.run(data["transactions"])
        self.assertEqual(output["status"], "ok")
        self.assertEqual(
            output["summary"]["total_transactions"],
            len(data["transactions"]),
        )


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_thresholds_alert_levels(self):
        """apply_thresholds 为每个 SAR 添加 alert_level。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        valid_levels = {"critical", "high", "medium", "low"}
        for alert in output["alerts"]:
            self.assertIn(alert["alert_level"], valid_levels)

    def test_alert_levels_summary_consistent(self):
        """alert_levels 汇总 = 各告警分级计数。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        levels = output["summary"]["alert_levels"]
        actual = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for a in output["alerts"]:
            actual[a["alert_level"]] += 1
        self.assertEqual(levels, actual)

    def test_custom_rules_cross_border_escalation(self):
        """高风险地区交易 → cross_border=True + alert_level=critical。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        hrisk = [a for a in output["alerts"] if a["sar_id"] == "SAR-HRISK-TX007"]
        self.assertEqual(len(hrisk), 1)
        self.assertTrue(hrisk[0]["cross_border"])
        self.assertEqual(hrisk[0]["alert_level"], "critical")

    def test_custom_rules_large_amount_review(self):
        """大额交易（total_amount > 50000）→ need_review=True。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        smurf = [a for a in output["alerts"] if "SMURF-C001" in a["sar_id"]]
        self.assertEqual(len(smurf), 1)
        self.assertTrue(smurf[0]["need_review"])

    def test_custom_rules_organized_layering(self):
        """C008 同时命中 Smurfing + Round-trip → organized_layering=True。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        organized = [a for a in output["alerts"] if a["organized_layering"]]
        self.assertGreater(len(organized), 0)
        # C008 的 SAR 应被标记
        c008 = [a for a in output["alerts"] if a["customer_id"] == "C008"]
        for a in c008:
            self.assertTrue(a["organized_layering"])

    def test_rule_adjustments_summary(self):
        """summary 含 rule_adjustments 统计。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        ra = output["summary"]["rule_adjustments"]
        self.assertIn("need_review", ra)
        self.assertIn("cross_border_escalated", ra)
        self.assertIn("organized_layering", ra)
        self.assertGreater(ra["need_review"], 0)
        self.assertGreater(ra["cross_border_escalated"], 0)


class TestPipelineHelpers(unittest.TestCase):
    """pipeline 辅助函数。"""

    def test_parse_amount_string_with_currency(self):
        """金额字符串解析。"""
        self.assertAlmostEqual(_parse_amount("¥50,000"), 50000.0)
        self.assertAlmostEqual(_parse_amount("10万"), 100000.0)
        self.assertAlmostEqual(_parse_amount(50000), 50000.0)

    def test_parse_hour_from_time_string(self):
        """时间字符串解析小时。"""
        self.assertEqual(_parse_hour("14:30:00"), 14)
        self.assertEqual(_parse_hour("02:00"), 2)
        self.assertEqual(_parse_hour(23), 23)
        self.assertEqual(_parse_hour(None), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
