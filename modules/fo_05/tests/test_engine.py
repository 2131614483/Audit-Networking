"""[FO-05] engine 单测：语言检测 / 翻译 / 情感分析 / 术语抽取 / 代码切换。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_05.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> LLMEngine:
    config = {"db_path": str(Path(tmpdir) / "fo_05_test.db")}
    config.update(overrides)
    eng = LLMEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_model_has_language_indicators(self):
        self.assertIn("language_indicators", self.engine.model)
        self.assertIn("zh", self.engine.model["language_indicators"])
        self.assertIn("en", self.engine.model["language_indicators"])

    def test_model_has_legal_terms(self):
        self.assertIn("legal_terms_zh_en", self.engine.model)
        terms = self.engine.model["legal_terms_zh_en"]
        self.assertIn("合同", terms)
        self.assertEqual(terms["合同"], "contract")

    def test_model_has_sentiment_lexicon(self):
        self.assertIn("sentiment_lexicon", self.engine.model)
        self.assertIn("positive", self.engine.model["sentiment_lexicon"])
        self.assertIn("negative", self.engine.model["sentiment_lexicon"])

    def test_db_initialized(self):
        self.assertIsNotNone(self.engine.db)


class TestEngineLanguageDetection(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_detect_chinese(self):
        self.assertEqual(self.engine._detect_language("这是一段中文文本"), "zh")

    def test_detect_english(self):
        self.assertEqual(self.engine._detect_language("This is English text"), "en")

    def test_detect_empty_text(self):
        self.assertEqual(self.engine._detect_language(""), "unknown")

    def test_detect_whitespace_only(self):
        self.assertEqual(self.engine._detect_language("   "), "unknown")

    def test_detect_mixed_returns_dominant(self):
        lang = self.engine._detect_language("这是中文内容 with some english")
        self.assertIn(lang, ("zh", "en"))


class TestEngineTranslation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_translate_zh_to_en_replaces_terms(self):
        result = self.engine._translate("合同违约", "zh", "en")
        self.assertIn("[contract]", result)
        self.assertIn("[breach]", result)

    def test_translate_en_to_zh_replaces_terms(self):
        result = self.engine._translate("contract breach", "en", "zh")
        self.assertIn("[合同]", result)
        self.assertIn("[违约]", result)

    def test_translate_same_lang_no_change(self):
        result = self.engine._translate("合同内容", "zh", "zh")
        self.assertEqual(result, "合同内容")

    def test_translate_unsupported_lang_no_change(self):
        result = self.engine._translate("こんにちは", "ja", "ko")
        self.assertEqual(result, "こんにちは")


class TestEngineSentiment(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_sentiment_positive(self):
        result = self.engine._analyze_sentiment("同意接受批准成功完成")
        self.assertEqual(result["label"], "正面")
        self.assertGreater(result["score"], 0)

    def test_sentiment_negative(self):
        result = self.engine._analyze_sentiment("违约争议终止取消违反")
        self.assertEqual(result["label"], "负面")
        self.assertLess(result["score"], 0)

    def test_sentiment_neutral(self):
        result = self.engine._analyze_sentiment("今天天气不错")
        self.assertEqual(result["label"], "中性")
        self.assertEqual(result["score"], 0.0)

    def test_sentiment_returns_counts(self):
        result = self.engine._analyze_sentiment("同意违约")
        self.assertGreater(result["positive_hits"], 0)
        self.assertGreater(result["negative_hits"], 0)


class TestEngineLegalTerms(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_extract_legal_terms_zh(self):
        terms = self.engine._extract_legal_terms("合同违约赔偿")
        zh_terms = {t["zh"] for t in terms}
        self.assertIn("合同", zh_terms)
        self.assertIn("违约", zh_terms)
        self.assertIn("赔偿", zh_terms)

    def test_extract_legal_terms_en(self):
        terms = self.engine._extract_legal_terms("contract breach compensation")
        en_terms = {t["en"] for t in terms}
        self.assertIn("contract", en_terms)
        self.assertIn("breach", en_terms)

    def test_extract_no_terms(self):
        terms = self.engine._extract_legal_terms("今天天气真好")
        self.assertEqual(len(terms), 0)

    def test_extract_terms_have_count(self):
        terms = self.engine._extract_legal_terms("合同合同合同")
        for t in terms:
            if t["zh"] == "合同":
                self.assertEqual(t["count"], 3)


class TestEngineCodeSwitch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_code_switch_detected_mixed(self):
        self.assertTrue(self.engine._detect_code_switch("这是中文 with english"))

    def test_no_code_switch_pure_zh(self):
        self.assertFalse(self.engine._detect_code_switch("这是纯中文文本"))

    def test_no_code_switch_pure_en(self):
        self.assertFalse(self.engine._detect_code_switch("pure english text"))

    def test_no_code_switch_empty(self):
        self.assertFalse(self.engine._detect_code_switch(""))


class TestEngineInfer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_infer_returns_translations(self):
        prepared = self.engine._preprocess(self.sample)
        result = self.engine._infer(prepared)
        self.assertEqual(
            len(result["translations"]), len(self.sample["texts"])
        )

    def test_infer_summary_stats(self):
        prepared = self.engine._preprocess(self.sample)
        result = self.engine._infer(prepared)
        summary = result["summary"]
        self.assertEqual(summary["text_count"], len(self.sample["texts"]))
        self.assertIn("language_distribution", summary)

    def test_infer_language_distribution(self):
        prepared = self.engine._preprocess(self.sample)
        result = self.engine._infer(prepared)
        dist = result["summary"]["language_distribution"]
        self.assertIn("zh", dist)

    def test_infer_code_switch_count(self):
        prepared = self.engine._preprocess(self.sample)
        result = self.engine._infer(prepared)
        self.assertGreaterEqual(result["summary"]["code_switch_count"], 1)

    def test_infer_total_legal_terms(self):
        prepared = self.engine._preprocess(self.sample)
        result = self.engine._infer(prepared)
        self.assertGreater(result["summary"]["total_legal_terms"], 0)

    def test_infer_each_translation_has_fields(self):
        prepared = self.engine._preprocess(self.sample)
        result = self.engine._infer(prepared)
        for t in result["translations"]:
            self.assertIn("detected_language", t)
            self.assertIn("translated_text", t)
            self.assertIn("sentiment", t)
            self.assertIn("legal_terms_found", t)
            self.assertIn("code_switch_detected", t)


class TestEnginePostprocess(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_postprocess_adds_overall_sentiment(self):
        result = self.engine.execute(self.sample)
        self.assertIn("overall_sentiment", result["summary"])

    def test_postprocess_overall_sentiment_value(self):
        result = self.engine.execute(self.sample)
        self.assertIn(
            result["summary"]["overall_sentiment"], ("正面", "负面", "中性")
        )


class TestEngineEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_texts(self):
        result = self.engine.execute({"texts": []})
        self.assertEqual(result["summary"]["text_count"], 0)

    def test_non_dict_input_raises(self):
        with self.assertRaises(ValueError):
            self.engine.execute("not a dict")

    def test_missing_texts_key(self):
        result = self.engine.execute({})
        self.assertEqual(result["summary"]["text_count"], 0)

    def test_text_with_empty_content(self):
        result = self.engine.execute({
            "texts": [{"text_id": "T1", "content": ""}],
        })
        self.assertEqual(
            result["translations"][0]["detected_language"], "unknown"
        )


class TestEngineEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_execute_full_flow(self):
        result = self.engine.execute(self.sample)
        self.assertIn("translations", result)
        self.assertIn("summary", result)
        self.assertIn("overall_sentiment", result["summary"])

    def test_execute_translations_count_matches_input(self):
        result = self.engine.execute(self.sample)
        self.assertEqual(
            len(result["translations"]), len(self.sample["texts"])
        )

    def test_execute_text_id_preserved(self):
        result = self.engine.execute(self.sample)
        input_ids = {t["text_id"] for t in self.sample["texts"]}
        output_ids = {t["text_id"] for t in result["translations"]}
        self.assertEqual(input_ids, output_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)
