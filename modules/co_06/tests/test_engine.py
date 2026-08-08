"""[CO-06] engine 单测：告警处理 / 模式识别 / 叙事生成 / 证据链 / 风险评分 / 报告格式化。

unittest 风格（不依赖 pytest）。CO-06 engine 无 PortableDB，无需 tmp 目录隔离。
注意：engine._preprocess 访问 self.model，故 execute/_preprocess 前必须 setup()。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_06.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(**overrides) -> KGEngine:
    config = {
        "reporting_org": "测试报告机构",
        "reporter": "测试分析师",
        "contact": "13800000000",
    }
    config.update(overrides)
    eng = KGEngine(config=config)
    eng.setup()
    return eng


def _tx(tx_id, amount, **kw):
    """构造一笔交易。"""
    t = {"tx_id": tx_id, "timestamp": kw.get("time", "2025-06-10T10:00:00+08:00"),
         "amount": amount, "currency": "CNY", "direction": kw.get("direction", "in"),
         "counterparty": kw.get("counterparty", {"name": "对手", "account": "A"}),
         "channel": kw.get("channel", "柜台"), "ip": kw.get("ip", ""),
         "location": kw.get("location", "上海"), "purpose": kw.get("purpose", "测试")}
    return t


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：多监管模板 / 字段映射 / 质量评分框架加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_model_has_five_templates(self):
        """加载 5 套监管模板。"""
        templates = self.engine.model["templates"]
        self.assertEqual(len(templates), 5)
        for tid in ("CN-PBOC", "US-FINCEN", "UK-NCA", "FATF-FIU", "HK-SG-FIU"):
            self.assertIn(tid, templates)

    def test_model_has_field_mapping(self):
        """字段映射表非空。"""
        self.assertGreater(len(self.engine.model["field_mapping"]), 10)

    def test_model_has_quality_weights(self):
        """质量评分框架 4 大类满分合计 100。"""
        w = self.engine.model["quality_weights"]
        total = sum(v["max"] for v in w.values())
        self.assertEqual(total, 100)
        for k in ("completeness", "accuracy", "logic", "compliance"):
            self.assertIn(k, w)

    def test_default_template_is_cn_pboc(self):
        """默认模板为 CN-PBOC。"""
        self.assertEqual(self.engine.model["current_template_id"], "CN-PBOC")

    def test_risk_framework_thresholds(self):
        """风险框架含 high/medium/low 三档阈值。"""
        rf = self.engine.model["risk_framework"]
        self.assertGreater(rf["high"]["threshold"], rf["medium"]["threshold"])
        self.assertGreater(rf["medium"]["threshold"], rf["low"]["threshold"])

    def test_suspicious_patterns_loaded(self):
        """可疑模式库加载至少 9 条。"""
        self.assertGreaterEqual(len(self.engine.model["suspicious_patterns"]), 9)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：告警 / 交易 / 客户数据归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_preprocess_normalizes_transactions(self):
        """交易标准化：amount 转 float、提取 tx_id。"""
        data = {"alert": {"transactions": [_tx("T1", "9500")]}}
        prepared = self.engine._preprocess(data)
        self.assertEqual(len(prepared["transactions"]), 1)
        self.assertEqual(prepared["transactions"][0]["amount"], 9500.0)
        self.assertEqual(prepared["transactions"][0]["tx_id"], "T1")

    def test_preprocess_extracts_customer(self):
        """从 alert.customer 提取客户信息。"""
        data = {"alert": {"customer": {"name": "张某", "id_no": "310101"}, "transactions": []}}
        prepared = self.engine._preprocess(data)
        self.assertEqual(prepared["customer"]["name"], "张某")

    def test_preprocess_template_id_from_input(self):
        """template_id 取自输入。"""
        data = {"template_id": "US-FINCEN", "alert": {"transactions": []}}
        prepared = self.engine._preprocess(data)
        self.assertEqual(prepared["template_id"], "US-FINCEN")

    def test_preprocess_falls_back_to_default_template(self):
        """未知 template_id 回退到 CN-PBOC。"""
        data = {"template_id": "UNKNOWN", "alert": {"transactions": []}}
        prepared = self.engine._preprocess(data)
        self.assertEqual(prepared["template_id"], "CN-PBOC")

    def test_preprocess_string_input(self):
        """字符串输入（非法 JSON）→ raw_text。"""
        prepared = self.engine._preprocess("not a json")
        self.assertIn("raw_text", prepared["alert"])

    def test_preprocess_calculates_tx_amount_total(self):
        """交易总额 = 各笔金额之和。"""
        data = {"alert": {"transactions": [_tx("T1", 100), _tx("T2", 200.5)]}}
        prepared = self.engine._preprocess(data)
        self.assertAlmostEqual(prepared["tx_amount_total"], 300.5)

    def test_preprocess_alert_id_generated(self):
        """缺 alert_id 时自动生成。"""
        data = {"alert": {"transactions": []}}
        prepared = self.engine._preprocess(data)
        self.assertTrue(prepared["alert_id"].startswith("ALERT-"))


class TestEngineNarrative(unittest.TestCase):
    """_generate_5w1h：5W1H 可疑行为描述。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample()
        self.prepared = self.engine._preprocess(self.sample)
        self.narrative = self.engine._generate_5w1h(self.prepared)

    def test_narrative_contains_who(self):
        """Who：含主体姓名。"""
        self.assertIn("张某", self.narrative)

    def test_narrative_contains_what(self):
        """What：含交易笔数与合计金额。"""
        self.assertIn("8 笔", self.narrative)
        self.assertIn("321300", self.narrative)

    def test_narrative_contains_when(self):
        """When：含时间范围。"""
        self.assertIn("时间范围", self.narrative)

    def test_narrative_contains_where(self):
        """Where：含渠道 / 地点。"""
        self.assertIn("柜台", self.narrative)

    def test_narrative_contains_why(self):
        """Why：含可疑原因。"""
        self.assertIn("可疑原因", self.narrative)

    def test_narrative_contains_how(self):
        """How：含关联账户 / 关联方信息。"""
        self.assertIn("关联账户", self.narrative)


class TestEnginePatternDetection(unittest.TestCase):
    """_detect_patterns：可疑模式识别。"""

    def setUp(self):
        self.engine = _make_engine()

    def _detect(self, alert):
        prepared = self.engine._preprocess({"alert": alert})
        return self.engine._detect_patterns(prepared)

    def test_detect_structuring(self):
        """3+ 笔金额在 8000-10000 → STRUCTURING。"""
        txs = [_tx(f"T{i}", 9500) for i in range(4)]
        codes = {p["code"] for p in self._detect({"transactions": txs})}
        self.assertIn("STRUCTURING", codes)

    def test_detect_smurfing(self):
        """5+ 笔小额（<1万）且总额>=5万 → SMURFING。"""
        txs = [_tx(f"T{i}", 9000) for i in range(6)]  # 总额 54000 >= 50000
        codes = {p["code"] for p in self._detect({"transactions": txs})}
        self.assertIn("SMURFING", codes)

    def test_detect_layering(self):
        """3+ 不同对手方 + 2+ 笔大额(>=10万) → LAYERING。"""
        txs = [
            _tx("T1", 150000, counterparty={"name": "A"}),
            _tx("T2", 120000, counterparty={"name": "B"}),
            _tx("T3", 50000, counterparty={"name": "C"}),
        ]
        codes = {p["code"] for p in self._detect({"transactions": txs})}
        self.assertIn("LAYERING", codes)

    def test_detect_keyword_money_laundry(self):
        """trigger_reason 含『频繁跨境』→ MONEY_LAUNDRY。"""
        codes = {p["code"] for p in self._detect({
            "transactions": [_tx("T1", 50000)],
            "trigger_reason": "资金频繁跨境转出",
        })}
        self.assertIn("MONEY_LAUNDRY", codes)

    def test_detect_unspecified_when_high_score_no_pattern(self):
        """alert_score>=50 且无明确模式 → UNSPECIFIED。"""
        codes = {p["code"] for p in self._detect({
            "transactions": [_tx("T1", 50000)],
            "risk_score": 60,
            "trigger_reason": "一般异常",
        })}
        self.assertIn("UNSPECIFIED", codes)

    def test_no_patterns_low_score(self):
        """低风险且无结构/关键词特征 → 无模式。"""
        codes = {p["code"] for p in self._detect({
            "transactions": [_tx("T1", 50000)],
            "risk_score": 10,
            "trigger_reason": "",
        })}
        self.assertEqual(codes, set())

    def test_detected_pattern_has_reason(self):
        """每个识别模式含 reason 说明。"""
        for p in self._detect({"transactions": [_tx(f"T{i}", 9500) for i in range(4)]}):
            self.assertTrue(p.get("reason"))


class TestEngineRiskAssessment(unittest.TestCase):
    """_assess_risk：风险等级判定。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_risk_score_capped_at_100(self):
        """风险评分上限 100。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 95, "transactions": [_tx(f"T{i}", 9500) for i in range(6)],
            "trigger_reason": "频繁跨境",
            "related_parties": [{"name": f"P{i}"} for i in range(5)],
        }})
        patterns = self.engine._detect_patterns(prepared)
        risk = self.engine._assess_risk(prepared, patterns)
        self.assertLessEqual(risk["score"], 100)

    def test_high_risk_level(self):
        """score>=80 → high。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 90, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        self.assertEqual(risk["level"], "high")

    def test_medium_risk_level(self):
        """50<=score<80 → medium。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 60, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        self.assertEqual(risk["level"], "medium")

    def test_low_risk_level(self):
        """score<50 → low。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 20, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        self.assertEqual(risk["level"], "low")

    def test_risk_boosted_by_high_severity_patterns(self):
        """高风险模式（LAYERING 等）加分。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 30, "transactions": [_tx("T1", 50000)],
        }})
        risk_no = self.engine._assess_risk(prepared, [])
        risk_yes = self.engine._assess_risk(prepared, [
            {"code": "LAYERING", "name": "快速分层"}])
        self.assertGreater(risk_yes["score"], risk_no["score"])

    def test_risk_boosted_by_large_amount(self):
        """总额>=100万 加 15 分。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 30,
            "transactions": [_tx("T1", 1500000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        self.assertGreaterEqual(risk["score"], 45)


class TestEngineConclusion(unittest.TestCase):
    """_generate_conclusion：结论与建议。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_conclusion_verdict_high(self):
        """high 风险 → 建议提交 SAR。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 90, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        conclusion = self.engine._generate_conclusion(prepared, risk, [])
        self.assertEqual(conclusion["verdict"], "建议提交 SAR")

    def test_conclusion_verdict_low(self):
        """low 风险 → 暂不建议提交。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 10, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        conclusion = self.engine._generate_conclusion(prepared, risk, [])
        self.assertIn("暂不建议", conclusion["verdict"])

    def test_conclusion_confidence_in_range(self):
        """置信度 ∈ [0, 1]。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 70, "transactions": [_tx("T1", 50000)],
            "trigger_reason": "异常",
        }})
        risk = self.engine._assess_risk(prepared, [])
        conclusion = self.engine._generate_conclusion(prepared, risk, ["SMURFING"])
        self.assertGreaterEqual(conclusion["confidence"], 0.0)
        self.assertLessEqual(conclusion["confidence"], 1.0)

    def test_conclusion_suggested_actions_nonempty(self):
        """建议行动列表非空。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 85, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        conclusion = self.engine._generate_conclusion(prepared, risk, [])
        self.assertGreater(len(conclusion["suggested_actions"]), 0)

    def test_conclusion_high_risk_has_four_actions(self):
        """high 风险建议含 4 条行动。"""
        prepared = self.engine._preprocess({"alert": {
            "risk_score": 90, "transactions": [_tx("T1", 50000)],
        }})
        risk = self.engine._assess_risk(prepared, [])
        conclusion = self.engine._generate_conclusion(prepared, risk, [])
        self.assertEqual(len(conclusion["suggested_actions"]), 4)


class TestEngineTemplateFill(unittest.TestCase):
    """_fill_template：多监管模板字段填充。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample()
        self.prepared = self.engine._preprocess(self.sample)

    def test_template_fields_populated(self):
        """CN-PBOC 模板字段全部生成。"""
        template = self.engine.model["templates"]["CN-PBOC"]
        narrative = self.engine._generate_5w1h(self.prepared)
        risk = self.engine._assess_risk(self.prepared, [])
        conclusion = self.engine._generate_conclusion(self.prepared, risk, [])
        filled = self.engine._fill_template(self.prepared, template, narrative, risk, conclusion)
        self.assertGreater(len(filled), 10)
        for name, field in filled.items():
            self.assertIn("section", field)
            self.assertIn("value", field)
            self.assertIn("is_mandatory", field)

    def test_mandatory_fields_flagged(self):
        """必填字段 is_mandatory=True。"""
        template = self.engine.model["templates"]["CN-PBOC"]
        narrative = self.engine._generate_5w1h(self.prepared)
        risk = self.engine._assess_risk(self.prepared, [])
        conclusion = self.engine._generate_conclusion(self.prepared, risk, [])
        filled = self.engine._fill_template(self.prepared, template, narrative, risk, conclusion)
        mandatory_names = template["mandatory"]
        self.assertTrue(any(filled[n]["is_mandatory"] for n in mandatory_names if n in filled))

    def test_narrative_filled_in_narrative_field(self):
        """US-FINCEN 的 narrative_detail 字段填入叙事。"""
        data = dict(self.sample)
        data["template_id"] = "US-FINCEN"
        prepared = self.engine._preprocess(data)
        template = self.engine.model["templates"]["US-FINCEN"]
        narrative = self.engine._generate_5w1h(prepared)
        risk = self.engine._assess_risk(prepared, [])
        conclusion = self.engine._generate_conclusion(prepared, risk, [])
        filled = self.engine._fill_template(prepared, template, narrative, risk, conclusion)
        self.assertEqual(filled["narrative_detail"]["value"], narrative)

    def test_subject_name_filled(self):
        """subject_name 字段填入客户姓名。"""
        template = self.engine.model["templates"]["CN-PBOC"]
        narrative = self.engine._generate_5w1h(self.prepared)
        risk = self.engine._assess_risk(self.prepared, [])
        conclusion = self.engine._generate_conclusion(self.prepared, risk, [])
        filled = self.engine._fill_template(self.prepared, template, narrative, risk, conclusion)
        self.assertEqual(filled["subject_name"]["value"], "张某")


class TestEngineQuality(unittest.TestCase):
    """_score_quality：质量评分。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample()
        self.prepared = self.engine._preprocess(self.sample)
        self.template = self.engine.model["templates"]["CN-PBOC"]
        self.narrative = self.engine._generate_5w1h(self.prepared)
        self.risk = self.engine._assess_risk(self.prepared, [])
        self.conclusion = self.engine._generate_conclusion(self.prepared, self.risk, [])
        self.filled = self.engine._fill_template(self.prepared, self.template, self.narrative, self.risk, self.conclusion)
        self.quality = self.engine._score_quality(self.prepared, self.template, self.filled, self.narrative)

    def test_total_score_in_range(self):
        """总分 ∈ [0, 100]。"""
        self.assertGreaterEqual(self.quality["total_score"], 0)
        self.assertLessEqual(self.quality["total_score"], 100)

    def test_grade_is_valid(self):
        """等级为优秀/良好/合格/不合格之一。"""
        self.assertIn(self.quality["grade"], ("优秀", "良好", "合格", "不合格"))

    def test_breakdown_four_categories(self):
        """评分明细含 4 大类。"""
        for k in ("completeness", "accuracy", "logic", "compliance"):
            self.assertIn(k, self.quality["breakdown"])

    def test_mandatory_fill_rate_in_range(self):
        """必填填充率 ∈ [0, 1]。"""
        self.assertGreaterEqual(self.quality["mandatory_fill_rate"], 0.0)
        self.assertLessEqual(self.quality["mandatory_fill_rate"], 1.0)

    def test_attachments_boost_completeness(self):
        """含附件 → 完整性 attachments 子项得满分。"""
        comp = self.quality["breakdown"]["completeness"]["sub_scores"]
        self.assertEqual(comp["attachments"], 10.0)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess / execute：完整报告生成。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample()
        self.result = self.engine.execute(self.sample)

    def test_status_generated(self):
        """状态为 generated。"""
        self.assertEqual(self.result["status"], "generated")

    def test_report_id_starts_with_sar(self):
        """report_id 以 SAR- 开头。"""
        self.assertTrue(self.result["report_id"].startswith("SAR-"))

    def test_submission_deadline_computed(self):
        """提交截止日 = 报告日 + 5 天（CN-PBOC）。"""
        self.assertEqual(self.result["submission_deadline"], "2025-06-20T08:00:00+00:00")

    def test_risk_level_is_high(self):
        """样本触发高风险。"""
        self.assertEqual(self.result["risk_level"], "high")

    def test_output_note_present(self):
        """输出备注非空。"""
        self.assertTrue(self.result["output_note"])

    def test_attachments_suggested_nonempty(self):
        """建议附件列表非空。"""
        self.assertGreater(len(self.result["attachments_suggested"]), 0)

    def test_suspicious_patterns_nonempty(self):
        """可疑模式列表非空。"""
        self.assertGreater(len(self.result["suspicious_patterns"]), 0)

    def test_template_info_regulator(self):
        """模板信息含监管机构。"""
        self.assertEqual(self.result["template"]["regulator"], "中国人民银行")

    def test_summary_tx_count(self):
        """摘要含交易笔数。"""
        self.assertEqual(self.result["summary"]["tx_count"], 8)

    def test_conclusion_verdict_submit(self):
        """结论为建议提交。"""
        self.assertEqual(self.result["conclusion"]["verdict"], "建议提交 SAR")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_transactions(self):
        """空交易列表也能生成报告。"""
        result = self.engine.execute({"alert": {"transactions": [], "risk_score": 10}})
        self.assertEqual(result["status"], "generated")
        self.assertEqual(result["summary"]["tx_count"], 0)

    def test_raw_alert_input(self):
        """裸告警（无 alert 键）也能处理。"""
        result = self.engine.execute({
            "transactions": [_tx("T1", 9500)],
            "risk_score": 30,
            "trigger_reason": "测试",
        })
        self.assertEqual(result["status"], "generated")

    def test_multiple_templates_execute(self):
        """多监管模板均可执行。"""
        for tid in ("US-FINCEN", "UK-NCA", "FATF-FIU", "HK-SG-FIU"):
            result = self.engine.execute({"template_id": tid, "alert": {
                "transactions": [_tx("T1", 9500)], "risk_score": 40,
            }})
            self.assertEqual(result["status"], "generated")
            self.assertEqual(result["template"]["name"],
                             self.engine.model["templates"][tid]["name"])

    def test_normalize_tx_handles_missing_fields(self):
        """交易缺字段时标准化不报错。"""
        from modules.co_06.engine import KGEngine as E
        t = E._normalize_tx({})
        self.assertEqual(t["amount"], 0)
        self.assertEqual(t["currency"], "CNY")

    def test_date_range_single(self):
        """单日期 date_range 返回该日期。"""
        from modules.co_06.engine import KGEngine as E
        self.assertEqual(E._date_range(["2025-06-10"]), "2025-06-10")

    def test_date_range_empty(self):
        """空日期 date_range 返回空串。"""
        from modules.co_06.engine import KGEngine as E
        self.assertEqual(E._date_range([]), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
