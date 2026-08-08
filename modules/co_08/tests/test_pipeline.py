"""[CO-08] pipeline 单测：端到端 + custom 规则 + PortableDB 持久化。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_08.pipeline import Pipeline
from modules.co_08.custom.custom_rules import apply_custom_rules
from modules.co_08.custom.custom_thresholds import apply_thresholds
from modules.co_08.custom.custom_formatter import format_output

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(tmpdir: str, **overrides) -> Pipeline:
    config = {"db_path": str(Path(tmpdir) / "co_08_pipe.db")}
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
        self.assertEqual(result["module"], "CO-08")

    def test_run_flows_present(self):
        result = self.pipe.run(self.sample)
        self.assertGreaterEqual(len(result["flows"]), 1)
        self.assertGreaterEqual(result["statistics"]["cross_border_count"], 1)

    def test_run_statistics_complete(self):
        result = self.pipe.run(self.sample)
        stats = result["statistics"]
        for key in ("total_entities", "total_flows", "cross_border_count", "by_risk_level", "high_risk_flows"):
            self.assertIn(key, stats)

    def test_run_entities_listed(self):
        result = self.pipe.run(self.sample)
        self.assertGreaterEqual(len(result["entities"]), 3)

    def test_run_empty_input(self):
        result = self.pipe.run({})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["statistics"]["total_flows"], 0)

    def test_collect_chinese_keys(self):
        result = self.pipe._collect({"系统": [], "数据集": [], "位置": [], "流程": []})
        self.assertIn("systems", result)
        self.assertIn("datasets", result)


class TestPipelineCustomRules(unittest.TestCase):
    """custom_rules：业务规则验证。"""

    def test_cross_border_l3_needs_dpa(self):
        result = {
            "cross_border_flows": [
                {"src_id": "a", "dst_id": "b", "sensitive_level": "L3"},
            ],
            "flows": [],
        }
        out = apply_custom_rules(result, {})
        self.assertTrue(out["cross_border_flows"][0]["needs_dpa"])
        self.assertEqual(out["rule_summary"]["needs_dpa_count"], 1)

    def test_l4_upgraded_to_critical(self):
        result = {
            "cross_border_flows": [],
            "flows": [{"risk_score": 50, "risk_level": "medium", "max_sensitive_level": 90}],
        }
        out = apply_custom_rules(result, {})
        self.assertEqual(out["flows"][0]["risk_level"], "critical")
        self.assertEqual(out["rule_summary"]["upgraded_to_critical"], 1)

    def test_excessive_cross_border_alert(self):
        cbs = [{"sensitive_level": "L1"} for _ in range(10)]
        result = {"cross_border_flows": cbs, "flows": []}
        out = apply_custom_rules(result, {"rules": {"max_cross_border": 5}})
        self.assertIn("compliance_alert", out)
        self.assertTrue(out["rule_summary"]["compliance_alert"])


class TestPipelineCustomThresholds(unittest.TestCase):
    """custom_thresholds：阈值分级验证。"""

    def test_threshold_regrades(self):
        result = {
            "flows": [
                {"risk_score": 85, "risk_level": "high"},
                {"risk_score": 50, "risk_level": "low"},
            ],
            "statistics": {},
        }
        out = apply_thresholds(result, {"threshold": {"critical": 80, "high": 60, "medium": 40}})
        self.assertEqual(out["flows"][0]["risk_level"], "critical")
        self.assertEqual(out["flows"][1]["risk_level"], "medium")

    def test_statistics_recalculated(self):
        result = {
            "flows": [
                {"risk_score": 90, "risk_level": "low"},
                {"risk_score": 30, "risk_level": "low"},
            ],
            "statistics": {},
        }
        out = apply_thresholds(result, {})
        self.assertEqual(out["statistics"]["by_risk_level"]["critical"], 1)
        self.assertEqual(out["statistics"]["by_risk_level"]["low"], 1)
        self.assertEqual(out["statistics"]["high_risk_flows"], 1)


class TestPipelinePortableDB(unittest.TestCase):
    """PortableDB 持久化验证。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pipe = _make_pipeline(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_flows_persisted(self):
        self.pipe.run(self.sample)
        rows = self.pipe.engine.db.all("flows")
        self.assertGreaterEqual(len(rows), 1)

    def test_locations_persisted(self):
        self.pipe.run(self.sample)
        rows = self.pipe.engine.db.all("locations")
        self.assertEqual(len(rows), 3)


class TestPipelineFormatter(unittest.TestCase):
    """format_output：输出格式验证。"""

    def test_format_output_structure(self):
        result = {"flows": [], "cross_border_flows": [], "statistics": {}, "entities": {}}
        out = format_output(result)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["module"], "CO-08")
        self.assertIn("flows", out)
        self.assertIn("statistics", out)

    def test_format_output_invalid(self):
        out = format_output("invalid")
        self.assertEqual(out["status"], "error")


if __name__ == "__main__":
    unittest.main()
