"""[ES-01] pipeline 端到端单测：Pipeline.run() 全流程 + 定制化生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.es_01.pipeline import Pipeline
from modules.es_01.custom.custom_thresholds import apply_thresholds
from modules.es_01.custom.custom_rules import apply_custom_rules

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(**overrides) -> Pipeline:
    """构造 pipeline。"""
    config = {"threshold": {"confidence": 0.85}}
    config.update(overrides)
    return Pipeline(config=config)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.sample = _load_sample_input()

    def test_pipeline_run_ok(self):
        """端到端跑通，输出 status=ok / module=ES-01。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "ES-01")

    def test_pipeline_data_catalog_complete(self):
        """data_catalog 含 8 个融合指标（覆盖全部 GRI 指标）。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        self.assertEqual(len(output["data_catalog"]), 8)
        keys = {m["metric_key"] for m in output["data_catalog"]}
        self.assertIn("GHG_Emissions", keys)
        self.assertIn("Board_Independence", keys)

    def test_pipeline_quality_assessment(self):
        """质量评估含 overall / confidence_level / issues。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        qa = output["quality_assessment"]
        self.assertIn("overall", qa)
        self.assertIn("confidence_level", qa)
        self.assertIn("issues", qa)
        self.assertGreater(qa["overall"], 0.0)
        self.assertIn(qa["confidence_level"], ("high", "medium", "low"))

    def test_pipeline_dimension_summary(self):
        """维度摘要含 E/S/G 三维度。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        dim = output["dimension_summary"]
        self.assertIn("E", dim)
        self.assertIn("S", dim)
        self.assertIn("G", dim)
        self.assertEqual(dim["E"]["count"], 4)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.sample = _load_sample_input()

    def test_thresholds_confidence_grade(self):
        """apply_thresholds 为每个指标打 confidence_grade。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        for m in output["data_catalog"]:
            self.assertIn(m["confidence_grade"], ("high", "medium", "low"))
        # GHG 来自低可信度+冲突源 → 低分级
        ghg = next(m for m in output["data_catalog"]
                   if m["metric_key"] == "GHG_Emissions")
        self.assertEqual(ghg["confidence_grade"], "low")

    def test_custom_rules_verification_flag(self):
        """GHG 含新闻媒体（低可信度）→ verification_flag=True。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        ghg = next(m for m in output["data_catalog"]
                   if m["metric_key"] == "GHG_Emissions")
        self.assertTrue(ghg["verification_flag"])
        self.assertIn("新闻媒体", ghg["low_credibility_sources"])
        alerts = output["rule_alerts"]
        self.assertGreater(alerts["verification_flag_count"], 0)

    def test_custom_rules_conflict_alert(self):
        """GHG 多源冲突 → conflict_alert=True。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        ghg = next(m for m in output["data_catalog"]
                   if m["metric_key"] == "GHG_Emissions")
        self.assertTrue(ghg["conflict_alert"])
        alerts = output["rule_alerts"]
        self.assertGreater(alerts["conflict_alert_count"], 0)

    def test_custom_rules_data_gaps_empty(self):
        """全指标采集 → data_gaps 为空。"""
        pipe = _make_pipeline()
        output = pipe.run(self.sample)
        self.assertEqual(len(output["data_gaps"]), 0)
        self.assertEqual(output["rule_alerts"]["data_gap_count"], 0)

    def test_custom_rules_data_gaps_when_missing(self):
        """仅采集部分指标 → data_gaps 含缺失指标。"""
        pipe = _make_pipeline()
        partial = {"data_sources": self.sample["data_sources"][:1]}  # 仅 GHG
        output = pipe.run(partial)
        self.assertGreater(len(output["data_gaps"]), 0)
        gap_keys = {g["metric_key"] for g in output["data_gaps"]}
        self.assertIn("Board_Independence", gap_keys)


class TestPipelineCollect(unittest.TestCase):
    """_collect 数据采集规整。"""

    def test_collect_extracts_data_sources(self):
        """{"data_sources":[...]} → 抽取列表。"""
        pipe = _make_pipeline()
        collected = pipe._collect({"data_sources": [
            {"source": "政府平台", "metric_key": "GHG_Emissions", "content": {"value": 1}},
        ]})
        self.assertEqual(len(collected), 1)

    def test_collect_accepts_bare_list(self):
        """裸 list 输入可直接采集。"""
        pipe = _make_pipeline()
        collected = pipe._collect([
            {"source": "政府平台", "metric_key": "GHG_Emissions", "content": {"value": 1}},
        ])
        self.assertEqual(len(collected), 1)

    def test_collect_fills_defaults(self):
        """缺省字段被补全（data_type/source/period）。"""
        pipe = _make_pipeline()
        collected = pipe._collect([{"content": {"value": 1}, "metric_key": "GHG_Emissions"}])
        self.assertEqual(collected[0]["data_type"], "structured")
        self.assertEqual(collected[0]["source"], "未知")


class TestPipelineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def test_empty_input(self):
        """空输入 → 空数据目录 + overall=0。"""
        pipe = _make_pipeline()
        output = pipe.run({"data_sources": []})
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["data_catalog"], [])
        self.assertEqual(output["quality_assessment"]["overall"], 0)

    def test_collection_log_recorded(self):
        """采集日志含 total_records 与 errors。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        log = output["collection_log"]
        self.assertIn("total_records", log)
        self.assertIn("errors", log)
        self.assertGreater(log["total_records"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
