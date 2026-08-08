"""[SC-01] engine 单测：五维评分 / 等级判定 / 缺失值处理 / 关键词匹配 / 去重。

unittest 风格，每个测试用独立 tmp_path 隔离 PortableDB，避免相互污染。

注意（Windows + SQLite）：PortableDB 连接在 .db 文件上持有锁，
必须在 TemporaryDirectory 清理之前关闭连接，否则触发 PermissionError。
本文件通过 setUp/tearDown 管理生命周期：先关闭所有 engine 连接，再 ignore_errors 清理目录。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from modules.sc_01.engine import MLEngine, _clean_uscc, _safe_float, _safe_int

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_suppliers() -> list:
    """读取 suppliers.jsonl fixture。"""
    with open(_FIXTURES / "suppliers.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class _DBTestCase(unittest.TestCase):
    """提供隔离 tmp_path + 自动关闭 PortableDB 连接的测试基类。

    Windows 下 SQLite 文件锁要求先关连接再删目录；本类在 cleanup 中
    先逐个 close 已创建的 engine，再用 ignore_errors 清理目录。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="sc01_eng_")
        self.tmp_path = Path(self._tmp)
        self._engines: list = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        # 先关闭所有 PortableDB 连接，释放 Windows 文件锁
        for eng in self._engines:
            try:
                eng.close()
            except Exception:
                pass
        # 再清理目录（ignore_errors 兜底残留 -wal/-shm 文件）
        shutil.rmtree(self._tmp, ignore_errors=True)

    def make_engine(self, threshold: float = 0.85,
                    db_name: str = "sc_01_engine.db") -> MLEngine:
        """构造隔离 db 的 engine 并加载模型。"""
        eng = MLEngine(config={
            "threshold": {"confidence": threshold},
            "db_path": str(self.tmp_path / db_name),
        })
        eng.setup()
        self._engines.append(eng)
        return eng


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
class TestCleanUscc(unittest.TestCase):
    def test_clean_strips_whitespace(self):
        self.assertEqual(_clean_uscc("  91440300MA5EX2X71A  "), "91440300MA5EX2X71A")

    def test_clean_uppercases(self):
        self.assertEqual(_clean_uscc("91440300ma5ex2x71a"), "91440300MA5EX2X71A")

    def test_clean_none_or_empty(self):
        self.assertEqual(_clean_uscc(None), "")
        self.assertEqual(_clean_uscc(""), "")
        self.assertEqual(_clean_uscc(123), "")


class TestSafeConverters(unittest.TestCase):
    def test_safe_float_none(self):
        self.assertEqual(_safe_float(None), 0.0)

    def test_safe_float_invalid(self):
        self.assertEqual(_safe_float("abc"), 0.0)

    def test_safe_float_valid(self):
        self.assertEqual(_safe_float("3.14"), 3.14)

    def test_safe_int_none(self):
        self.assertEqual(_safe_int(None), 0)

    def test_safe_int_string(self):
        self.assertEqual(_safe_int("5"), 5)


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
class TestEngineLoadModel(_DBTestCase):
    def test_load_model_creates_tables(self):
        eng = self.make_engine()
        tables = set(eng.db.tables())
        self.assertIn("suppliers", tables)
        self.assertIn("risk_assessments", tables)
        self.assertIn("risk_events", tables)
        self.assertIn("scoring_weights", tables)
        self.assertIn("risk_keywords", tables)

    def test_load_model_seeds_default_weights(self):
        eng = self.make_engine()
        weights = eng.model["weights"]
        self.assertAlmostEqual(weights["business"], 0.15)
        self.assertAlmostEqual(weights["litigation"], 0.25)
        self.assertAlmostEqual(weights["financial"], 0.30)
        self.assertAlmostEqual(weights["esg"], 0.15)
        self.assertAlmostEqual(weights["sentiment"], 0.15)
        # 权重和为 1.0
        self.assertAlmostEqual(sum(weights.values()), 1.0, places=4)

    def test_load_model_loads_keywords_from_fixture(self):
        eng = self.make_engine()
        keywords = eng.model["keywords"]
        self.assertIn("litigation", keywords)
        self.assertIn("esg", keywords)
        self.assertIn("sentiment_negative", keywords)
        self.assertIn("sentiment_positive", keywords)
        # 来自 fixtures/risk_keywords.jsonl 的种子词
        self.assertIn("诉讼", keywords["litigation"])
        self.assertIn("环保", keywords["esg"])
        self.assertIn("破产", keywords["sentiment_negative"])
        self.assertIn("增长", keywords["sentiment_positive"])

    def test_db_persisted_keywords_survive_reload(self):
        db_path = str(self.tmp_path / "sc_01_persist.db")
        eng1 = MLEngine(config={
            "threshold": {"confidence": 0.85},
            "db_path": db_path,
        })
        eng1.setup()
        self._engines.append(eng1)
        self.assertGreater(eng1.db.count("risk_keywords"), 0)
        eng1.close()
        # 新实例加载同一个 db
        eng2 = MLEngine(config={
            "threshold": {"confidence": 0.85},
            "db_path": db_path,
        })
        eng2.setup()
        self._engines.append(eng2)
        self.assertGreater(eng2.db.count("risk_keywords"), 0)


# ----------------------------------------------------------------------
# 预处理：去重 / 缺失值
# ----------------------------------------------------------------------
class TestEnginePreprocess(_DBTestCase):
    def test_dedup_by_uscc(self):
        eng = self.make_engine()
        prepared = eng._preprocess({
            "suppliers": [
                {"supplier_id": "A", "name": "公司A", "uscc": "91440300MA5EX2X71A"},
                {"supplier_id": "B", "name": "公司B", "uscc": "91440300MA5EX2X71A"},  # USCC 重复
                {"supplier_id": "C", "name": "公司C", "uscc": "91440100MA5X9BCD44"},
            ]
        })
        self.assertEqual(len(prepared["suppliers"]), 2)

    def test_dedup_by_name_when_no_uscc(self):
        eng = self.make_engine()
        prepared = eng._preprocess({
            "suppliers": [
                {"supplier_id": "A", "name": "无信用代码公司"},
                {"supplier_id": "B", "name": "无信用代码公司"},  # 名称重复
                {"supplier_id": "C", "name": "另一家公司"},
            ]
        })
        self.assertEqual(len(prepared["suppliers"]), 2)

    def test_missing_fields_filled_with_defaults(self):
        eng = self.make_engine()
        prepared = eng._preprocess({
            "suppliers": [
                {"supplier_id": "A", "name": "数据缺失公司", "uscc": "91440300XX"}
            ]
        })
        s = prepared["suppliers"][0]
        self.assertEqual(s["business"]["registered_capital"], 0.0)
        self.assertEqual(s["business"]["establishment_years"], 0.0)
        self.assertEqual(s["business"]["business_status"], "未知")
        self.assertEqual(s["business"]["change_count"], 0)
        self.assertEqual(s["financial"]["revenue"], 0.0)
        self.assertEqual(s["financial"]["debt_ratio"], 0.0)
        self.assertEqual(s["esg"]["social_security_compliance"], "未知")

    def test_invalid_input_raises_value_error(self):
        eng = self.make_engine()
        with self.assertRaises(ValueError):
            eng.execute(["not", "a", "dict"])

    def test_empty_suppliers_returns_empty(self):
        eng = self.make_engine()
        result = eng.execute({"suppliers": []})
        self.assertEqual(result["suppliers"], [])
        self.assertEqual(result["summary"]["total"], 0)


# ----------------------------------------------------------------------
# 五维评分
# ----------------------------------------------------------------------
class TestFiveDimensionScoring(_DBTestCase):
    def test_healthy_supplier_low_score(self):
        """健康供应商：五维均低分，综合分 < 40，等级=低。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-001",
                    "name": "健康公司",
                    "uscc": "91440300MA5EX2X71A",
                    "business": {"registered_capital": 50000000, "establishment_years": 15, "business_status": "存续", "change_count": 1},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 200000000, "debt_ratio": 0.35, "current_ratio": 2.5, "cash_flow": 30000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": "通过ISO14001认证"},
                    "sentiment": {"news_count": 0, "news_text": "公司获得优秀企业称号，技术创新获奖"},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertLess(s["total_score"], 40)
        self.assertEqual(s["level"], "低")
        self.assertLess(s["sub_scores"]["litigation"], 10)
        self.assertLess(s["sub_scores"]["financial"], 15)
        self.assertLess(s["sub_scores"]["esg"], 10)
        self.assertLess(s["sub_scores"]["sentiment"], 15)

    def test_business_dimension_capital_too_low(self):
        """工商维度：注册资本 <10万 → 工商子分高 + 风险点。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-LOW-CAP",
                    "name": "低资本公司",
                    "uscc": "91440300MA5LOWCAP1",
                    "business": {"registered_capital": 50000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.3, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        # 注册资本 5 万 → cap_score=80，权重 0.30 → 贡献 24 分；
        # 其余维度健康（年限 10 年=5、存续=0、变更 0=0）→ 工商子分 ≈25.5
        # 校验工商子分显著高于健康基线（健康供应商工商子分 < 10）
        self.assertGreater(s["sub_scores"]["business"], 20)
        biz_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "business"]
        self.assertTrue(any("注册资本过低" in p for p in biz_points))

    def test_business_dimension_newly_established(self):
        """工商维度：成立 <1年 → 新设企业风险点。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-NEW",
                    "name": "新设公司",
                    "uscc": "91440300MA5NEWEST1",
                    "business": {"registered_capital": 5000000, "establishment_years": 0.5, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.3, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        biz_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "business"]
        self.assertTrue(any("新设企业" in p for p in biz_points))

    def test_litigation_dimension_dishonest(self):
        """司法维度：失信 → 司法子分高 + 失信风险点。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-DIS",
                    "name": "失信公司",
                    "uscc": "91440300MA5DISHON1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 5, "executed_count": 2, "dishonest_count": 1, "litigation_text": "诉讼被执行失信"},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.5, "current_ratio": 1.5, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertGreaterEqual(s["sub_scores"]["litigation"], 50)
        lit_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "litigation"]
        self.assertTrue(any("失信" in p for p in lit_points))

    def test_financial_dimension_high_debt_and_negative_cashflow(self):
        """财务维度：高负债 + 负现金流 → 财务子分高 + 风险点。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-DEBT",
                    "name": "高负债公司",
                    "uscc": "91440300MA5HIGHDBT",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.85, "current_ratio": 0.8, "cash_flow": -2000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertGreaterEqual(s["sub_scores"]["financial"], 60)
        fin_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "financial"]
        self.assertTrue(any("资产负债率过高" in p for p in fin_points))
        self.assertTrue(any("现金流为负" in p for p in fin_points))

    def test_esg_dimension_multiple_violations(self):
        """ESG维度：环保处罚 + 不合规社保 + 税务违规 → ESG子分高。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-ESG",
                    "name": "ESG违规公司",
                    "uscc": "91440300MA5ESGBAD1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 2, "social_security_compliance": "不合规", "tax_violation_count": 2, "esg_text": "环保污染处罚欠薪偷税"},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertGreaterEqual(s["sub_scores"]["esg"], 60)
        esg_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "esg"]
        self.assertTrue(any("环保处罚" in p for p in esg_points))
        self.assertTrue(any("社保不合规" in p for p in esg_points))
        self.assertTrue(any("税务违规" in p for p in esg_points))

    def test_sentiment_dimension_negative_news(self):
        """舆情维度：负面新闻 + 负面文本 → 舆情子分高。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-NEG",
                    "name": "负面舆情公司",
                    "uscc": "91440300MA5NEGNEW1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 8, "news_text": "公司破产欺诈造假暴雷被执行"},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertGreaterEqual(s["sub_scores"]["sentiment"], 60)
        sen_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "sentiment"]
        self.assertTrue(any("负面新闻" in p for p in sen_points))
        self.assertTrue(any("负面倾向" in p for p in sen_points))

    def test_sentiment_positive_text_low_score(self):
        """舆情维度：正面文本 → 舆情子分低。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-POS",
                    "name": "正面舆情公司",
                    "uscc": "91440300MA5POSNEW1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": "公司增长获奖优质创新突破领先"},
                }
            ]
        })
        s = result["suppliers"][0]
        # 全正面词 → 负面占比 0 → 情感分 0；news=0 → 总分 0
        self.assertLess(s["sub_scores"]["sentiment"], 15)


# ----------------------------------------------------------------------
# 关键词匹配
# ----------------------------------------------------------------------
class TestKeywordMatching(_DBTestCase):
    def test_litigation_keyword_hits(self):
        """司法文本命中多个关键词 → 风险点含命中信息。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-KW-LIT",
                    "name": "司法关键词公司",
                    "uscc": "91440300MA5KWLIT1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": "诉讼纠纷起诉被告判决欠款强制执行"},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        lit_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "litigation"]
        self.assertTrue(any("命中风险关键词" in p for p in lit_points))
        # 关键词命中应提升司法子分
        self.assertGreater(s["sub_scores"]["litigation"], 0)

    def test_esg_keyword_hits(self):
        """ESG文本命中多个关键词 → 风险点含命中信息。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-KW-ESG",
                    "name": "ESG关键词公司",
                    "uscc": "91440300MA5KWESG1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": "环保污染排放欠薪偷税漏税"},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        esg_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "esg"]
        self.assertTrue(any("命中风险关键词" in p for p in esg_points))
        self.assertGreater(s["sub_scores"]["esg"], 0)


# ----------------------------------------------------------------------
# 风险等级判定
# ----------------------------------------------------------------------
class TestRiskLevel(_DBTestCase):
    def test_level_mapping_low_vs_high(self):
        """低风险供应商等级=低，高风险供应商等级∈{高, 极高}。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "LOW",
                    "name": "低风险",
                    "uscc": "91440300MA5LOWLV1",
                    "business": {"registered_capital": 100000000, "establishment_years": 20, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 500000000, "debt_ratio": 0.25, "current_ratio": 3.0, "cash_flow": 80000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": "公司增长获奖优质"},
                },
                {
                    "supplier_id": "HIGH",
                    "name": "高风险",
                    "uscc": "91440300MA5HIGHLV1",
                    "business": {"registered_capital": 500000, "establishment_years": 1, "business_status": "存续", "change_count": 8},
                    "litigation": {"litigation_count": 12, "executed_count": 4, "dishonest_count": 1, "litigation_text": "诉讼被执行失信欠款强制执行查封冻结"},
                    "financial": {"revenue": 5000000, "debt_ratio": 0.92, "current_ratio": 0.5, "cash_flow": -3000000},
                    "esg": {"esg_penalty_count": 3, "social_security_compliance": "不合规", "tax_violation_count": 2, "esg_text": "环保污染欠薪偷税漏税停产整顿"},
                    "sentiment": {"news_count": 15, "news_text": "公司破产欺诈造假暴雷被执行违规下滑暴跌"},
                },
            ]
        })
        by_id = {s["supplier_id"]: s for s in result["suppliers"]}
        self.assertEqual(by_id["LOW"]["level"], "低")
        self.assertIn(by_id["HIGH"]["level"], ("高", "极高"))
        self.assertGreater(by_id["HIGH"]["total_score"], by_id["LOW"]["total_score"])

    def test_results_sorted_desc_by_score(self):
        """结果按综合分降序排列（高风险在前）。"""
        eng = self.make_engine()
        suppliers = _load_suppliers()[:10]
        result = eng.execute({"suppliers": suppliers})
        scores = [s["total_score"] for s in result["suppliers"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_summary_level_distribution_matches(self):
        """summary.level_distribution 之和 = total。"""
        eng = self.make_engine()
        suppliers = _load_suppliers()[:15]
        result = eng.execute({"suppliers": suppliers})
        dist = result["summary"]["level_distribution"]
        total = dist["低"] + dist["中"] + dist["高"] + dist["极高"]
        self.assertEqual(total, result["summary"]["total"])

    def test_recommendations_generated(self):
        """每个供应商都有建议措施。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "SUP-REC",
                    "name": "建议测试",
                    "uscc": "91440300MA5RECOM1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertIsInstance(s["recommendations"], list)
        self.assertGreater(len(s["recommendations"]), 0)


# ----------------------------------------------------------------------
# 缺失值处理
# ----------------------------------------------------------------------
class TestMissingData(_DBTestCase):
    def test_all_zeros_does_not_crash(self):
        """全部字段为零/未知：不崩溃，分数在 [0,100]，有风险点。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "ZERO",
                    "name": "全零公司",
                    "uscc": "91440300MA5ZERO01",
                    "business": {"registered_capital": 0, "establishment_years": 0, "business_status": "未知", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 0, "debt_ratio": 0, "current_ratio": 0, "cash_flow": 0},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "未知", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        self.assertGreaterEqual(s["total_score"], 0)
        self.assertLessEqual(s["total_score"], 100)
        self.assertGreater(len(s["risk_points"]), 0)

    def test_missing_business_data(self):
        """工商数据缺失 → 风险点包含注册资本缺失/成立年限缺失。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "MISSING-BIZ",
                    "name": "缺失工商",
                    "uscc": "91440300MA5MISBIZ1",
                    "business": {},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {"revenue": 10000000, "debt_ratio": 0.4, "current_ratio": 2.0, "cash_flow": 1000000},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        biz_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "business"]
        self.assertTrue(any("注册资本缺失" in p for p in biz_points))
        self.assertTrue(any("成立年限缺失" in p for p in biz_points))

    def test_missing_financial_data(self):
        """财务数据缺失 → 风险点包含缺失提示。"""
        eng = self.make_engine()
        result = eng.execute({
            "suppliers": [
                {
                    "supplier_id": "MISSING-FIN",
                    "name": "缺失财务",
                    "uscc": "91440300MA5MISFIN1",
                    "business": {"registered_capital": 5000000, "establishment_years": 10, "business_status": "存续", "change_count": 0},
                    "litigation": {"litigation_count": 0, "executed_count": 0, "dishonest_count": 0, "litigation_text": ""},
                    "financial": {},
                    "esg": {"esg_penalty_count": 0, "social_security_compliance": "合规", "tax_violation_count": 0, "esg_text": ""},
                    "sentiment": {"news_count": 0, "news_text": ""},
                }
            ]
        })
        s = result["suppliers"][0]
        fin_points = [rp["point"] for rp in s["risk_points"] if rp["dimension"] == "financial"]
        self.assertTrue(any("资产负债率缺失" in p for p in fin_points))
        self.assertTrue(any("流动比率缺失" in p for p in fin_points))


# ----------------------------------------------------------------------
# 全量 fixtures 跑通
# ----------------------------------------------------------------------
class TestFullFixtures(_DBTestCase):
    def test_suppliers_fixture_loadable(self):
        """suppliers.jsonl 至少 50 条且结构完整。"""
        suppliers = _load_suppliers()
        self.assertGreaterEqual(len(suppliers), 50)
        for s in suppliers:
            self.assertIn("supplier_id", s)
            self.assertIn("name", s)
            self.assertIn("business", s)
            self.assertIn("litigation", s)
            self.assertIn("financial", s)
            self.assertIn("esg", s)
            self.assertIn("sentiment", s)

    def test_engine_runs_full_fixtures(self):
        """engine 跑全量 fixtures：去重后 ≥50 家，汇总统计正确。"""
        eng = self.make_engine()
        suppliers = _load_suppliers()
        result = eng.execute({"suppliers": suppliers})
        # SUP-052 与 SUP-001 USCC 相同，去重后 51 家
        self.assertGreaterEqual(len(result["suppliers"]), 50)
        self.assertEqual(result["summary"]["total"], len(result["suppliers"]))
        dist = result["summary"]["level_distribution"]
        self.assertEqual(
            dist["低"] + dist["中"] + dist["高"] + dist["极高"],
            result["summary"]["total"],
        )

    def test_full_fixtures_cover_all_levels(self):
        """全量 fixtures 覆盖低风险与高风险样本。

        注：「极高」等级主要由 custom_rules 一票否决升级产生（失信/清算等），
        engine 五维评分本身产出「低/中/高」三级；极高在 pipeline 测试中覆盖。
        """
        eng = self.make_engine()
        suppliers = _load_suppliers()
        result = eng.execute({"suppliers": suppliers})
        dist = result["summary"]["level_distribution"]
        # 至少有低风险和高风险样本
        self.assertGreater(dist["低"], 0, "应有低风险样本")
        self.assertGreater(dist["高"], 0, "应有高风险样本")


if __name__ == "__main__":
    unittest.main()
