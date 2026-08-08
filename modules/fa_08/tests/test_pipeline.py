"""[FA-08] pipeline 端到端单测：Pipeline.run() 全流程 + custom 规则生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_08.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_pipeline_run_returns_ok(self):
        """Pipeline.run 返回 status=ok。"""
        output = self.pipe.run(_load_sample())
        self.assertEqual(output["status"], "ok")

    def test_pipeline_module_name(self):
        """输出含 module=FA-08 与 module_name。"""
        output = self.pipe.run(_load_sample())
        self.assertEqual(output["module"], "FA-08")
        self.assertEqual(output["module_name"], "底稿自动勾稽检查")

    def test_pipeline_summary_populated(self):
        """summary 含 total_checks / pass_count / fail_count / pass_rate。"""
        output = self.pipe.run(_load_sample())
        summary = output["summary"]
        for key in ("total_checks", "pass_count", "fail_count",
                    "pass_rate", "severity_distribution"):
            self.assertIn(key, summary)
        self.assertGreater(summary["total_checks"], 0)

    def test_pipeline_items_contain_pass_and_fail(self):
        """items 含 PASS 与 FAIL 项。"""
        output = self.pipe.run(_load_sample())
        statuses = {i["status"] for i in output["items"]}
        self.assertIn("PASS", statuses)
        self.assertIn("FAIL", statuses)

    def test_pipeline_critical_issues_present(self):
        """sample 含 high 严重度失败 → critical_issues 非空。"""
        output = self.pipe.run(_load_sample())
        self.assertGreater(len(output["critical_issues"]), 0)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_thresholds_confidence_level(self):
        """apply_thresholds 计算 confidence_level。"""
        output = self.pipe.run(_load_sample())
        self.assertIn("confidence_level", output["summary"])

    def test_custom_rule_partner_review(self):
        """存在 high FAIL → partner_review_required=True。"""
        output = self.pipe.run(_load_sample())
        self.assertTrue(output["summary"]["partner_review_required"])

    def test_custom_rule_escalation(self):
        """总差异金额超阈值 → escalation=True。"""
        output = self.pipe.run(_load_sample())
        # sample 总差异 525000 > 默认 500000 → escalation
        self.assertTrue(output["summary"]["escalation"])

    def test_custom_rule_warning(self):
        """通过率 < 80% → warning=True。"""
        output = self.pipe.run(_load_sample())
        self.assertTrue(output["summary"]["warning"])


class TestPipelineCollect(unittest.TestCase):
    """_collect 数据归一化。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_chinese_keys(self):
        """中文键归一化为英文键。"""
        collected = self.pipe._collect({
            "底稿": [{"id": "WP1"}],
            "报表": {"trial_balance": {"debit": 1, "credit": 1}},
            "凭证": [],
            "指标": [],
        })
        self.assertEqual(len(collected["workpapers"]), 1)
        self.assertIn("trial_balance", collected["statements"])

    def test_collect_list_input(self):
        """list 输入包装为 workpapers。"""
        collected = self.pipe._collect([{"id": "WP1"}, {"id": "WP2"}])
        self.assertEqual(len(collected["workpapers"]), 2)

    def test_collect_none_input(self):
        """None 输入返回空 dict。"""
        collected = self.pipe._collect(None)
        self.assertEqual(collected, {})


class TestPipelineConfigOverride(unittest.TestCase):
    """config 阈值覆盖。"""

    def test_custom_threshold_config(self):
        """自定义 diff_escalate 阈值生效。"""
        pipe = Pipeline({
            "threshold": {"diff_escalate": 10},
        })
        sample = _load_sample()
        output = pipe.run(sample)
        # diff_escalate=10 → 净利润(200000)被升级为 high
        self.assertGreater(output["summary"].get("escalated_count", 0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
