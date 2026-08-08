"""[CO-05] pipeline 端到端单测：Pipeline.run() 全流程。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_05.pipeline import Pipeline

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
        """用 sample_input.json 端到端跑通，输出含检测 + 汇总。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-05")
        self.assertEqual(output["action"], "detect_patterns")
        self.assertIn("detections", output)
        self.assertIn("summary", output)

    def test_pipeline_detects_multiple_patterns(self):
        """sample_input 触发多种模式。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        pids = {d["pattern_id"] for d in output["detections"]}
        self.assertIn("PAT-SMURFING", pids)
        self.assertIn("PAT-MONEY-LOOP", pids)
        self.assertIn("PAT-SHELL-COMPANY", pids)

    def test_pipeline_total_detections_correct(self):
        """total_detections = 检测列表长度。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        self.assertEqual(
            output["summary"]["total_detections"],
            len(output["detections"]),
        )

    def test_pipeline_matches_expected_output(self):
        """输出与 expected_output.json 关键字段一致。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        expected = _load_expected_output()
        self.assertEqual(
            output["summary"]["total_detections"],
            expected["summary"]["total_detections"],
        )
        self.assertEqual(
            output["summary"]["by_severity"],
            expected["summary"]["by_severity"],
        )
        self.assertEqual(
            output["summary"]["by_pattern"],
            expected["summary"]["by_pattern"],
        )

    def test_pipeline_smurfing_organized(self):
        """Smurfing 检测源账户 >= 5 → organized_smurfing=True。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        smurf = [d for d in output["detections"]
                 if d["pattern_id"] == "PAT-SMURFING"]
        self.assertEqual(len(smurf), 1)
        self.assertTrue(smurf[0]["organized_smurfing"])

    def test_pipeline_money_loop_layering(self):
        """Money Loop 检测 → layering_pattern=True。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        loops = [d for d in output["detections"]
                 if d["pattern_id"] == "PAT-MONEY-LOOP"]
        self.assertEqual(len(loops), 1)
        self.assertTrue(loops[0]["layering_pattern"])

    def test_pipeline_shell_company_syndicate(self):
        """Shell Company 节点 >= 4 → suspected_syndicate=True。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        shells = [d for d in output["detections"]
                  if d["pattern_id"] == "PAT-SHELL-COMPANY"]
        self.assertGreaterEqual(len(shells), 1)
        for s in shells:
            self.assertTrue(s["suspected_syndicate"])

    def test_pipeline_risk_grading(self):
        """risk_grading 含 critical/high/medium/low 计数。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        grading = output["summary"]["risk_grading"]
        self.assertIn("critical", grading)
        self.assertIn("high", grading)
        self.assertIn("medium", grading)
        self.assertIn("low", grading)
        total = sum(grading.values())
        self.assertEqual(total, len(output["detections"]))


class TestPipelineActions(unittest.TestCase):
    """不同 action 的 pipeline 行为。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_pipeline_load_graph_action(self):
        """load_graph action → 返回图谱摘要。"""
        output = self.pipe.run({
            "action": "load_graph",
            "nodes": [{"node_id": "A"}, {"node_id": "B"}],
            "edges": [{"src": "A", "dst": "B", "amount": 100}],
        })
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["action"], "load_graph")
        self.assertEqual(output["node_count"], 2)
        self.assertEqual(output["edge_count"], 1)

    def test_pipeline_centrality_action(self):
        """centrality_analysis action → 返回中心性分析。"""
        output = self.pipe.run({
            "action": "centrality_analysis",
            "nodes": [{"node_id": "A"}, {"node_id": "B"}],
            "edges": [{"src": "A", "dst": "B", "amount": 100}],
        })
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["action"], "centrality_analysis")
        self.assertIn("top_pagerank", output)

    def test_pipeline_trace_funds_action(self):
        """trace_funds action → 返回资金流路径。"""
        output = self.pipe.run({
            "action": "trace_funds",
            "nodes": [{"node_id": "A"}, {"node_id": "B"}],
            "edges": [{"src": "A", "dst": "B", "amount": 100}],
            "suspicious_node_ids": ["A"],
        })
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["action"], "trace_funds")
        self.assertIn("paths", output)

    def test_pipeline_graph_field_input(self):
        """graph 字段输入也可处理。"""
        output = self.pipe.run({
            "graph": {
                "nodes": [{"node_id": "A"}, {"node_id": "B"}],
                "edges": [{"src": "A", "dst": "B", "amount": 100}],
            }
        })
        self.assertEqual(output["status"], "ok")


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_thresholds_risk_grade_added(self):
        """apply_thresholds 为每个检测添加 risk_grade。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        valid_grades = {"critical", "high", "medium", "low"}
        for d in output["detections"]:
            self.assertIn(d["risk_grade"], valid_grades)

    def test_rule_adjustments_summary(self):
        """summary 含 rule_adjustments 统计。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        ra = output["summary"]["rule_adjustments"]
        self.assertIn("layering_pattern", ra)
        self.assertIn("organized_smurfing", ra)
        self.assertIn("suspected_syndicate", ra)
        self.assertGreater(ra["layering_pattern"], 0)
        self.assertGreater(ra["organized_smurfing"], 0)
        self.assertGreater(ra["suspected_syndicate"], 0)

    def test_money_loop_critical_grade(self):
        """Money Loop (high + confidence >= 0.85) → risk_grade=critical。"""
        data = _load_sample_input()
        output = self.pipe.run(data)
        loops = [d for d in output["detections"]
                 if d["pattern_id"] == "PAT-MONEY-LOOP"]
        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0]["risk_grade"], "critical")


if __name__ == "__main__":
    unittest.main(verbosity=2)
