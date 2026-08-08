"""[FA-08] engine 单测：跨表勾稽 / 凭证匹配 / 异常波动 / 后处理汇总。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_08.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine():
    """构造已加载规则的 engine。"""
    eng = MLEngine()
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：规则库加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_rules_loaded(self):
        """_load_model 后 self._rules 非空。"""
        self.assertGreater(len(self.engine._rules), 0)

    def test_consistency_rules_count(self):
        """CONSISTENCY_RULES 含 7 条规则。"""
        self.assertEqual(len(MLEngine.CONSISTENCY_RULES), 7)

    def test_anomaly_threshold(self):
        """ANOMALY_THRESHOLD = 0.3。"""
        self.assertAlmostEqual(MLEngine.ANOMALY_THRESHOLD, 0.3)

    def test_rules_are_tuples(self):
        """每条规则为 (rule_id, desc, checker) 三元组。"""
        for rule in self.engine._rules:
            self.assertEqual(len(rule), 3)
            self.assertIsInstance(rule[0], str)
            self.assertIsInstance(rule[1], str)
            self.assertTrue(callable(rule[2]))


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_dict_input_english_keys(self):
        """英文键正常解析。"""
        prepared = self.engine._preprocess({
            "workpapers": [{"id": "WP1"}],
            "statements": {"trial_balance": {"debit": 1, "credit": 1}},
            "vouchers": [],
            "metrics": [],
        })
        self.assertEqual(len(prepared["workpapers"]), 1)
        self.assertIn("trial_balance", prepared["statements"])

    def test_dict_input_chinese_keys(self):
        """中文键（底稿/报表/凭证/指标）正常解析。"""
        prepared = self.engine._preprocess({
            "底稿": [{"id": "WP1"}],
            "报表": {"trial_balance": {"debit": 1, "credit": 1}},
            "凭证": [],
            "指标": [],
        })
        self.assertEqual(len(prepared["workpapers"]), 1)
        self.assertIn("trial_balance", prepared["statements"])

    def test_list_input_wraps_as_workpapers(self):
        """裸 list 输入包装为 workpapers。"""
        prepared = self.engine._preprocess([{"id": "WP1"}, {"id": "WP2"}])
        self.assertEqual(len(prepared["workpapers"]), 2)

    def test_none_input(self):
        """None 输入返回空结构。"""
        prepared = self.engine._preprocess(None)
        self.assertEqual(prepared["workpapers"], [])
        self.assertEqual(prepared["statements"], {})
        self.assertEqual(prepared["vouchers"], [])
        # engine 默认 metrics 为 {} (data.get("metrics", data.get("指标", {})))
        self.assertEqual(prepared["metrics"], {})

    def test_non_dict_input_wraps(self):
        """非 dict 输入包装为 workpapers。"""
        prepared = self.engine._preprocess("raw_string")
        self.assertEqual(prepared["workpapers"], "raw_string")


class TestEngineConsistencyRules(unittest.TestCase):
    """CONSISTENCY_RULES 各规则 PASS / FAIL。"""

    def setUp(self):
        self.engine = _make_engine()

    def _check_rule(self, rule_id, payload):
        """执行单条规则并返回该规则的结果项。"""
        result = self.engine.execute({"statements": {rule_id: payload}})
        return next(i for i in result["items"] if i["check_id"] == rule_id)

    def test_trial_balance_pass(self):
        """借贷平衡 → PASS。"""
        item = self._check_rule("trial_balance", {"debit": 1000, "credit": 1000})
        self.assertEqual(item["status"], "PASS")

    def test_trial_balance_fail(self):
        """借贷不平衡 → FAIL, severity=medium。"""
        item = self._check_rule("trial_balance", {"debit": 1000, "credit": 900})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["severity"], "medium")
        self.assertAlmostEqual(item["diff_amount"], 100.0)

    def test_balance_sheet_pass(self):
        """资产=负债+权益 → PASS。"""
        item = self._check_rule("balance_sheet",
                                {"assets": 1000, "liabilities": 400, "equity": 600})
        self.assertEqual(item["status"], "PASS")

    def test_balance_sheet_fail(self):
        """资产≠负债+权益 → FAIL, severity=high。"""
        item = self._check_rule("balance_sheet",
                                {"assets": 1000, "liabilities": 400, "equity": 500})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["severity"], "high")

    def test_cash_flow_pass(self):
        """现金流量期末=资产负债现金 → PASS。"""
        item = self._check_rule("cash_flow", {"cf_ending_cash": 500, "bs_cash": 500})
        self.assertEqual(item["status"], "PASS")

    def test_cash_flow_fail(self):
        """现金流不一致 → FAIL, severity=high。"""
        item = self._check_rule("cash_flow", {"cf_ending_cash": 500, "bs_cash": 480})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["severity"], "high")

    def test_retained_earnings_pass(self):
        """未分配利润勾稽 → PASS。"""
        item = self._check_rule("retained_earnings",
                                {"ending_re": 500, "begin_re": 300,
                                 "net_profit": 300, "dividend": 100})
        self.assertEqual(item["status"], "PASS")

    def test_retained_earnings_fail(self):
        """未分配利润不一致 → FAIL, severity=high。"""
        item = self._check_rule("retained_earnings",
                                {"ending_re": 500, "begin_re": 300,
                                 "net_profit": 100, "dividend": 100})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["severity"], "high")

    def test_inventory_pass(self):
        """存货勾稽 → PASS。"""
        item = self._check_rule("inventory",
                                {"inventory_total": 1000, "raw": 400,
                                 "wip": 300, "fg": 300})
        self.assertEqual(item["status"], "PASS")

    def test_inventory_fail(self):
        """存货不一致 → FAIL, severity=medium。"""
        item = self._check_rule("inventory",
                                {"inventory_total": 1000, "raw": 400,
                                 "wip": 300, "fg": 200})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["severity"], "medium")

    def test_depreciation_pass(self):
        """折旧勾稽 → PASS。"""
        item = self._check_rule("depreciation",
                                {"dep_ending": 800, "dep_begin": 600,
                                 "dep_add": 300, "dep_dispose": 100})
        self.assertEqual(item["status"], "PASS")

    def test_payroll_pass(self):
        """薪酬勾稽 → PASS。"""
        item = self._check_rule("payroll",
                                {"pay_ending": 200, "pay_begin": 150,
                                 "pay_accrue": 100, "pay_paid": 50})
        self.assertEqual(item["status"], "PASS")

    def test_payroll_fail(self):
        """薪酬不一致 → FAIL, severity=medium。"""
        item = self._check_rule("payroll",
                                {"pay_ending": 200, "pay_begin": 150,
                                 "pay_accrue": 100, "pay_paid": 80})
        self.assertEqual(item["status"], "FAIL")
        self.assertEqual(item["severity"], "medium")


class TestEngineVoucherMatching(unittest.TestCase):
    """底稿 ↔ 凭证金额一致性。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_voucher_match_no_fail(self):
        """底稿与凭证金额一致 → 不产生 cross_doc FAIL。"""
        result = self.engine.execute({
            "workpapers": [{"id": "WP1", "amount": 1000}],
            "vouchers": [{"workpaper_id": "WP1", "amount": 1000}],
        })
        cross = [i for i in result["items"] if i["type"] == "cross_doc"]
        self.assertEqual(len(cross), 0)

    def test_voucher_mismatch_fail(self):
        """底稿与凭证金额不一致 → cross_doc FAIL, severity=high。"""
        result = self.engine.execute({
            "workpapers": [{"id": "WP1", "amount": 1000}],
            "vouchers": [{"workpaper_id": "WP1", "amount": 800}],
        })
        cross = [i for i in result["items"] if i["type"] == "cross_doc"]
        self.assertEqual(len(cross), 1)
        self.assertEqual(cross[0]["status"], "FAIL")
        self.assertEqual(cross[0]["severity"], "high")
        self.assertAlmostEqual(cross[0]["diff_amount"], -200.0)

    def test_voucher_no_workpaper_skip(self):
        """凭证 workpaper_id 不在底稿中 → 跳过。"""
        result = self.engine.execute({
            "workpapers": [{"id": "WP1", "amount": 1000}],
            "vouchers": [{"workpaper_id": "WP999", "amount": 9999}],
        })
        cross = [i for i in result["items"] if i["type"] == "cross_doc"]
        self.assertEqual(len(cross), 0)


class TestEngineAnomalyDetection(unittest.TestCase):
    """异常波动检测。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_anomaly_volatility(self):
        """同比波动 > 30% → anomaly FAIL, severity=medium。"""
        result = self.engine.execute({
            "metrics": [{"name": "收入", "current": 150, "previous": 100}],
        })
        anomalies = [i for i in result["items"] if i["type"] == "anomaly"]
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["severity"], "medium")
        self.assertAlmostEqual(anomalies[0]["change_pct"], 0.5)

    def test_anomaly_new_appear(self):
        """前期为 0 本期非 0 → new_appear, severity=high。"""
        result = self.engine.execute({
            "metrics": [{"name": "新增科目", "current": 500, "previous": 0}],
        })
        anomalies = [i for i in result["items"] if i["type"] == "anomaly"]
        self.assertEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["severity"], "high")

    def test_no_anomaly_under_threshold(self):
        """波动 ≤ 30% → 不产生异常。"""
        result = self.engine.execute({
            "metrics": [{"name": "收入", "current": 120, "previous": 100}],
        })
        anomalies = [i for i in result["items"] if i["type"] == "anomaly"]
        self.assertEqual(len(anomalies), 0)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：汇总 / 通过率 / 严重度分布。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample()
        self.result = self.engine.execute(self.sample)

    def test_summary_keys(self):
        """summary 含必要键。"""
        summary = self.result["summary"]
        for key in ("total_checks", "pass_count", "fail_count",
                    "pass_rate", "severity_distribution", "total_diff_amount"):
            self.assertIn(key, summary)

    def test_pass_rate_calculation(self):
        """pass_rate = pass_count / total_checks。"""
        summary = self.result["summary"]
        expected = round(summary["pass_count"] / max(1, summary["total_checks"]), 3)
        self.assertAlmostEqual(summary["pass_rate"], expected)

    def test_total_checks_consistency(self):
        """total_checks = pass_count + fail_count。"""
        summary = self.result["summary"]
        self.assertEqual(
            summary["total_checks"],
            summary["pass_count"] + summary["fail_count"],
        )

    def test_severity_distribution_only_fails(self):
        """severity_distribution 仅统计 FAIL 项。"""
        summary = self.result["summary"]
        fail_count = summary["fail_count"]
        sev_sum = sum(summary["severity_distribution"].values())
        self.assertEqual(sev_sum, fail_count)

    def test_critical_issues_are_high(self):
        """critical_issues 全部为 high 严重度。"""
        for c in self.result["critical_issues"]:
            self.assertEqual(c["severity"], "high")

    def test_adjustment_suggestions_for_consistency(self):
        """adjustment_suggestions 含 consistency 类型 FAIL。"""
        tips = self.result["adjustment_suggestions"]
        self.assertGreater(len(tips), 0)
        for t in tips:
            self.assertIn("issue", t)
            self.assertIn("action", t)

    def test_total_diff_amount_non_negative(self):
        """total_diff_amount ≥ 0。"""
        self.assertGreaterEqual(self.result["summary"]["total_diff_amount"], 0)


class TestEngineExecute(unittest.TestCase):
    """execute 全流程集成。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample()

    def test_execute_returns_dict(self):
        """execute 返回 dict 结构。"""
        result = self.engine.execute(self.sample)
        self.assertIsInstance(result, dict)
        self.assertIn("items", result)
        self.assertIn("summary", result)

    def test_execute_sample_has_fails(self):
        """sample_input 含失败项（balance_sheet / cash_flow 不一致）。"""
        result = self.engine.execute(self.sample)
        fails = [i for i in result["items"] if i["status"] == "FAIL"]
        self.assertGreater(len(fails), 0)

    def test_execute_sample_has_passes(self):
        """sample_input 含通过项（trial_balance / retained_earnings 等）。"""
        result = self.engine.execute(self.sample)
        passes = [i for i in result["items"] if i["status"] == "PASS"]
        self.assertGreater(len(passes), 0)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_input(self):
        """空输入 → 7 条 PASS, 0 FAIL, pass_rate=1.0。"""
        result = self.engine.execute({})
        self.assertEqual(result["summary"]["fail_count"], 0)
        self.assertEqual(result["summary"]["pass_count"], 7)
        self.assertAlmostEqual(result["summary"]["pass_rate"], 1.0)

    def test_missing_statement_fields(self):
        """statements 缺失某规则 → 该规则 payload={} → 全 0 → PASS。"""
        result = self.engine.execute({"statements": {}})
        # 7 条规则全部 PASS（空 payload → 0=0）
        self.assertEqual(result["summary"]["pass_count"], 7)
        self.assertEqual(result["summary"]["fail_count"], 0)

    def test_zero_values_pass(self):
        """全零值 → 所有规则 PASS。"""
        result = self.engine.execute({
            "statements": {
                "trial_balance": {"debit": 0, "credit": 0},
                "balance_sheet": {"assets": 0, "liabilities": 0, "equity": 0},
            }
        })
        self.assertEqual(result["summary"]["fail_count"], 0)

    def test_no_vouchers_no_metrics(self):
        """无凭证无指标 → 仅 consistency 检查。"""
        result = self.engine.execute({
            "statements": {"trial_balance": {"debit": 100, "credit": 100}},
        })
        # 7 条 consistency 规则全 PASS
        self.assertEqual(result["summary"]["total_checks"], 7)
        self.assertEqual(result["summary"]["fail_count"], 0)

    def test_metric_negative_change(self):
        """指标下降 > 30% → 异常（负 pct）。"""
        result = self.engine.execute({
            "metrics": [{"name": "利润", "current": 60, "previous": 100}],
        })
        anomalies = [i for i in result["items"] if i["type"] == "anomaly"]
        self.assertEqual(len(anomalies), 1)
        self.assertLess(anomalies[0]["change_pct"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
