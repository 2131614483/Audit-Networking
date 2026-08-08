"""[CO-07] engine 单测：资产发现 / PII 检测 / 模式匹配 / 关键词分类 / 敏感度分级。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_07.engine import (
    MLEngine,
    _luhn_check,
    _validate_chinese_id,
    _validate_email,
    _validate_ipv4,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {"db_path": str(Path(tmpdir) / "co_07_test.db")}
    config.update(overrides)
    eng = MLEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + 模式/词典/分级加载。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_db_has_two_tables(self):
        """PortableDB 含 assets / fields 两张表。"""
        tables = set(self.engine.db.tables())
        self.assertIn("assets", tables)
        self.assertIn("fields", tables)

    def test_patterns_loaded(self):
        """加载 9 条敏感数据模式规则。"""
        patterns = self.engine.model["patterns"]
        self.assertEqual(len(patterns), 9)
        names = {p[0] for p in patterns}
        for n in ("chinese_id", "credit_card", "email", "phone",
                  "bank_account", "ssn", "passport", "ip_address", "uk_ni"):
            self.assertIn(n, names)

    def test_field_keywords_loaded(self):
        """字段名关键词词典含 9 类敏感类型。"""
        kw = self.engine.model["field_keywords"]
        for t in ("pii", "phone", "email", "finance", "credit_card",
                  "health", "hr", "business_secret", "contract"):
            self.assertIn(t, kw)
            self.assertIn("zh", kw[t])
            self.assertIn("en", kw[t])

    def test_level_definitions_loaded(self):
        """五级分类定义 L0-L4 全部加载。"""
        defs = self.engine.model["level_definitions"]
        for level in ("L0", "L1", "L2", "L3", "L4"):
            self.assertIn(level, defs)
        self.assertEqual(defs["L4"]["name"], "受限 Restricted")
        self.assertIn("pii", defs["L4"]["sensitive_types"])
        self.assertIn("finance", defs["L3"]["sensitive_types"])


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入校验 + 字段清洗。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_validates_input_type(self):
        """非 dict 输入 → ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess("not a dict")

    def test_preprocess_cleans_fields(self):
        """预处理：字段名/数据类型/样本值归一化。"""
        prepared = self.engine._preprocess({"assets": [{
            "asset_id": "A1",
            "name": "测试表",
            "fields": [
                {"field_name": "身份证号", "data_type": "VARCHAR",
                 "sample_values": ["110101199003071233"]},
            ],
        }]})
        asset = prepared[0]
        self.assertEqual(asset["asset_id"], "A1")
        self.assertEqual(asset["name"], "测试表")
        self.assertEqual(asset["source_type"], "unknown")
        field = asset["fields"][0]
        self.assertEqual(field["field_name"], "身份证号")
        self.assertEqual(field["data_type"], "VARCHAR")
        self.assertEqual(field["sample_values"], ["110101199003071233"])

    def test_preprocess_handles_aliases(self):
        """别名键：id→asset_id, name→field_name, source→source_type。"""
        prepared = self.engine._preprocess({"assets": [{
            "id": "X1",
            "source": "DATABASE",
            "format": "STRUCTURED",
            "fields": [{"name": "邮箱", "type": "TEXT", "samples": ["a@b.com"]}],
        }]})
        asset = prepared[0]
        self.assertEqual(asset["asset_id"], "X1")
        self.assertEqual(asset["source_type"], "database")
        self.assertEqual(asset["format_type"], "structured")
        self.assertEqual(asset["fields"][0]["field_name"], "邮箱")
        self.assertEqual(asset["fields"][0]["sample_values"], ["a@b.com"])


class TestEngineValidators(unittest.TestCase):
    """校验函数：Luhn / 中国身份证 / 邮箱 / IPv4。"""

    def test_luhn_valid_card(self):
        self.assertTrue(_luhn_check("4111111111111111"))

    def test_luhn_invalid_card(self):
        self.assertFalse(_luhn_check("4111111111111112"))

    def test_chinese_id_valid(self):
        self.assertTrue(_validate_chinese_id("110101199003071233"))

    def test_chinese_id_invalid_checksum(self):
        self.assertFalse(_validate_chinese_id("110101199003071234"))

    def test_email_valid(self):
        self.assertTrue(_validate_email("test@example.com"))

    def test_email_invalid(self):
        self.assertFalse(_validate_email("not-an-email"))

    def test_ipv4_valid(self):
        self.assertTrue(_validate_ipv4("192.168.1.1"))

    def test_ipv4_invalid(self):
        self.assertFalse(_validate_ipv4("999.999.999.999"))


class TestEnginePatternMatching(unittest.TestCase):
    """_match_patterns：正则模式匹配 + 校验函数。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.patterns = self.engine.model["patterns"]

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_chinese_id_detected(self):
        """有效身份证号 → chinese_id 命中。"""
        hits = self.engine._match_patterns(
            ["110101199003071233"], self.patterns
        )
        self.assertIn("chinese_id", hits)

    def test_credit_card_valid_luhn(self):
        """Luhn 合法信用卡号 → credit_card 命中。"""
        hits = self.engine._match_patterns(
            ["4111111111111111"], self.patterns
        )
        self.assertIn("credit_card", hits)

    def test_credit_card_invalid_luhn(self):
        """Luhn 非法信用卡号 → credit_card 不命中。"""
        hits = self.engine._match_patterns(
            ["4111111111111112"], self.patterns
        )
        self.assertNotIn("credit_card", hits)

    def test_email_detected(self):
        """邮箱地址 → email 命中。"""
        hits = self.engine._match_patterns(
            ["test@example.com"], self.patterns
        )
        self.assertIn("email", hits)

    def test_phone_detected(self):
        """电话号码 → phone 命中。"""
        hits = self.engine._match_patterns(
            ["13800138000"], self.patterns
        )
        self.assertIn("phone", hits)

    def test_bank_account_detected(self):
        """银行账号（12-22 位数字）→ bank_account 命中。"""
        hits = self.engine._match_patterns(
            ["6222020200112345678"], self.patterns
        )
        self.assertIn("bank_account", hits)


class TestEngineKeywordMatching(unittest.TestCase):
    """_match_field_keywords：中英双语字段名关键词匹配。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.kw = self.engine.model["field_keywords"]

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_pii_keyword_zh(self):
        """身份证号 → pii 类型。"""
        types = self.engine._match_field_keywords("身份证号", self.kw)
        self.assertIn("pii", types)

    def test_finance_keyword_zh(self):
        """银行账号 → finance 类型。"""
        types = self.engine._match_field_keywords("银行账号", self.kw)
        self.assertIn("finance", types)

    def test_health_keyword_zh(self):
        """诊断结果 → health 类型。"""
        types = self.engine._match_field_keywords("诊断结果", self.kw)
        self.assertIn("health", types)

    def test_pii_keyword_en(self):
        """first_name → pii 类型。"""
        types = self.engine._match_field_keywords("customer_first_name", self.kw)
        self.assertIn("pii", types)

    def test_multiple_keyword_types(self):
        """身份证手机邮箱 → 同时命中 pii / phone / email。"""
        types = self.engine._match_field_keywords("身份证手机邮箱", self.kw)
        self.assertIn("pii", types)
        self.assertIn("phone", types)
        self.assertIn("email", types)


class TestEngineClassification(unittest.TestCase):
    """_score_to_level + _calc_confidence + _aggregate_asset。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_score_to_level_l4(self):
        """高分 + pii 类型 → L4。"""
        self.assertEqual(self.engine._score_to_level(0.9, {"pii"}), "L4")

    def test_score_to_level_l3(self):
        """中高分 + finance 类型 → L3。"""
        self.assertEqual(self.engine._score_to_level(0.7, {"finance"}), "L3")

    def test_score_to_level_l2(self):
        """中分 + phone 类型 → L2。"""
        self.assertEqual(self.engine._score_to_level(0.5, {"phone"}), "L2")

    def test_score_to_level_l1(self):
        """低分无敏感类型 → L1。"""
        self.assertEqual(self.engine._score_to_level(0.2, set()), "L1")

    def test_score_to_level_l0(self):
        """极低分 → L0。"""
        self.assertEqual(self.engine._score_to_level(0.05, set()), "L0")

    def test_score_to_level_fallthrough(self):
        """分数在 L2 区间但类型不匹配 → 回落到 L0。"""
        self.assertEqual(self.engine._score_to_level(0.5, {"finance"}), "L0")

    def test_calc_confidence_empty(self):
        """无模式无关键词 → 0.0。"""
        self.assertEqual(self.engine._calc_confidence({}, set()), 0.0)

    def test_calc_confidence_pattern_only(self):
        """仅模式命中 → pattern_score * 0.6。"""
        c = self.engine._calc_confidence({"email": 1}, set())
        self.assertAlmostEqual(c, 0.15, places=3)

    def test_calc_confidence_pattern_and_keyword(self):
        """模式 + 关键词 → 加权综合。"""
        c = self.engine._calc_confidence({"email": 1}, {"email"})
        self.assertAlmostEqual(c, 0.2833, places=3)

    def test_calc_confidence_max(self):
        """4 模式 + 3 关键词 → 1.0。"""
        c = self.engine._calc_confidence(
            {"a": 1, "b": 1, "c": 1, "d": 1}, {"x", "y", "z"}
        )
        self.assertAlmostEqual(c, 1.0, places=3)

    def test_aggregate_asset_highest_level(self):
        """资产级别 = 字段最高级别。"""
        fields = [
            {"asset_id": "A", "level": "L2", "confidence": 0.5,
             "sensitive_types": ["phone"]},
            {"asset_id": "A", "level": "L0", "confidence": 0.1,
             "sensitive_types": []},
        ]
        level, score, types, tags = self.engine._aggregate_asset(fields, "A")
        self.assertEqual(level, "L2")
        self.assertAlmostEqual(score, 0.5, places=3)
        self.assertIn("phone", types)

    def test_aggregate_asset_compliance_tags(self):
        """含 pii 类型 → 合规标签含 GDPR-Art.9。"""
        fields = [
            {"asset_id": "A", "level": "L1", "confidence": 0.2,
             "sensitive_types": ["pii"]},
        ]
        _, _, _, tags = self.engine._aggregate_asset(fields, "A")
        self.assertIn("GDPR-Art.9", tags)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：统计 + 持久化。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.result = self.engine.execute(_load_sample_input())

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_statistics_populated(self):
        """统计含 total_assets / total_fields / by_level / by_sensitive_type。"""
        stats = self.result["statistics"]
        self.assertEqual(stats["total_assets"], 5)
        self.assertEqual(stats["total_fields"], 20)
        self.assertIn("by_level", stats)
        self.assertIn("by_sensitive_type", stats)
        self.assertIn("l3_l4_count", stats)

    def test_assets_persisted_to_db(self):
        """资产持久化到 assets 表（5 条）。"""
        self.assertEqual(self.engine.db.count("assets"), 5)

    def test_fields_persisted_to_db(self):
        """字段持久化到 fields 表（20 条）。"""
        self.assertEqual(self.engine.db.count("fields"), 20)

    def test_by_level_consistent(self):
        """by_level 各级之和 = total_assets。"""
        stats = self.result["statistics"]
        total = sum(stats["by_level"].values())
        self.assertEqual(total, stats["total_assets"])


class TestEngineEndToEnd(unittest.TestCase):
    """端到端 execute：资产发现 + 敏感类型检测。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.result = self.engine.execute(_load_sample_input())

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_result_structure(self):
        """结果含 assets / fields / statistics。"""
        self.assertIn("assets", self.result)
        self.assertIn("fields", self.result)
        self.assertIn("statistics", self.result)
        self.assertEqual(len(self.result["assets"]), 5)

    def test_pii_asset_detected(self):
        """AST001（客户主数据表）含 pii 敏感类型。"""
        ast001 = next(
            a for a in self.result["assets"] if a["asset_id"] == "AST001"
        )
        self.assertIn("pii", ast001["sensitive_types"])

    def test_health_asset_detected(self):
        """AST003（患者病历表）含 health 敏感类型。"""
        ast003 = next(
            a for a in self.result["assets"] if a["asset_id"] == "AST003"
        )
        self.assertIn("health", ast003["sensitive_types"])

    def test_credit_card_asset_detected(self):
        """AST005（信用卡交易记录）含 credit_card 敏感类型。"""
        ast005 = next(
            a for a in self.result["assets"] if a["asset_id"] == "AST005"
        )
        self.assertIn("credit_card", ast005["sensitive_types"])

    def test_all_levels_valid(self):
        """所有资产敏感等级 ∈ {L0,L1,L2,L3,L4}。"""
        valid = {"L0", "L1", "L2", "L3", "L4"}
        for a in self.result["assets"]:
            self.assertIn(a["sensitivity_level"], valid)

    def test_confidence_in_range(self):
        """所有字段置信度 ∈ [0, 1]。"""
        for f in self.result["fields"]:
            self.assertGreaterEqual(f["confidence"], 0.0)
            self.assertLessEqual(f["confidence"], 1.0)

    def test_compliance_tags_for_pii(self):
        """含 pii 的资产有 GDPR-Art.9 合规标签。"""
        for a in self.result["assets"]:
            if "pii" in a["sensitive_types"] or "health" in a["sensitive_types"]:
                self.assertIn("GDPR-Art.9", a["compliance_tags"])


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_assets(self):
        """空资产列表 → 0 资产、0 字段。"""
        result = self.engine.execute({"assets": []})
        self.assertEqual(result["statistics"]["total_assets"], 0)
        self.assertEqual(result["statistics"]["total_fields"], 0)

    def test_asset_with_no_fields(self):
        """无字段的资产 → 仍出现在结果中，field_count=0。"""
        result = self.engine.execute({"assets": [
            {"asset_id": "EMPTY", "name": "空表", "fields": []},
        ]})
        self.assertEqual(result["statistics"]["total_assets"], 1)
        self.assertEqual(result["assets"][0]["field_count"], 0)

    def test_invalid_input_raises(self):
        """非 dict 输入 → ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute(["not", "a", "dict"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
