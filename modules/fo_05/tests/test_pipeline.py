"""[FO-05] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_05.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class _PipelineTestBase(unittest.TestCase):
    """公共 setUp/tearDown：管理 tmpdir + pipeline 生命周期。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._pipes: list[Pipeline] = []

    def tearDown(self):
        for p in self._pipes:
            try:
                p.close()
            except Exception:
                pass
        self._pipes.clear()
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass

    def _make_pipeline(self, **overrides) -> Pipeline:
        config = {
            "db_path": str(Path(self.tmpdir.name) / "fo_05_pipeline.db"),
        }
        config.update(overrides)
        pipe = Pipeline(config=config)
        self._pipes.append(pipe)
        return pipe

    def _load_sample(self) -> dict:
        return _load_sample_input()


class TestPipelineEndToEnd(_PipelineTestBase):
    """端到端跑通。"""

    def test_pipeline_run_with_sample_input(self):
        """用 sample_input.json 端到端跑通。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "FO-05")
        self.assertIn("translations", output)
        self.assertIn("quality_assessment", output)
        self.assertIn("alerts", output)
        self.assertIn("statistics", output)

    def test_pipeline_translations_count_matches_input(self):
        """翻译条数与输入 texts 数量一致。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertEqual(
            len(output["translations"]), len(sample["texts"])
        )

    def test_pipeline_statistics_complete(self):
        """统计含 text_count / language_distribution / code_switch_count。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        stats = output["statistics"]
        self.assertEqual(stats["text_count"], len(sample["texts"]))
        self.assertIn("language_distribution", stats)
        self.assertIn("code_switch_count", stats)
        self.assertIn("total_legal_terms", stats)
        self.assertIn("alert_count", stats)

    def test_pipeline_quality_assessment_populated(self):
        """质量评估含 avg_confidence / quality_level / quality_distribution。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        qa = output["quality_assessment"]
        self.assertIn("avg_confidence", qa)
        self.assertIn("quality_level", qa)
        self.assertIn("quality_distribution", qa)
        self.assertIn(qa["quality_level"], ("high", "medium", "low"))
        self.assertGreaterEqual(qa["avg_confidence"], 0.0)
        self.assertLessEqual(qa["avg_confidence"], 1.0)

    def test_pipeline_code_switch_detected(self):
        """sample_input TXT-003 含中英混用 → code_switch_count >= 1。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertGreaterEqual(output["statistics"]["code_switch_count"], 1)
        switched = [t for t in output["translations"] if t["code_switch_detected"]]
        self.assertGreater(len(switched), 0)

    def test_pipeline_legal_terms_extracted(self):
        """sample_input 含法律术语 → total_legal_terms > 0。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertGreater(output["statistics"]["total_legal_terms"], 0)
        terms_found = [
            t for t in output["translations"] if t["legal_terms_found"]
        ]
        self.assertGreater(len(terms_found), 0)

    def test_pipeline_each_translation_has_fields(self):
        """每条翻译含必需字段。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        for t in output["translations"]:
            self.assertIn("text_id", t)
            self.assertIn("detected_language", t)
            self.assertIn("translated_text", t)
            self.assertIn("translation_confidence", t)
            self.assertIn("quality_level", t)
            self.assertIn("sentiment", t)
            self.assertIn("legal_terms_found", t)
            self.assertIn("code_switch_detected", t)
            self.assertIn("needs_review", t)
            self.assertIn("escalate", t)

    def test_pipeline_empty_input(self):
        """空输入 → 0 texts，不报错。"""
        pipe = self._make_pipeline()
        output = pipe.run({"texts": []})

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["statistics"]["text_count"], 0)
        self.assertEqual(len(output["translations"]), 0)


class TestPipelinePortableDB(_PipelineTestBase):
    """PortableDB 持久化。"""

    def test_pipeline_creates_tables(self):
        """Pipeline 初始化后 PortableDB 含 source_texts / analysis_results 表。"""
        db_path = Path(self.tmpdir.name) / "fo_05_pipeline.db"
        self._make_pipeline()
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        self.assertIn("source_texts", tables)
        self.assertIn("analysis_results", tables)

    def test_pipeline_persists_source_texts(self):
        """Pipeline 把原始文本持久化到 source_texts 表。"""
        db_path = Path(self.tmpdir.name) / "fo_05_pipeline.db"
        pipe = self._make_pipeline()
        sample = self._load_sample()
        pipe.run(sample)

        with PortableDB(db_path) as db:
            count = db.count("source_texts")
        self.assertEqual(count, len(sample["texts"]))

    def test_pipeline_persists_analysis_results(self):
        """Pipeline 把分析结果持久化到 analysis_results 表。"""
        db_path = Path(self.tmpdir.name) / "fo_05_pipeline.db"
        pipe = self._make_pipeline()
        sample = self._load_sample()
        pipe.run(sample)

        with PortableDB(db_path) as db:
            count = db.count("analysis_results")
        self.assertEqual(count, len(sample["texts"]))

    def test_pipeline_analysis_results_have_quality(self):
        """analysis_results 含 quality_level / translation_confidence。"""
        db_path = Path(self.tmpdir.name) / "fo_05_pipeline.db"
        pipe = self._make_pipeline()
        sample = self._load_sample()
        pipe.run(sample)

        with PortableDB(db_path) as db:
            rows = db.all("analysis_results")
        for r in rows:
            self.assertTrue(r["text_id"])
            self.assertIn(r["quality_level"], ("high", "medium", "low"))
            self.assertGreaterEqual(r["translation_confidence"], 0.0)


class TestPipelineCustomization(_PipelineTestBase):
    """custom_thresholds + custom_rules 生效。"""

    def test_thresholds_quality_distribution(self):
        """apply_thresholds 生成 quality_distribution 统计。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        dist = output["quality_assessment"]["quality_distribution"]
        self.assertIn("high", dist)
        self.assertIn("medium", dist)
        self.assertIn("low", dist)
        total = dist["high"] + dist["medium"] + dist["low"]
        self.assertEqual(total, len(sample["texts"]))

    def test_custom_rules_low_confidence_alert(self):
        """高 review_threshold → 低置信度翻译触发 low_confidence 告警。"""
        pipe = self._make_pipeline(rules={"review_threshold": 0.95})
        sample = self._load_sample()
        output = pipe.run(sample)

        low_conf = [
            a for a in output["alerts"] if a["type"] == "low_confidence"
        ]
        self.assertGreater(len(low_conf), 0)
        self.assertGreater(output["statistics"]["needs_review_count"], 0)

    def test_custom_rules_terminology_alert(self):
        """expected_terms 未命中 → terminology_alert。"""
        pipe = self._make_pipeline(
            rules={"expected_terms": [" nonexistent_term "]}
        )
        sample = self._load_sample()
        output = pipe.run(sample)

        term_alerts = [
            a for a in output["alerts"] if a["type"] == "terminology_alert"
        ]
        self.assertGreater(len(term_alerts), 0)
        self.assertGreater(output["statistics"]["terminology_alerts"], 0)

    def test_custom_rules_unsupported_language_escalate(self):
        """检测到不支持的语言 → escalate。"""
        pipe = self._make_pipeline(
            rules={"supported_languages": ["zh"]}
        )
        sample = self._load_sample()
        output = pipe.run(sample)

        escalate_alerts = [
            a for a in output["alerts"] if a["type"] == "unsupported_language"
        ]
        self.assertGreater(len(escalate_alerts), 0)
        escalated = [t for t in output["translations"] if t["escalate"]]
        self.assertGreater(len(escalated), 0)

    def test_statistics_alert_count_consistent(self):
        """统计的 alert_count 与 alerts 列表长度一致。"""
        pipe = self._make_pipeline(rules={"review_threshold": 0.95})
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertEqual(
            output["statistics"]["alert_count"],
            len(output["alerts"]),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
