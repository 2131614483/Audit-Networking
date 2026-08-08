"""[CO-09] pipeline 单测：端到端 + custom 规则 + 阈值分级 + 持久化。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_09.pipeline import Pipeline
from modules.co_09.custom.custom_rules import apply_custom_rules
from modules.co_09.custom.custom_thresholds import apply_thresholds
from modules.co_09.custom.custom_formatter import format_output

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(tmpdir: str, **overrides) -> Pipeline:
    config = {"db_path": str(Path(tmpdir) / "co_09_pipe.db")}
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
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["module"], "CO-09")

    def test_run_policies_present(self):
        result = self.pipe.run(self.sample)
        self.assertEqual(len(result["policies"]), 2)

    def test_run_summary_complete(self):
        result = self.pipe.run(self.sample)
        summary = result["summary"]
        self.assertIn("total_policies", summary)
        self.assertIn("compliance_levels", summary)
        self.assertIn("violations", summary)

    def test_run_gap_analysis(self):
        result = self.pipe.run(self.sample)
        self.assertIn("gap_analysis", result)
        self.assertIn("missing_categories", result["gap_analysis"])

    def test_run_remediation_plan(self):
        result = self.pipe.run(self.sample)
        self.assertIn("remediation_plan", result)
        self.assertGreaterEqual(len(result["remediation_plan"]), 1)

    def test_run_empty_input(self):
        result = self.pipe.run({"policies": []})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["total_policies"], 0)

    def test_collect_list_input(self):
        collected = self.pipe._collect([{"policy_id": "T1", "text": "test"}])
        self.assertIn("policies", collected)

    def test_collect_alias_keys(self):
        collected = self.pipe._collect({"privacy_policies": [{"text": "test"}]})
        self.assertIn("policies", collected)


class TestPipelineCustomRules(unittest.TestCase):
    """custom_rules：违规标记验证。"""

    def test_legal_basis_missing_violation(self):
        result = {
            "policies": [{
                "policy_id": "P1",
                "findings": [
                    {"category_id": "legal_basis", "status": "missing", "score": 0,
                     "category_name": "法律依据", "legal_refs": {}},
                ],
            }],
            "summary": {},
        }
        out = apply_custom_rules(result, {})
        self.assertGreaterEqual(out["policies"][0]["violation_count"], 1)
        self.assertEqual(out["policies"][0]["violations"][0]["severity"], "critical")
        self.assertEqual(out["policies"][0]["compliance_level"], "non_compliant")

    def test_security_weak_violation(self):
        result = {
            "policies": [{
                "policy_id": "P1",
                "findings": [
                    {"category_id": "security", "status": "weak", "score": 25,
                     "category_name": "安全措施", "legal_refs": {}},
                ],
            }],
            "summary": {},
        }
        out = apply_custom_rules(result, {})
        self.assertGreaterEqual(out["policies"][0]["violation_count"], 1)

    def test_compliant_no_violation(self):
        result = {
            "policies": [{
                "policy_id": "P1",
                "findings": [
                    {"category_id": "legal_basis", "status": "compliant", "score": 90,
                     "category_name": "法律依据", "legal_refs": {}},
                ],
            }],
            "summary": {},
        }
        out = apply_custom_rules(result, {})
        self.assertEqual(out["policies"][0]["violation_count"], 0)

    def test_disabled_rule(self):
        result = {
            "policies": [{
                "policy_id": "P1",
                "findings": [
                    {"category_id": "legal_basis", "status": "missing", "score": 0,
                     "category_name": "法律依据", "legal_refs": {}},
                ],
            }],
            "summary": {},
        }
        out = apply_custom_rules(result, {"rules": {"disabled": ["legal_basis"]}})
        self.assertEqual(out["policies"][0]["violation_count"], 0)


class TestPipelineCustomThresholds(unittest.TestCase):
    """custom_thresholds：阈值分级验证。"""

    def test_threshold_grading(self):
        result = {
            "policies": [
                {"overall_score": 85},
                {"overall_score": 60},
                {"overall_score": 30},
            ],
            "summary": {},
        }
        out = apply_thresholds(result, {})
        self.assertEqual(out["policies"][0]["compliance_level"], "compliant")
        self.assertEqual(out["policies"][1]["compliance_level"], "partial")
        self.assertEqual(out["policies"][2]["compliance_level"], "non_compliant")

    def test_custom_thresholds(self):
        result = {
            "policies": [{"overall_score": 70}],
            "summary": {},
        }
        out = apply_thresholds(result, {"threshold": {"compliant": 90, "partial": 50}})
        self.assertEqual(out["policies"][0]["compliance_level"], "partial")


class TestPipelinePortableDB(unittest.TestCase):
    """PortableDB 持久化。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pipe = _make_pipeline(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_policies_persisted(self):
        self.pipe.run(self.sample)
        rows = self.pipe.engine.db.all("policies")
        self.assertEqual(len(rows), 2)

    def test_findings_persisted(self):
        self.pipe.run(self.sample)
        rows = self.pipe.engine.db.all("findings")
        self.assertGreaterEqual(len(rows), 11)


class TestPipelineFormatter(unittest.TestCase):
    """format_output：输出格式验证。"""

    def test_format_output_structure(self):
        result = {"policies": [], "summary": {}}
        out = format_output(result)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["module"], "CO-09")
        self.assertIn("gap_analysis", out)
        self.assertIn("remediation_plan", out)

    def test_format_output_invalid(self):
        out = format_output("invalid")
        self.assertEqual(out["status"], "error")


if __name__ == "__main__":
    unittest.main()
