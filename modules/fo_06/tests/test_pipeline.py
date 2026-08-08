"""[FO-06] pipeline 单测：端到端 + custom 规则 + 阈值分级。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_06.pipeline import Pipeline
from modules.fo_06.custom.custom_rules import apply_custom_rules
from modules.fo_06.custom.custom_thresholds import apply_thresholds
from modules.fo_06.custom.custom_formatter import format_output

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(tmpdir: str, **overrides) -> Pipeline:
    config = {"db_path": str(Path(tmpdir) / "fo_06_pipe.db")}
    config.update(overrides)
    return Pipeline(config=config)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pipe = _make_pipeline(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_run_returns_dict(self):
        result = self.pipe.run(self.sample)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["module"], "FO-06")

    def test_run_chains_present(self):
        result = self.pipe.run(self.sample)
        self.assertEqual(len(result["chains"]), 2)

    def test_run_summary_complete(self):
        result = self.pipe.run(self.sample)
        summary = result["summary"]
        self.assertIn("total_evidence", summary)
        self.assertIn("total_chains", summary)
        self.assertIn("chain_quality", summary)

    def test_run_empty_input(self):
        result = self.pipe.run({})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["total_evidence"], 0)

    def test_collect_chinese_keys(self):
        collected = self.pipe._collect({"证据": [], "案件": []})
        self.assertIn("evidence", collected)

    def test_chains_have_quality_grade(self):
        result = self.pipe.run(self.sample)
        for c in result["chains"]:
            self.assertIn("quality_grade", c)


class TestPipelineCustomRules(unittest.TestCase):
    """custom_rules：业务规则验证。"""

    def test_critical_gap_alert(self):
        result = {
            "chains": [{
                "completeness_score": 30,
                "missing_elements": ["a", "b", "c"],
                "evidence": [{"id": 1}, {"id": 2}],
            }],
            "all_entities": {},
        }
        out = apply_custom_rules(result, {})
        self.assertEqual(out["chains"][0]["alert"]["type"], "critical_gap")

    def test_insufficient_evidence(self):
        result = {
            "chains": [{"evidence": [{"id": 1}], "completeness_score": 80, "missing_elements": []}],
            "all_entities": {},
        }
        out = apply_custom_rules(result, {})
        self.assertEqual(out["chains"][0]["evidence_alert"]["type"], "insufficient_evidence")

    def test_cross_case_entity(self):
        result = {
            "chains": [],
            "all_entities": {
                "company:X": {"entity_type": "company", "entity_value": "X", "cases": ["C1", "C2"], "evidence_count": 3},
            },
        }
        out = apply_custom_rules(result, {})
        self.assertGreaterEqual(len(out["cross_case_entities"]), 1)


class TestPipelineCustomThresholds(unittest.TestCase):
    """custom_thresholds：阈值分级验证。"""

    def test_threshold_grading(self):
        result = {"chains": [
            {"completeness_score": 90},
            {"completeness_score": 75},
            {"completeness_score": 55},
            {"completeness_score": 30},
        ]}
        out = apply_thresholds(result, {})
        self.assertEqual(out["chains"][0]["quality_grade"], "excellent")
        self.assertEqual(out["chains"][1]["quality_grade"], "good")
        self.assertEqual(out["chains"][2]["quality_grade"], "pass")
        self.assertEqual(out["chains"][3]["quality_grade"], "fail")


class TestPipelineFormatter(unittest.TestCase):
    """format_output：输出格式验证。"""

    def test_format_output_structure(self):
        result = {"chains": [], "summary": {}, "all_entities": {}}
        out = format_output(result)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["module"], "FO-06")

    def test_format_output_invalid(self):
        out = format_output("invalid")
        self.assertEqual(out["status"], "error")


if __name__ == "__main__":
    unittest.main()
