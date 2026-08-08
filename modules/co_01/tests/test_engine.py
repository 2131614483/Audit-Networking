"""[CO-01] engine 单测：法规分类 / 影响评估 / 多语言 / 订阅匹配（unittest 风格）。

每个测试用独立 tmp 目录隔离 PortableDB，避免订阅规则互相污染。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.co_01.engine import (
    KGEngine,
    _normalize_date,
    _strip_html,
    _count_substring,
    _count_word,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _make_engine(test: unittest.TestCase, tmp_dir: str,
                 threshold: float = 0.85) -> KGEngine:
    """构造隔离 db 的 engine 并加载模型；注册 close 清理（Windows 文件锁）。"""
    eng = KGEngine(config={
        "threshold": {"confidence": threshold},
        "db_path": str(Path(tmp_dir) / "co_01_engine.db"),
    })
    eng.setup()
    test.addCleanup(eng.close)
    return eng


def _enterprise(**overrides):
    """默认企业画像：大型上市金融科技集团，总部中国。"""
    base = {
        "name": "示例金融科技集团",
        "industries": ["finance", "technology"],
        "countries": ["CN"],
        "size": "large",
        "listed": True,
        "home_country": "CN",
    }
    base.update(overrides)
    return base


class TestTextUtilities(unittest.TestCase):
    """文本清洗 / 日期归一化 / 关键词计数工具。"""

    def test_strip_html_removes_tags(self):
        self.assertEqual(_strip_html("<p>数据安全<p>法"), "数据安全 法")

    def test_strip_html_collapses_whitespace(self):
        self.assertEqual(_strip_html("  a   b  "), "a b")

    def test_normalize_date_slash(self):
        self.assertEqual(_normalize_date("2021/06/10"), "2021-06-10")

    def test_normalize_date_dot(self):
        self.assertEqual(_normalize_date("2021.06.10"), "2021-06-10")

    def test_normalize_date_iso(self):
        self.assertEqual(_normalize_date("2021-06-10"), "2021-06-10")

    def test_normalize_date_empty(self):
        self.assertEqual(_normalize_date(""), "")

    def test_count_substring_chinese(self):
        self.assertEqual(_count_substring("数据安全与数据安全法", "数据安全"), 2)

    def test_count_word_english_case_insensitive(self):
        self.assertEqual(_count_word("Data Security and data security", "data security"), 2)

    def test_count_word_boundary(self):
        # "disclosure" 不应匹配 "disclosures"
        self.assertEqual(_count_word("disclosures of data", "disclosure"), 0)


class TestRegulationClassification(unittest.TestCase):
    """① 法规分类：TF-IDF 关键词分类。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.eng = _make_engine(self, self._tmp.name)

    def test_classify_data_security_zh(self):
        """中文数据安全法分类为 data_security，置信度 > 0。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "T1", "title": "数据安全法",
                "body": "规范数据处理活动，保障数据安全，保护个人信息，数据出境安全评估。",
                "country": "CN", "language": "zh", "publish_date": "2021-06-10",
            }],
        })
        reg = r["regulations"][0]
        self.assertEqual(reg["category"], "data_security")
        self.assertGreater(reg["category_confidence"], 0.0)
        self.assertIn("数据安全", reg["matched_keywords"])

    def test_classify_tax_en(self):
        """英文税务法规分类为 tax。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "T2", "title": "Tax Cuts and Jobs Act",
                "body": "Reform corporate income tax, reduce tax rate, transfer pricing, withholding tax.",
                "country": "US", "language": "en", "publish_date": "2017-12-22",
            }],
        })
        reg = r["regulations"][0]
        self.assertEqual(reg["category"], "tax")
        self.assertIn("tax", reg["matched_keywords"])

    def test_classify_accounting(self):
        """会计准则分类。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "T3", "title": "企业会计准则",
                "body": "规范会计确认计量，公允价值，收入确认，金融工具，合并报表，财务报告。",
                "country": "CN", "language": "zh", "publish_date": "2006-02-15",
            }],
        })
        self.assertEqual(r["regulations"][0]["category"], "accounting")

    def test_classify_no_match_returns_other(self):
        """无任何分类关键词命中 → other，置信度 0。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "T4", "title": "zzz qqq xxx",
                "body": "no relevant keyword here at all",
                "country": "XX", "language": "en", "publish_date": "2020-01-01",
            }],
        })
        reg = r["regulations"][0]
        self.assertEqual(reg["category"], "other")
        self.assertEqual(reg["category_confidence"], 0.0)
        self.assertEqual(reg["matched_keywords"], [])

    def test_classify_antitrust_zh(self):
        """反垄断法分类。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "T5", "title": "反垄断法",
                "body": "禁止垄断协议，滥用市场支配地位，经营者集中审查，公平竞争。",
                "country": "CN", "language": "zh", "publish_date": "2022-06-24",
            }],
        })
        self.assertEqual(r["regulations"][0]["category"], "antitrust")


class TestImpactAssessment(unittest.TestCase):
    """② 影响评估：相关性评分 + 影响等级。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.eng = _make_engine(self, self._tmp.name)

    def test_home_country_high_relevance(self):
        """企业所在国 + 本行业法规 → 高相关性（≥0.7）→ high。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "H1", "title": "数据安全法",
                "body": "数据安全 个人信息 数据出境 网络安全",
                "country": "CN", "language": "zh", "publish_date": "2021-06-10",
                "applicable_size": "all",
            }],
        })
        reg = r["regulations"][0]
        self.assertEqual(reg["country_match"], 1)
        self.assertGreaterEqual(reg["industry_match"], 0.5)
        self.assertGreaterEqual(reg["relevance"], 0.7)
        self.assertEqual(reg["impact_level"], "high")

    def test_foreign_country_lower_relevance(self):
        """外国法规相关性低于本国法规。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [
                {"reg_id": "F1", "title": "数据安全法", "body": "数据安全 个人信息",
                 "country": "CN", "language": "zh", "publish_date": "2021-06-10"},
                {"reg_id": "F2", "title": "Data Security Law", "body": "data security personal information",
                 "country": "US", "language": "en", "publish_date": "2021-06-10"},
            ],
        })
        by_id = {x["reg_id"]: x for x in r["regulations"]}
        self.assertGreater(by_id["F1"]["relevance"], by_id["F2"]["relevance"])
        self.assertEqual(by_id["F1"]["country_match"], 1)
        self.assertEqual(by_id["F2"]["country_match"], 0)

    def test_industry_match_full_vs_generic(self):
        """data_security 命中 finance/technology 行业 → industry_match=1.0；
           tax 通用法规 → industry_match=0.5。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [
                {"reg_id": "I1", "title": "数据安全法", "body": "数据安全 个人信息",
                 "country": "CN", "language": "zh", "publish_date": "2021-06-10"},
                {"reg_id": "I2", "title": "增值税法", "body": "增值税 税率 抵扣 纳税",
                 "country": "CN", "language": "zh", "publish_date": "2024-12-25"},
            ],
        })
        by_id = {x["reg_id"]: x for x in r["regulations"]}
        self.assertEqual(by_id["I1"]["industry_match"], 1.0)
        self.assertEqual(by_id["I2"]["industry_match"], 0.5)

    def test_scope_match_size(self):
        """applicable_size=large 命中 large 企业；=small 不命中。"""
        r = self.eng.execute({
            "enterprise": _enterprise(size="large"),
            "regulations": [
                {"reg_id": "S1", "title": "证券法", "body": "证券 上市公司 招股说明书 信息披露",
                 "country": "CN", "language": "zh", "publish_date": "2019-12-28",
                 "applicable_size": "large"},
                {"reg_id": "S2", "title": "证券法", "body": "证券 上市公司 招股说明书 信息披露",
                 "country": "CN", "language": "zh", "publish_date": "2019-12-28",
                 "applicable_size": "small"},
            ],
        })
        by_id = {x["reg_id"]: x for x in r["regulations"]}
        self.assertEqual(by_id["S1"]["scope_match"], 1)
        self.assertEqual(by_id["S2"]["scope_match"], 0)

    def test_impact_level_thresholds(self):
        """影响等级阈值：高≥0.7 / 中0.4-0.7 / 低<0.4。"""
        eng = self.eng
        self.assertEqual(eng._impact_level(0.85), "high")
        self.assertEqual(eng._impact_level(0.7), "high")
        self.assertEqual(eng._impact_level(0.55), "medium")
        self.assertEqual(eng._impact_level(0.4), "medium")
        self.assertEqual(eng._impact_level(0.3), "low")


class TestMultilingual(unittest.TestCase):
    """③ 多语言处理：中英双语关键词匹配。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.eng = _make_engine(self, self._tmp.name)

    def test_chinese_and_english_both_classified(self):
        """中英文表述的同类法规应分到同一分类。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [
                {"reg_id": "M1", "title": "数据安全法",
                 "body": "数据安全 个人信息保护 数据出境",
                 "country": "CN", "language": "zh", "publish_date": "2021-06-10"},
                {"reg_id": "M2", "title": "Data Protection Regulation",
                 "body": "data security personal information data protection privacy",
                 "country": "EU", "language": "en", "publish_date": "2018-05-25"},
            ],
        })
        by_id = {x["reg_id"]: x for x in r["regulations"]}
        self.assertEqual(by_id["M1"]["category"], "data_security")
        self.assertEqual(by_id["M2"]["category"], "data_security")

    def test_html_stripped_before_classification(self):
        """HTML 标签在预处理中被去除，不影响分类。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "M3", "title": "数据安全法",
                "body": "<p>数据安全 与 个人信息 保护</p>",
                "country": "CN", "language": "zh", "publish_date": "2021-06-10",
            }],
        })
        reg = r["regulations"][0]
        self.assertEqual(reg["category"], "data_security")
        self.assertNotIn("<p>", reg["body"])

    def test_date_normalized_from_slash(self):
        """YYYY/MM/DD 日期归一化为 YYYY-MM-DD。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "M4", "title": "数据安全法",
                "body": "数据安全 个人信息",
                "country": "CN", "language": "zh", "publish_date": "2021/06/10",
            }],
        })
        self.assertEqual(r["regulations"][0]["publish_date"], "2021-06-10")


class TestSubscriptionMatching(unittest.TestCase):
    """④ 订阅匹配：对照企业订阅规则匹配需推送法规。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.eng = _make_engine(self, self._tmp.name)

    def test_subscription_match_marks_push(self):
        """命中订阅规则的法规 subscription_match=True 且 push=True。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "P1", "title": "数据安全法",
                "body": "数据安全 个人信息 数据出境",
                "country": "CN", "language": "zh", "publish_date": "2021-06-10",
            }],
        })
        reg = r["regulations"][0]
        self.assertTrue(reg["subscription_match"])
        self.assertTrue(reg["push"])
        self.assertIn("subscription_match", reg["push_reasons"])
        self.assertGreater(len(reg["matched_rules"]), 0)

    def test_no_subscription_no_push(self):
        """未命中订阅规则且相关性低 → push=False。

        美国劳动法对中国金融科技企业：SUB-007 仅订阅 CN 劳动法规，故不命中。
        """
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "P2", "title": "Fair Labor Standards Act",
                "body": "minimum wage overtime working time employee",
                "country": "US", "language": "en", "publish_date": "1938-06-25",
            }],
        })
        reg = r["regulations"][0]
        self.assertFalse(reg["subscription_match"])
        self.assertFalse(reg["push"])
        self.assertEqual(reg["matched_rules"], [])

    def test_global_subscription_matches_any_country(self):
        """SUB-005 全球数据安全订阅：外国数据安全法规也应命中。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "P3", "title": "GDPR",
                "body": "data protection personal data privacy data processing",
                "country": "EU", "language": "en", "publish_date": "2018-05-25",
            }],
        })
        reg = r["regulations"][0]
        self.assertTrue(reg["subscription_match"])
        self.assertIn("SUB-005", reg["matched_rules"])

    def test_add_subscription_rule_persists(self):
        """新增订阅规则持久化到 PortableDB，新 engine 实例自动加载。"""
        db_path = Path(self._tmp.name) / "co_01_sub.db"
        eng1 = KGEngine(config={
            "threshold": {"confidence": 0.85}, "db_path": str(db_path),
        })
        eng1.setup()
        self.addCleanup(eng1.close)
        eng1.add_subscription_rule(
            "SUB-TEST", industry="technology", country="JP",
            categories=["data_security"], priority="high", desc="测试规则",
        )
        # 新实例加载同一 db
        eng2 = KGEngine(config={
            "threshold": {"confidence": 0.85}, "db_path": str(db_path),
        })
        eng2.setup()
        self.addCleanup(eng2.close)
        rule_ids = [r["rule_id"] for r in eng2.model["subscription_rules"]]
        self.assertIn("SUB-TEST", rule_ids)

        # 日本数据安全法规命中新规则
        r = eng2.execute({
            "enterprise": _enterprise(),
            "regulations": [{
                "reg_id": "P4", "title": "Japan Data Protection Law",
                "body": "data security personal data privacy",
                "country": "JP", "language": "en", "publish_date": "2020-01-01",
            }],
        })
        self.assertIn("SUB-TEST", r["regulations"][0]["matched_rules"])


class TestPostprocessStats(unittest.TestCase):
    """后处理统计：总数 / 各分类 / 各等级 / 推送数 / 覆盖国家。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.eng = _make_engine(self, self._tmp.name)

    def test_statistics_aggregation(self):
        """统计字段正确聚合。"""
        r = self.eng.execute({
            "enterprise": _enterprise(),
            "regulations": [
                {"reg_id": "A1", "title": "数据安全法", "body": "数据安全 个人信息",
                 "country": "CN", "language": "zh", "publish_date": "2021-06-10"},
                {"reg_id": "A2", "title": "GDPR", "body": "data protection personal data",
                 "country": "EU", "language": "en", "publish_date": "2018-05-25"},
                {"reg_id": "A3", "title": "增值税法", "body": "增值税 税率 抵扣",
                 "country": "CN", "language": "zh", "publish_date": "2024-12-25"},
            ],
        })
        stats = r["statistics"]
        self.assertEqual(stats["total"], 3)
        self.assertIn("data_security", stats["by_category"])
        self.assertIn("tax", stats["by_category"])
        self.assertGreaterEqual(stats["push_count"], 0)
        self.assertIn("CN", stats["covered_countries"])
        self.assertIn("EU", stats["covered_countries"])


class TestEdgeCases(unittest.TestCase):
    """空输入 / 异常输入。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.eng = _make_engine(self, self._tmp.name)

    def test_empty_regulations(self):
        """空法规列表返回空结果与零统计。"""
        r = self.eng.execute({"enterprise": _enterprise(), "regulations": []})
        self.assertEqual(r["regulations"], [])
        self.assertEqual(r["statistics"]["total"], 0)

    def test_invalid_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.eng.execute(["not", "a", "dict"])

    def test_missing_enterise_uses_empty(self):
        """缺 enterprise 字段不报错（视为无匹配企业）。"""
        r = self.eng.execute({"regulations": [
            {"reg_id": "E1", "title": "数据安全法", "body": "数据安全 个人信息",
             "country": "CN", "language": "zh", "publish_date": "2021-06-10"},
        ]})
        self.assertEqual(len(r["regulations"]), 1)


if __name__ == "__main__":
    unittest.main()
