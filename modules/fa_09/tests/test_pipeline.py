"""[FA-09] pipeline 端到端单测：Pipeline.run() 全流程 + custom 规则生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_09.pipeline import Pipeline

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
        """输出含 module=FA-09 与 module_name。"""
        output = self.pipe.run(_load_sample())
        self.assertEqual(output["module"], "FA-09")
        self.assertEqual(output["module_name"], "AI底稿质量复核助手")

    def test_pipeline_summary_populated(self):
        """summary 含 total_workpapers / average_score / grade_distribution。"""
        output = self.pipe.run(_load_sample())
        summary = output["summary"]
        for key in ("total_workpapers", "average_score", "grade_distribution"):
            self.assertIn(key, summary)
        self.assertEqual(summary["total_workpapers"], 3)

    def test_pipeline_items_have_grades(self):
        """items 含 grade 与 overall_score。"""
        output = self.pipe.run(_load_sample())
        for item in output["items"]:
            self.assertIn("grade", item)
            self.assertIn("overall_score", item)
            self.assertIn("dimension_scores", item)

    def test_pipeline_improvement_tips(self):
        """improvement_tips 非空。"""
        output = self.pipe.run(_load_sample())
        self.assertGreater(len(output["improvement_tips"]), 0)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_thresholds_pass_rate(self):
        """apply_thresholds 计算 pass_rate。"""
        output = self.pipe.run(_load_sample())
        summary = output["summary"]
        self.assertIn("pass_rate", summary)
        self.assertIn("pass_count", summary)
        # WP1(B) + WP3(B) 通过, WP2(F) 不通过
        self.assertEqual(summary["pass_count"], 2)
        self.assertEqual(summary["fail_count"], 1)

    def test_custom_rule_force_revise(self):
        """WP002 总分 < 60 → force_revise=True。"""
        output = self.pipe.run(_load_sample())
        wp2 = next(i for i in output["items"] if i["wp_id"] == "WP002")
        self.assertTrue(wp2["force_revise"])
        self.assertGreater(output["summary"]["force_revise_count"], 0)

    def test_custom_rule_critical_dimension(self):
        """WP002 有维度 < 50 → has_critical_dimension=True。"""
        output = self.pipe.run(_load_sample())
        wp2 = next(i for i in output["items"] if i["wp_id"] == "WP002")
        self.assertTrue(wp2["has_critical_dimension"])

    def test_custom_rule_escalate(self):
        """WP002 compliance < 50 → escalate=True。"""
        output = self.pipe.run(_load_sample())
        wp2 = next(i for i in output["items"] if i["wp_id"] == "WP002")
        self.assertTrue(wp2["escalate"])


class TestPipelineCollect(unittest.TestCase):
    """_collect 数据归一化。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_chinese_keys(self):
        """中文键 底稿 归一化为 workpapers。"""
        collected = self.pipe._collect({"底稿": [{"id": "WP1", "type": "bank"}]})
        self.assertEqual(len(collected["workpapers"]), 1)

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

    def test_custom_grade_threshold(self):
        """自定义 grade_a 阈值生效。"""
        pipe = Pipeline({"threshold": {"grade_a": 80}})
        sample = _load_sample()
        output = pipe.run(sample)
        # grade_a=80 → WP001(86.5) 和 WP003(82.5) 都为 A
        wp1 = next(i for i in output["items"] if i["wp_id"] == "WP001")
        self.assertEqual(wp1["grade"], "A")


if __name__ == "__main__":
    unittest.main(verbosity=2)
