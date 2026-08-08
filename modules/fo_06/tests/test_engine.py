"""[FO-06] engine 单测：实体抽取 + 证据链构建 + 完整度评估。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_06.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> LLMEngine:
    config = {"db_path": str(Path(tmpdir) / "fo_06_test.db")}
    config.update(overrides)
    eng = LLMEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：模型初始化。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_model_loaded(self):
        self.assertIsNotNone(self.engine.model)
        self.assertIn("entity_patterns", self.engine.model)
        self.assertIn("relation_types", self.engine.model)
        self.assertIn("chain_rules", self.engine.model)

    def test_entity_patterns_present(self):
        patterns = self.engine.model["entity_patterns"]
        for etype in ("person", "company", "amount", "date", "location"):
            self.assertIn(etype, patterns)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：证据清洗 + 实体抽取。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_returns_dict(self):
        prepared = self.engine._preprocess(self.sample)
        self.assertIn("evidence", prepared)
        self.assertIn("cases", prepared)
        self.assertEqual(len(prepared["evidence"]), 5)

    def test_entities_extracted(self):
        prepared = self.engine._preprocess(self.sample)
        evd = prepared["evidence"][0]
        self.assertIn("entities", evd)
        self.assertIn("person", evd["entities"])
        self.assertIn("company", evd["entities"])

    def test_evidence_id_generated(self):
        prepared = self.engine._preprocess({"evidence": [{"content": "测试"}]})
        self.assertNotEqual(prepared["evidence"][0]["evidence_id"], "")

    def test_non_dict_raises(self):
        with self.assertRaises(ValueError):
            self.engine._preprocess("invalid")


class TestEngineInfer(unittest.TestCase):
    """_infer：证据链构建 + 关联分析。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")
        self.prepared = self.engine._preprocess(self.sample)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_infer_returns_chains(self):
        result = self.engine._infer(self.prepared)
        self.assertIn("chains", result)
        self.assertEqual(len(result["chains"]), 2)

    def test_chain_structure(self):
        result = self.engine._infer(self.prepared)
        chain = result["chains"][0]
        self.assertIn("case_id", chain)
        self.assertIn("evidence", chain)
        self.assertIn("entities", chain)
        self.assertIn("connections", chain)
        self.assertIn("chain_complete", chain)
        self.assertIn("completeness_score", chain)

    def test_summary_generated(self):
        result = self.engine._infer(self.prepared)
        summary = result["summary"]
        self.assertEqual(summary["total_evidence"], 5)
        self.assertEqual(summary["total_chains"], 2)
        self.assertIn("avg_evidence_per_chain", summary)
        self.assertIn("complete_chains", summary)

    def test_all_entities_merged(self):
        result = self.engine._infer(self.prepared)
        self.assertGreater(len(result["all_entities"]), 0)
        for ent in result["all_entities"].values():
            self.assertIn("entity_type", ent)
            self.assertIn("cases", ent)

    def test_empty_input(self):
        result = self.engine._infer({"evidence": [], "cases": []})
        self.assertEqual(len(result["chains"]), 0)

    def test_auto_case_detection(self):
        """无 cases 时从 evidence 的 case_id 自动构建。"""
        prepared = {"evidence": self.prepared["evidence"], "cases": []}
        result = self.engine._infer(prepared)
        self.assertGreater(len(result["chains"]), 0)


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
        self.assertIn("chains", result)
        self.assertIn("summary", result)
        self.assertIn("chain_quality", result["summary"])

    def test_execute_empty(self):
        result = self.engine.execute({})
        self.assertEqual(result["summary"]["total_evidence"], 0)

    def test_chain_quality_values(self):
        sample = _load_fixture("sample_input.json")
        result = self.engine.execute(sample)
        quality = result["summary"]["chain_quality"]
        self.assertIn(quality, ("优秀", "良好", "待完善"))


if __name__ == "__main__":
    unittest.main()
