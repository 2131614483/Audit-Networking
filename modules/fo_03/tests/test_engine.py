"""[FO-03] engine 单测：关键词检测 / Benford检验 / 严重等级 / 风险评分 / 汇总。

unittest 风格（不依赖 pytest），纯 stdlib。
"""
from __future__ import annotations

import unittest

from modules.fo_03.engine import LLMEngine


def _make_engine() -> LLMEngine:
    """构造已加载模型的 engine。"""
    eng = LLMEngine()
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：舞弊信号词典 + Benford 配置加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_model_loaded(self):
        """model 非 None 且含 fraud_signal_categories。"""
        self.assertIsNotNone(self.engine.model)
        self.assertIn("fraud_signal_categories", self.engine.model)

    def test_categories_populated(self):
        """舞弊信号类别 ≥ 6 类。"""
        cats = self.engine.model["fraud_signal_categories"]
        self.assertGreaterEqual(len(cats), 6)

    def test_benford_config_loaded(self):
        """Benford 阈值与期望分布已加载。"""
        self.assertIn("benford_threshold", self.engine.model)
        self.assertIn("benford_expected", self.engine.model)
        self.assertGreater(len(self.engine.model["benford_expected"]), 5)

    def test_db_initialized(self):
        """PortableDB 已初始化。"""
        from modules.shared.portable_db import PortableDB
        self.assertIsInstance(self.engine.db, PortableDB)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：文档归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_documents_normalized(self):
        """文档归一化后含 doc_id/title/content/doc_type。"""
        prepared = self.engine._preprocess({
            "documents": [
                {"doc_id": "D1", "title": "测试", "content": "隐瞒收入", "doc_type": "邮件"},
            ],
        })
        doc = prepared["documents"][0]
        self.assertEqual(doc["doc_id"], "D1")
        self.assertEqual(doc["title"], "测试")
        self.assertEqual(doc["content"], "隐瞒收入")
        self.assertEqual(doc["doc_type"], "邮件")

    def test_auto_doc_id(self):
        """缺失 doc_id 时自动生成 DOC-000001。"""
        prepared = self.engine._preprocess({
            "documents": [{"content": "测试文本"}],
        })
        self.assertTrue(prepared["documents"][0]["doc_id"].startswith("DOC-"))

    def test_missing_fields_defaulted(self):
        """缺失字段有默认值（title→空串, doc_type→文本）。"""
        prepared = self.engine._preprocess({
            "documents": [{"doc_id": "D2", "content": "测试"}],
        })
        doc = prepared["documents"][0]
        self.assertEqual(doc["title"], "")
        self.assertEqual(doc["doc_type"], "文本")

    def test_non_dict_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess("not a dict")

    def test_empty_documents(self):
        """空文档列表 → 0 文档。"""
        prepared = self.engine._preprocess({"documents": []})
        self.assertEqual(len(prepared["documents"]), 0)


class TestEngineAnalyzeDocument(unittest.TestCase):
    """_analyze_document：关键词检测 / Benford / 严重等级。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_fraud_keyword_detected(self):
        """隐瞒收入关键词被检测到。"""
        findings = self.engine._analyze_document({
            "doc_id": "T1", "title": "", "doc_type": "文本",
            "content": "本公司隐瞒了部分收入",
        })
        cats = [f["category"] for f in findings]
        self.assertIn("隐瞒收入", cats)

    def test_multiple_keywords_same_category(self):
        """同类别多个关键词各生成一条 finding。"""
        findings = self.engine._analyze_document({
            "doc_id": "T2", "title": "", "doc_type": "文本",
            "content": "隐瞒收入并藏匿账外资金",
        })
        conceal_findings = [f for f in findings if f["category"] == "隐瞒收入"]
        self.assertGreaterEqual(len(conceal_findings), 2)

    def test_keyword_count_recorded(self):
        """关键词出现次数被记录在 count 字段。"""
        findings = self.engine._analyze_document({
            "doc_id": "T3", "title": "", "doc_type": "文本",
            "content": "可能大概可能",
        })
        hedge = [f for f in findings if f["keyword"] == "可能"]
        self.assertEqual(hedge[0]["count"], 2)

    def test_clean_document_no_findings(self):
        """无舞弊关键词的文档 → 0 findings。"""
        findings = self.engine._analyze_document({
            "doc_id": "T4", "title": "", "doc_type": "文本",
            "content": "本公司从事日用百货零售业务，经营正常。",
        })
        self.assertEqual(len(findings), 0)

    def test_benford_detection(self):
        """≥10 个首数字均为 9 的金额 → Benford 异常 finding。"""
        content = "费用：" + " ".join([f"9{i:02d}元" for i in range(12)])
        findings = self.engine._analyze_document({
            "doc_id": "T5", "title": "", "doc_type": "文本",
            "content": content,
        })
        benford = [f for f in findings if f["category"] == "数值异常"]
        self.assertEqual(len(benford), 1)
        self.assertGreater(benford[0]["deviation"], 0.15)

    def test_benford_not_triggered_below_threshold(self):
        """金额数量 < 10 → 不触发 Benford。"""
        findings = self.engine._analyze_document({
            "doc_id": "T6", "title": "", "doc_type": "文本",
            "content": "费用：100元 200元 300元",
        })
        benford = [f for f in findings if f["category"] == "数值异常"]
        self.assertEqual(len(benford), 0)


class TestEngineSeverity(unittest.TestCase):
    """_severity_for：类别 → 严重等级映射。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_high_severity_categories(self):
        """隐瞒收入/虚列支出/资金挪用/利益输送 → high。"""
        for cat in ("隐瞒收入", "虚列支出", "虚假发票", "资金挪用", "利益输送", "洗钱"):
            self.assertEqual(self.engine._severity_for(cat), "high")

    def test_medium_severity_category(self):
        """操纵市场 → medium。"""
        self.assertEqual(self.engine._severity_for("操纵市场"), "medium")

    def test_low_severity_categories(self):
        """模糊用语/强烈肯定 → low。"""
        self.assertEqual(self.engine._severity_for("模糊用语"), "low")
        self.assertEqual(self.engine._severity_for("强烈肯定"), "low")


class TestEngineRiskScore(unittest.TestCase):
    """_compute_doc_risk：风险评分计算。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_no_findings_zero_score(self):
        """无 findings → risk_score=0.0。"""
        self.assertEqual(self.engine._compute_doc_risk([]), 0.0)

    def test_high_severity_dominates(self):
        """3 个 high finding → score=3/5=0.6。"""
        findings = [
            {"severity": "high"},
            {"severity": "high"},
            {"severity": "high"},
        ]
        self.assertAlmostEqual(self.engine._compute_doc_risk(findings), 0.6)

    def test_score_capped_at_one(self):
        """超过 5 个 high finding → 封顶 1.0。"""
        findings = [{"severity": "high"} for _ in range(10)]
        self.assertEqual(self.engine._compute_doc_risk(findings), 1.0)

    def test_mixed_severity(self):
        """混合：2 high + 1 medium + 1 low → (2+0.5+0.2)/5=0.54。"""
        findings = [
            {"severity": "high"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        self.assertAlmostEqual(
            self.engine._compute_doc_risk(findings), (2.0 + 0.5 + 0.2) / 5
        )


class TestEngineBenford(unittest.TestCase):
    """_benford_test：偏差计算。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_all_nines_high_deviation(self):
        """全部首数字为 9 → 偏差极大。"""
        amounts = [900, 950, 920, 980, 910, 930, 970, 940, 960, 990]
        result = self.engine._benford_test(amounts)
        self.assertGreater(result["deviation"], 0.5)

    def test_total_digits_counted(self):
        """total_digits = 金额数量。"""
        amounts = [100, 200, 300, 400, 500, 600, 700, 800, 900, 150]
        result = self.engine._benford_test(amounts)
        self.assertEqual(result["total_digits"], 10)


class TestEngineExecuteAndPostprocess(unittest.TestCase):
    """execute / _postprocess：端到端 + 汇总。"""

    def setUp(self):
        self.engine = _make_engine()
        self.data = {
            "documents": [
                {"doc_id": "E1", "title": "邮件", "doc_type": "邮件",
                 "content": "隐瞒收入并虚列支出，挪用资金"},
                {"doc_id": "E2", "title": "正常", "doc_type": "说明",
                 "content": "公司经营正常，无异常情况"},
            ],
        }
        self.result = self.engine.execute(self.data)

    def test_detections_count(self):
        """检测结果数 = 文档数。"""
        self.assertEqual(len(self.result["detections"]), 2)

    def test_detection_fields(self):
        """每个 detection 含 doc_id/findings/risk_score。"""
        for det in self.result["detections"]:
            self.assertIn("doc_id", det)
            self.assertIn("findings", det)
            self.assertIn("risk_score", det)
            self.assertIn("title", det)
            self.assertIn("doc_type", det)

    def test_summary_fields(self):
        """summary 含 document_count/total_signals/high_risk_docs/avg_risk_score。"""
        s = self.result["summary"]
        self.assertEqual(s["document_count"], 2)
        self.assertIn("total_signals", s)
        self.assertIn("high_risk_docs", s)
        self.assertIn("avg_risk_score", s)
        self.assertIn("category_counts", s)

    def test_fraud_doc_higher_score(self):
        """舞弊文档(E1)风险评分高于正常文档(E2)。"""
        scores = {d["doc_id"]: d["risk_score"] for d in self.result["detections"]}
        self.assertGreater(scores["E1"], scores["E2"])

    def test_overall_risk_level_set(self):
        """_postprocess 设置 overall_risk_level。"""
        self.assertIn("overall_risk_level", self.result["summary"])
        self.assertIn(self.result["summary"]["overall_risk_level"],
                      ("高风险", "中风险", "低风险"))

    def test_clean_doc_zero_score(self):
        """正常文档(E2) risk_score=0.0。"""
        scores = {d["doc_id"]: d["risk_score"] for d in self.result["detections"]}
        self.assertEqual(scores["E2"], 0.0)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_documents(self):
        """空文档列表 → 0 检测结果。"""
        result = self.engine.execute({"documents": []})
        self.assertEqual(result["summary"]["document_count"], 0)
        self.assertEqual(len(result["detections"]), 0)

    def test_empty_content(self):
        """空 content → 0 findings, risk_score=0。"""
        result = self.engine.execute({
            "documents": [{"doc_id": "X1", "content": ""}],
        })
        self.assertEqual(result["detections"][0]["risk_score"], 0.0)
        self.assertEqual(len(result["detections"][0]["findings"]), 0)

    def test_category_counts_aggregated(self):
        """category_counts 跨文档聚合。"""
        result = self.engine.execute({
            "documents": [
                {"doc_id": "C1", "content": "隐瞒收入"},
                {"doc_id": "C2", "content": "隐瞒收入"},
            ],
        })
        self.assertEqual(result["summary"]["category_counts"]["隐瞒收入"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
