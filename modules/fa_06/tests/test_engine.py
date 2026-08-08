"""[FA-06] engine 单测：差异检测 / 分类 / 严重等级 / 根因分析 / 审计建议 / 取证。

unittest 风格（不依赖 pytest），纯 stdlib。
"""
from __future__ import annotations

import unittest

from modules.fa_06.engine import KGEngine


def _make_engine() -> KGEngine:
    """构造已加载模型的 engine。"""
    eng = KGEngine()
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：差异容忍率规则库 + 差异模式正则编译。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_tolerance_rules_loaded(self):
        """容忍率规则库加载（含 default 与多个科目）。"""
        self.assertGreater(len(self.engine._rules), 5)
        self.assertIn("default", self.engine._rules)
        self.assertIn("银行存款", self.engine._rules)

    def test_patterns_compiled(self):
        """差异模式正则已编译（每类为 re.Pattern 列表）。"""
        import re
        self.assertGreater(len(self.engine._patterns), 3)
        for _label, pats in self.engine._patterns:
            for p in pats:
                self.assertIsInstance(p, re.Pattern)

    def test_tolerance_subject_match(self):
        """_tolerance 按科目名包含匹配：银行存款-工商银行 → 0.005。"""
        self.assertAlmostEqual(self.engine._tolerance("银行存款-工商银行"), 0.005)
        self.assertAlmostEqual(self.engine._tolerance("应收账款"), 0.02)
        self.assertAlmostEqual(self.engine._tolerance("应付账款"), 0.02)
        self.assertAlmostEqual(self.engine._tolerance("存货"), 0.015)

    def test_tolerance_default(self):
        """未知科目回退 default=0.01。"""
        self.assertAlmostEqual(self.engine._tolerance("其他应收款"), 0.01)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_diff_and_abs_diff_computed(self):
        """diff = reply - book，abs_diff = |diff|。"""
        prepared = self.engine._preprocess([
            {"item_id": "T1", "subject": "银行存款", "book_amount": 1000,
             "reply_amount": 1200, "book_text": "a", "reply_text": "b"},
        ])
        self.assertEqual(prepared[0]["diff"], 200.0)
        self.assertEqual(prepared[0]["abs_diff"], 200.0)

    def test_chinese_keys_supported(self):
        """支持中文键名（科目/账面金额/回函金额）。"""
        prepared = self.engine._preprocess([
            {"id": "T1", "科目": "应收账款", "账面金额": 500,
             "回函金额": 450, "账面描述": "x", "回函描述": "y"},
        ])
        self.assertEqual(prepared[0]["subject"], "应收账款")
        self.assertEqual(prepared[0]["book_amount"], 500.0)
        self.assertEqual(prepared[0]["diff"], -50.0)

    def test_to_float_robust(self):
        """_to_float 对非数值返回 0.0。"""
        self.assertEqual(KGEngine._to_float("abc"), 0.0)
        self.assertEqual(KGEngine._to_float(None), 0.0)
        self.assertEqual(KGEngine._to_float("123.45"), 123.45)

    def test_safe_pct_zero_base(self):
        """_safe_pct 基数为 0 时返回 0.0。"""
        self.assertEqual(KGEngine._safe_pct(100, 0), 0.0)
        self.assertAlmostEqual(KGEngine._safe_pct(100, 200), 0.5)

    def test_ensure_list(self):
        """_ensure_list：None→[]，单 dict→[dict]，list 透传。"""
        self.assertEqual(KGEngine._ensure_list(None), [])
        d = {"a": 1}
        self.assertEqual(KGEngine._ensure_list(d), [d])
        lst = [1, 2]
        self.assertEqual(KGEngine._ensure_list(lst), lst)


class TestEngineClassify(unittest.TestCase):
    """_classify / _infer：差异分类（5 大类）。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_timing_difference_classified(self):
        """在途 + 容忍率内 → 时间性差异。"""
        item = self.engine._preprocess([{
            "item_id": "T1", "subject": "银行存款-工商银行",
            "book_amount": 1000000, "reply_amount": 1004000,
            "book_text": "账面余额", "reply_text": "在途资金4000",
            "materiality": 50000,
        }])[0]
        cat, score, reasons = self.engine._classify(item)
        self.assertEqual(cat, "时间性差异")
        self.assertIn("在途", reasons)
        self.assertGreater(score, 0.0)

    def test_fraud_risk_classified(self):
        """隐瞒关键词 → 舞弊风险。"""
        item = self.engine._preprocess([{
            "item_id": "T2", "subject": "应收账款",
            "book_amount": 500000, "reply_amount": 400000,
            "book_text": "应收货款", "reply_text": "客户隐瞒收入",
            "materiality": 50000,
        }])[0]
        cat, _score, reasons = self.engine._classify(item)
        self.assertEqual(cat, "舞弊风险")
        self.assertIn("隐瞒", reasons)

    def test_processing_error_classified(self):
        """重记关键词 → 记账差错。"""
        item = self.engine._preprocess([{
            "item_id": "T3", "subject": "应付账款",
            "book_amount": 300000, "reply_amount": 330000,
            "book_text": "应付货款", "reply_text": "重记手续费",
            "materiality": 50000,
        }])[0]
        cat, _score, reasons = self.engine._classify(item)
        self.assertEqual(cat, "记账差错")
        self.assertIn("重记", reasons)

    def test_writeoff_classified(self):
        """坏账/核销/跌价 → 减值/核销。"""
        item = self.engine._preprocess([{
            "item_id": "T4", "subject": "存货",
            "book_amount": 800000, "reply_amount": 750000,
            "book_text": "存货成本", "reply_text": "存货跌价核销坏账",
            "materiality": 50000,
        }])[0]
        cat, _score, reasons = self.engine._classify(item)
        self.assertEqual(cat, "减值/核销")
        self.assertTrue(any(r in reasons for r in ("跌价", "坏账", "核销")))

    def test_exchange_classified(self):
        """汇兑/期末调汇 → 汇兑/利息。"""
        item = self.engine._preprocess([{
            "item_id": "T5", "subject": "收入",
            "book_amount": 1200000, "reply_amount": 1212000,
            "book_text": "营业收入", "reply_text": "期末调汇汇兑差额",
            "materiality": 50000,
        }])[0]
        cat, _score, reasons = self.engine._classify(item)
        self.assertEqual(cat, "汇兑/利息")
        self.assertTrue(any(r in reasons for r in ("汇兑", "期末调汇")))

    def test_confidence_in_range(self):
        """confidence ∈ [0, 1]。"""
        item = self.engine._preprocess([{
            "item_id": "T6", "subject": "银行存款",
            "book_amount": 1000, "reply_amount": 1000,
            "book_text": "a", "reply_text": "a", "materiality": 100,
        }])[0]
        _cat, score, _reasons = self.engine._classify(item)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestEngineSeverity(unittest.TestCase):
    """_severity：严重等级判定。"""

    def setUp(self):
        self.engine = _make_engine()

    def _item(self, diff, book, mat, subject="其他", cat="记账差错"):
        return {
            "subject": subject, "book_amount": book, "reply_amount": book + diff,
            "diff": diff, "abs_diff": abs(diff), "materiality": mat,
            "book_text": "", "reply_text": "",
        }

    def test_fraud_risk_critical(self):
        """舞弊风险 + pct_of_mat > 0.1 → critical。"""
        it = self._item(6000, 100000, 50000, cat="舞弊风险")
        self.assertEqual(self.engine._severity(it, "舞弊风险"), "critical")

    def test_fraud_risk_high(self):
        """舞弊风险 + pct_of_mat <= 0.1 → high。"""
        it = self._item(100, 100000, 50000, cat="舞弊风险")
        self.assertEqual(self.engine._severity(it, "舞弊风险"), "high")

    def test_critical_when_over_half_materiality(self):
        """非舞弊 + pct_of_mat > 0.5 → critical。"""
        it = self._item(30000, 100000, 50000)
        self.assertEqual(self.engine._severity(it, "记账差错"), "critical")

    def test_high_when_over_10pct_materiality(self):
        """pct_of_mat > 0.1 → high。"""
        it = self._item(6000, 100000, 50000)
        self.assertEqual(self.engine._severity(it, "记账差错"), "high")

    def test_medium_when_over_2pct_materiality(self):
        """pct_of_mat > 0.02 → medium。"""
        it = self._item(1500, 100000, 50000)
        self.assertEqual(self.engine._severity(it, "记账差错"), "medium")

    def test_low_for_tiny_diff(self):
        """pct_of_mat <= 0.02 → low。"""
        it = self._item(100, 100000, 50000)
        self.assertEqual(self.engine._severity(it, "记账差错"), "low")


class TestEngineForensics(unittest.TestCase):
    """_forensics：底稿取证点。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_bank_forensics(self):
        """银行存款 → 获取对账单 + 亲自发函。"""
        item = {"subject": "银行存款", "diff": 0, "direction": ""}
        tips = self.engine._forensics(item)
        self.assertIn("获取银行对账单原件", tips)
        self.assertIn("执行亲自发函控制", tips)

    def test_receivable_forensics(self):
        """应收账款 → 核对期后收付款凭证。"""
        item = {"subject": "应收账款", "diff": 0, "direction": ""}
        tips = self.engine._forensics(item)
        self.assertIn("核对期后收付款凭证", tips)

    def test_direction_anomaly(self):
        """借方 + 正差异 → 关注方向异常。"""
        item = {"subject": "银行存款", "diff": 100, "direction": "借"}
        tips = self.engine._forensics(item)
        self.assertIn("关注方向异常", tips)


class TestEngineExecuteAndPostprocess(unittest.TestCase):
    """execute / _postprocess：端到端 + 汇总。"""

    def setUp(self):
        self.engine = _make_engine()
        self.data = [
            {"item_id": "E1", "subject": "银行存款-工商银行",
             "book_amount": 1000000, "reply_amount": 1004000,
             "book_text": "账面余额", "reply_text": "在途资金4000",
             "direction": "借", "materiality": 50000},
            {"item_id": "E2", "subject": "应收账款",
             "book_amount": 500000, "reply_amount": 400000,
             "book_text": "应收货款", "reply_text": "客户隐瞒收入",
             "direction": "借", "materiality": 50000},
            {"item_id": "E3", "subject": "固定资产",
             "book_amount": 2000000, "reply_amount": 2000000,
             "book_text": "设备原值", "reply_text": "设备原值一致",
             "direction": "借", "materiality": 50000},
        ]
        self.result = self.engine.execute(self.data)

    def test_items_count(self):
        """输出项数 = 输入记录数。"""
        self.assertEqual(len(self.result["items"]), 3)

    def test_item_fields_populated(self):
        """每项含 diff/category/severity/audit_advice/forensics。"""
        for it in self.result["items"]:
            self.assertIn("diff", it)
            self.assertIn("abs_diff", it)
            self.assertIn("category", it)
            self.assertIn("severity", it)
            self.assertIn("audit_advice", it)
            self.assertIn("forensics", it)
            self.assertIn("tolerance_pct", it)

    def test_summary_fields(self):
        """summary 含 total_items/has_diff_count/分布/high_risk。"""
        s = self.result["summary"]
        self.assertEqual(s["total_items"], 3)
        self.assertIn("category_distribution", s)
        self.assertIn("severity_distribution", s)
        self.assertIn("total_abs_diff_amount", s)
        self.assertIn("high_risk_count", s)
        self.assertIn("high_risk_ids", s)

    def test_high_risk_includes_fraud(self):
        """舞弊风险项（E2）在 high_risk_ids 中。"""
        self.assertIn("E2", self.result["summary"]["high_risk_ids"])

    def test_workpaper_todo_for_high_risk(self):
        """高危项生成底稿待办。"""
        todos = self.result["workpaper_todo"]
        ids = [t["item_id"] for t in todos]
        self.assertIn("E2", ids)

    def test_valid_categories(self):
        """分类在 5 大类中。"""
        valid = {"时间性差异", "记账差错", "舞弊风险", "减值/核销", "汇兑/利息"}
        for it in self.result["items"]:
            self.assertIn(it["category"], valid)

    def test_valid_severity(self):
        """严重等级在 critical/high/medium/low 中。"""
        valid = {"critical", "high", "medium", "low"}
        for it in self.result["items"]:
            self.assertIn(it["severity"], valid)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_list(self):
        """空列表 → 0 项。"""
        result = self.engine.execute([])
        self.assertEqual(result["summary"]["total_items"], 0)
        self.assertEqual(result["items"], [])

    def test_none_input(self):
        """None 输入 → 0 项。"""
        result = self.engine.execute(None)
        self.assertEqual(result["summary"]["total_items"], 0)

    def test_single_dict_input(self):
        """单 dict 输入（_ensure_list 包装为 1 项）。"""
        result = self.engine.execute({
            "item_id": "S1", "subject": "银行存款",
            "book_amount": 1000, "reply_amount": 1000,
            "book_text": "a", "reply_text": "a",
        })
        self.assertEqual(result["summary"]["total_items"], 1)

    def test_zero_book_amount(self):
        """账面金额为 0 → diff_pct=0（不除零）。"""
        result = self.engine.execute([{
            "item_id": "Z1", "subject": "其他", "book_amount": 0,
            "reply_amount": 100, "book_text": "a", "reply_text": "b",
        }])
        self.assertEqual(result["items"][0]["diff_pct"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
