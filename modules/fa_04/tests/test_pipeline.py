"""[FA-04] pipeline 端到端单测：Pipeline.run() 全流程 + custom 生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from modules.fa_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _hours_ago(hours: float) -> str:
    return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_pipeline_run_with_sample_input(self):
        """sample_input 端到端跑通，输出含 dashboard / confirmations / exceptions。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "FA-04")
        self.assertIn("dashboard", output)
        self.assertIn("confirmations", output)
        self.assertIn("exceptions", output)

    def test_pipeline_dashboard_total(self):
        """dashboard.total 等于输入函证数（8）。"""
        sample = _load_sample_input()
        output = self.pipe.run(sample)
        self.assertEqual(output["dashboard"]["total"], len(sample["confirmations"]))

    def test_pipeline_detects_differences(self):
        """回函差异被识别 → exceptions 非空（3 条）。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(len(output["exceptions"]), 3)
        cids = {e["confirmation_id"] for e in output["exceptions"]}
        self.assertIn("CF-2024-0002", cids)
        self.assertIn("CF-2024-0003", cids)
        self.assertIn("CF-2024-0008", cids)

    def test_pipeline_follow_up_list_populated(self):
        """待回函纳入催函清单（3 条）。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(len(output["follow_up_list"]), 3)
        statuses = {f["status"] for f in output["follow_up_list"]}
        self.assertIn("timeout", statuses)
        self.assertIn("delivered", statuses)
        self.assertIn("draft", statuses)

    def test_pipeline_escalations_recorded(self):
        """超时催函被记录（1 条）。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(len(output["escalations"]), 1)
        self.assertEqual(output["escalations"][0]["confirmation_id"], "CF-2024-0004")

    def test_pipeline_transitions_recorded(self):
        """状态流转被记录（sent→timeout）。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(len(output["transitions"]), 1)
        t = output["transitions"][0]
        self.assertEqual(t["from"], "sent")
        self.assertEqual(t["to"], "timeout")


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_response_rate_below_threshold_triggers_campaign(self):
        """回函率 0.5 < 0.8 → follow_up_campaign=True。"""
        output = self.pipe.run(_load_sample_input())
        self.assertTrue(output["custom_rules"]["follow_up_campaign"])
        self.assertEqual(output["custom_rules"]["response_rate"], 0.5)

    def test_material_diffs_flagged(self):
        """差异金额 > 10000 → 重大差异（2 条）。"""
        output = self.pipe.run(_load_sample_input())
        self.assertEqual(output["custom_rules"]["material_diff_count"], 2)

    def test_grading_applied(self):
        """apply_thresholds 注入 grading（严重度 + 异常等级分布）。"""
        output = self.pipe.run(_load_sample_input())
        grading = output["grading"]
        self.assertIn("severity_distribution", grading)
        self.assertIn("exception_distribution", grading)
        # CF-2024-0004 超期 → critical
        self.assertGreater(grading["severity_distribution"]["critical"], 0)

    def test_overdue_severity_critical_for_old_sent(self):
        """超期函证 overdue_severity=critical。"""
        output = self.pipe.run(_load_sample_input())
        confs = {c["confirmation_id"]: c for c in output["confirmations"]}
        self.assertEqual(confs["CF-2024-0004"]["overdue_severity"], "critical")
        self.assertTrue(confs["CF-2024-0004"]["needs_escalation"])

    def test_exception_level_grading(self):
        """差异异常等级：CF-0003(high) / CF-0002(medium) / CF-0008(low)。"""
        output = self.pipe.run(_load_sample_input())
        confs = {c["confirmation_id"]: c for c in output["confirmations"]}
        self.assertEqual(confs["CF-2024-0003"]["exception_level"], "high")
        self.assertEqual(confs["CF-2024-0002"]["exception_level"], "medium")
        self.assertEqual(confs["CF-2024-0008"]["exception_level"], "low")


class TestPipelineCollect(unittest.TestCase):
    """_collect 输入归一化。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_list_input(self):
        """list 输入包装为 confirmations。"""
        collected = self.pipe._collect([
            {"confirmation_id": "X1", "status": "draft"},
            {"confirmation_id": "X2", "status": "draft"},
        ])
        self.assertEqual(len(collected["confirmations"]), 2)

    def test_collect_single_confirmation(self):
        """单张函证 dict（含 confirmation_id）包装为列表。"""
        collected = self.pipe._collect({"confirmation_id": "X1", "status": "draft"})
        self.assertEqual(len(collected["confirmations"]), 1)

    def test_collect_invalid_raises(self):
        """非法输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.pipe._collect(12345)

    def test_collect_dynamic_input_runs(self):
        """动态构造输入（sent 50h 前超时）端到端跑通。"""
        output = self.pipe.run({"confirmations": [
            {"confirmation_id": "D1", "status": "sent", "sent_at": _hours_ago(50),
             "bank_name": "工行"},
        ]})
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["confirmations"][0]["status"], "timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
