"""[CO-09] engine 单测：隐私政策分类 + 四维合规检查 + 评分分级。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_09.engine import LLMEngine, _split_sentences, _calc_readability

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> LLMEngine:
    config = {"db_path": str(Path(tmpdir) / "co_09_test.db")}
    config.update(overrides)
    eng = LLMEngine(config=config)
    eng.setup()
    return eng


class TestHelperFunctions(unittest.TestCase):
    """辅助函数测试。"""

    def test_split_sentences_chinese(self):
        result = _split_sentences("第一句。第二句！第三句？")
        self.assertGreaterEqual(len(result), 3)

    def test_split_sentences_english(self):
        result = _split_sentences("First. Second! Third?")
        self.assertGreaterEqual(len(result), 3)

    def test_split_sentences_empty(self):
        result = _split_sentences("")
        self.assertEqual(len(result), 1)

    def test_calc_readability_normal(self):
        result = _calc_readability("这是一个正常的句子，长度适中。")
        self.assertIn("avg_sentence_len", result)
        self.assertIn("complexity_score", result)
        self.assertIn("score", result)
        self.assertGreater(result["score"], 0)

    def test_calc_readability_empty(self):
        result = _calc_readability("")
        self.assertEqual(result["score"], 50.0)

    def test_calc_readability_long_sentence(self):
        long_text = "a" * 100 + "。" * 1
        result = _calc_readability(long_text)
        self.assertLess(result["score"], 50)


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB + 类别定义。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_model_loaded(self):
        self.assertIsNotNone(self.engine.model)
        self.assertIn("categories", self.engine.model)
        self.assertIn("misleading_patterns", self.engine.model)

    def test_categories_count(self):
        cats = self.engine.model["categories"]
        self.assertEqual(len(cats), 11)

    def test_db_tables_created(self):
        tables = self.engine.db.tables()
        self.assertIn("policies", tables)
        self.assertIn("findings", tables)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：政策文本清洗。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_returns_list(self):
        prepared = self.engine._preprocess(self.sample)
        self.assertIsInstance(prepared, list)
        self.assertEqual(len(prepared), 2)

    def test_html_removed(self):
        prepared = self.engine._preprocess({"policies": [
            {"policy_id": "T1", "text": "<p>隐私政策</p>"}
        ]})
        self.assertNotIn("<p>", prepared[0]["raw_text"])

    def test_language_default(self):
        prepared = self.engine._preprocess({"policies": [
            {"policy_id": "T1", "text": "some text"}
        ]})
        self.assertEqual(prepared[0]["language"], "zh")

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            self.engine._preprocess("not a dict")


class TestEngineInfer(unittest.TestCase):
    """_infer：四维合规检查。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")
        self.prepared = self.engine._preprocess(self.sample)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_infer_returns_policies(self):
        result = self.engine._infer(self.prepared)
        self.assertIn("policies", result)
        self.assertEqual(len(result["policies"]), 2)

    def test_findings_count(self):
        result = self.engine._infer(self.prepared)
        for p in result["policies"]:
            self.assertEqual(len(p["findings"]), 11)

    def test_dimension_scores(self):
        result = self.engine._infer(self.prepared)
        for p in result["policies"]:
            dims = p["dimension_scores"]
            self.assertIn("completeness", dims)
            self.assertIn("accuracy", dims)
            self.assertIn("clarity", dims)
            self.assertIn("fairness", dims)

    def test_overall_score_range(self):
        result = self.engine._infer(self.prepared)
        for p in result["policies"]:
            score = p["overall_score"]
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)

    def test_grade_values(self):
        result = self.engine._infer(self.prepared)
        valid_grades = {"A", "B", "C", "D", "F"}
        for p in result["policies"]:
            self.assertIn(p["grade"], valid_grades)

    def test_complete_policy_scores_higher(self):
        result = self.engine._infer(self.prepared)
        full = next(p for p in result["policies"] if p["policy_id"] == "POL-001")
        partial = next(p for p in result["policies"] if p["policy_id"] == "POL-002")
        self.assertGreater(full["overall_score"], partial["overall_score"])

    def test_status_values(self):
        result = self.engine._infer(self.prepared)
        valid_statuses = {"compliant", "partial", "weak", "missing"}
        for p in result["policies"]:
            for f in p["findings"]:
                self.assertIn(f["status"], valid_statuses)

    def test_misleading_detected(self):
        result = self.engine._infer(self.prepared)
        partial = next(p for p in result["policies"] if p["policy_id"] == "POL-002")
        # POL-002 has "可能会" and "视情况而定" → should affect fairness
        self.assertLess(partial["dimension_scores"]["fairness"], 100)

    def test_empty_input(self):
        result = self.engine._infer([])
        self.assertEqual(len(result["policies"]), 0)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：持久化 + 摘要。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_summary_generated(self):
        result = self.engine.execute(self.sample)
        summary = result["summary"]
        self.assertIn("total_policies", summary)
        self.assertIn("total_findings", summary)
        self.assertIn("by_status", summary)
        self.assertIn("average_overall_score", summary)
        self.assertIn("policies_by_grade", summary)

    def test_policies_persisted(self):
        result = self.engine.execute(self.sample)
        rows = self.engine.db.all("policies")
        self.assertEqual(len(rows), 2)

    def test_findings_persisted(self):
        result = self.engine.execute(self.sample)
        rows = self.engine.db.all("findings")
        self.assertEqual(len(rows), result["summary"]["total_findings"])


class TestEngineExecute(unittest.TestCase):
    """execute：端到端集成。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_execute_full(self):
        sample = _load_fixture("sample_input.json")
        result = self.engine.execute(sample)
        self.assertIsInstance(result, dict)
        self.assertIn("policies", result)
        self.assertIn("summary", result)

    def test_execute_empty(self):
        result = self.engine.execute({"policies": []})
        self.assertEqual(result["summary"]["total_policies"], 0)

    def test_execute_single_policy(self):
        result = self.engine.execute({"policies": [
            {"policy_id": "X1", "text": "我们收集个人信息。"}
        ]})
        self.assertEqual(len(result["policies"]), 1)


if __name__ == "__main__":
    unittest.main()
