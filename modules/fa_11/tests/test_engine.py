"""[FA-11] engine 单测：可比公司法 Z-score / 历史趋势 / 成本加成 / 风险调整 / 综合评估。

unittest 风格（不依赖 pytest），覆盖 _load_model / _preprocess / _infer /
_postprocess 及核心工具方法。
"""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from modules.fa_11.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_engine() -> MLEngine:
    """构造 engine 并显式触发 _load_model（初始化行业容忍度）。"""
    eng = MLEngine("fa_11")
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：行业容忍度加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_industry_bias_loaded(self):
        """_load_model 后 _industry_bias 含制造/贸易/金融等关键行业。"""
        self.assertTrue(self.engine._industry_bias)
        for k in ("制造", "贸易", "金融", "房地产", "科技", "医药", "default"):
            self.assertIn(k, self.engine._industry_bias)

    def test_industry_bias_values_in_range(self):
        """行业容忍度取值 ∈ (0, 0.2]。"""
        for v in self.engine._industry_bias.values():
            self.assertGreater(v, 0.0)
            self.assertLessEqual(v, 0.2)

    def test_tolerance_default_constant(self):
        """TOLERANCE_DEFAULT = 0.10。"""
        self.assertEqual(MLEngine.TOLERANCE_DEFAULT, 0.10)

    def test_setup_returns_engine(self):
        """setup 返回 self，支持链式调用。"""
        eng = MLEngine("fa_11")
        self.assertIs(eng.setup(), eng)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据清洗与归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_preprocess_english_keys(self):
        """英文键 transactions/peers/history 正确解析。"""
        prepared = self.engine._preprocess({
            "transactions": [
                {"tx_id": "T1", "amount": 1000, "quantity": 10,
                 "unit_price": 100, "industry": "制造"},
            ],
            "peers": [{"price": 99, "industry": "制造"}],
            "history": [{"price": 95, "year": "2024"}],
        })
        self.assertEqual(len(prepared["transactions"]), 1)
        self.assertEqual(prepared["transactions"][0]["amount"], 1000.0)
        self.assertEqual(prepared["transactions"][0]["unit_price"], 100.0)
        self.assertEqual(len(prepared["peers"]), 1)
        self.assertEqual(prepared["peers"][0]["price"], 99.0)
        self.assertEqual(len(prepared["history"]), 1)

    def test_preprocess_chinese_keys(self):
        """中文键 交易/可比数据/历史价格 兼容。"""
        prepared = self.engine._preprocess({
            "交易": [{"id": "T1", "金额": "200", "单价": "50"}],
            "可比数据": [{"单价": 100}],
            "历史价格": [{"单价": 90, "year": "2023"}],
        })
        self.assertEqual(prepared["transactions"][0]["amount"], 200.0)
        self.assertEqual(prepared["transactions"][0]["unit_price"], 50.0)
        self.assertEqual(prepared["peers"][0]["price"], 100.0)
        self.assertEqual(prepared["history"][0]["price"], 90.0)

    def test_preprocess_amount_from_string(self):
        """金额字符串正确转 float（_f 容错）。"""
        prepared = self.engine._preprocess({
            "transactions": [{"amount": "1234.5"}],
        })
        self.assertEqual(prepared["transactions"][0]["amount"], 1234.5)

    def test_preprocess_invalid_amount_defaults_zero(self):
        """非法金额默认 0.0。"""
        prepared = self.engine._preprocess({
            "transactions": [{"amount": "N/A"}],
        })
        self.assertEqual(prepared["transactions"][0]["amount"], 0.0)

    def test_preprocess_non_dict_input(self):
        """非 dict 输入包装为 {transactions: data}。"""
        prepared = self.engine._preprocess([{"tx_id": "T1"}])
        self.assertEqual(len(prepared["transactions"]), 1)

    def test_preprocess_default_industry(self):
        """未指定行业默认 default。"""
        prepared = self.engine._preprocess({
            "transactions": [{"tx_id": "T1"}],
        })
        self.assertEqual(prepared["transactions"][0]["industry"], "default")


class TestEnginePeerStats(unittest.TestCase):
    """可比公司法：_peer_stats 统计。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_peer_stats_mean_and_std(self):
        """5 个可比价格 mean=100, std≈1.5811。"""
        peers = [{"price": p} for p in [98, 100, 102, 99, 101]]
        stats = self.engine._peer_stats(peers)
        self.assertEqual(stats["count"], 5)
        self.assertAlmostEqual(stats["mean"], 100.0, places=6)
        self.assertAlmostEqual(stats["std"], 1.5811388, places=4)

    def test_peer_stats_less_than_two(self):
        """不足 2 个可比样本：std=0。"""
        stats = self.engine._peer_stats([{"price": 100}])
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["std"], 0)
        self.assertEqual(stats["mean"], 100)

    def test_peer_stats_empty(self):
        """空可比列表：count=0, mean=0。"""
        stats = self.engine._peer_stats([])
        self.assertEqual(stats["count"], 0)
        self.assertEqual(stats["mean"], 0)

    def test_peer_stats_ignores_zero_prices(self):
        """价格为 0 的可比样本被忽略。"""
        stats = self.engine._peer_stats(
            [{"price": 0}, {"price": 100}, {"price": 102}]
        )
        self.assertEqual(stats["count"], 2)


class TestEngineHistStats(unittest.TestCase):
    """历史趋势：_hist_stats 统计。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_hist_stats_mean_and_std(self):
        """4 年历史价格 mean=99, std≈2.582。"""
        hist = [{"price": p} for p in [96, 98, 100, 102]]
        stats = self.engine._hist_stats(hist)
        self.assertEqual(stats["count"], 4)
        self.assertAlmostEqual(stats["mean"], 99.0, places=6)
        self.assertAlmostEqual(stats["std"], 2.5819888, places=4)

    def test_hist_stats_single_point(self):
        """单点历史：std=0。"""
        stats = self.engine._hist_stats([{"price": 100}])
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["std"], 0)


class TestEngineZScoreAndDeviation(unittest.TestCase):
    """Z-score 与偏离率工具。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_zscore_basic(self):
        """Z-score = (x - mean) / std。"""
        self.assertAlmostEqual(self.engine._zscore(110, 100, 5), 2.0, places=6)

    def test_zscore_zero_std(self):
        """std=0 → Z-score=0（避免除零）。"""
        self.assertEqual(self.engine._zscore(110, 100, 0), 0.0)

    def test_deviation_basic(self):
        """偏离率 = (price - mean) / mean。"""
        self.assertAlmostEqual(self.engine._deviation(120, 100), 0.2, places=6)

    def test_deviation_zero_mean(self):
        """mean=0 → 偏离率=0。"""
        self.assertEqual(self.engine._deviation(120, 0), 0.0)

    def test_f_parses_numbers(self):
        """_f 将数值/字符串转 float。"""
        self.assertEqual(self.engine._f(10), 10.0)
        self.assertEqual(self.engine._f("3.14"), 3.14)
        self.assertEqual(self.engine._f(None), 0.0)
        self.assertEqual(self.engine._f("abc"), 0.0)


class TestEngineEvaluate(unittest.TestCase):
    """_evaluate：综合评估（可比公司/历史/成本加成/风险调整）。"""

    def setUp(self):
        self.engine = _make_engine()
        self.peer_stats = {"count": 5, "mean": 100.0, "std": 1.5811388}
        self.hist_stats = {"count": 4, "mean": 99.0, "std": 2.5819888}

    def _tx(self, **over):
        base = {
            "tx_id": "T", "subject": "s", "amount": 1000.0, "quantity": 10,
            "unit_price": 100.0, "related_party": "rp",
            "ownership_pct": 0.3, "industry": "制造", "direction": "采购",
            "profit_margin": 0.15, "dependence": 0.2, "contract_ref": "",
        }
        base.update(over)
        return base

    def test_fair_when_price_at_mean(self):
        """价格等于可比均值 → fair（高评分）。"""
        tx = self._tx(unit_price=100.0, ownership_pct=0.3, dependence=0.2)
        level, score, methods = self.engine._evaluate(
            tx, 100.0, self.peer_stats, self.hist_stats
        )
        self.assertEqual(level, "fair")
        self.assertGreaterEqual(score, 0.8)
        self.assertIn("comparable_company", methods)
        self.assertIn("historical_trend", methods)
        self.assertIn("cost_plus", methods)

    def test_significantly_biased_when_large_deviation(self):
        """大幅偏离 → significantly_biased（评分低）。"""
        tx = self._tx(unit_price=135.0, ownership_pct=0.7, dependence=0.6)
        level, score, methods = self.engine._evaluate(
            tx, 135.0, self.peer_stats, self.hist_stats
        )
        self.assertEqual(level, "significantly_biased")
        self.assertLess(score, 0.55)

    def test_cost_plus_skipped_when_margin_zero(self):
        """profit_margin=0 → 不启用 cost_plus 方法。"""
        tx = self._tx(unit_price=100.0, profit_margin=0.0)
        level, score, methods = self.engine._evaluate(
            tx, 100.0, self.peer_stats, self.hist_stats
        )
        self.assertNotIn("cost_plus", methods)
        self.assertEqual(level, "fair")

    def test_no_methods_when_insufficient_data(self):
        """无可比/历史数据且无利润率 → methods 为空，score=0.5。"""
        tx = self._tx(unit_price=100.0, profit_margin=0.0)
        level, score, methods = self.engine._evaluate(
            tx, 100.0, {"count": 0, "mean": 0, "std": 0},
            {"count": 0, "mean": 0, "std": 0},
        )
        self.assertEqual(methods, {})
        self.assertAlmostEqual(score, 0.5, places=6)

    def test_risk_adjustment_reduces_score(self):
        """高持股比例/高依赖度 → 风险调整系数降低评分。"""
        tx_low = self._tx(unit_price=100.0, ownership_pct=0.0, dependence=0.0)
        tx_high = self._tx(unit_price=100.0, ownership_pct=1.0, dependence=1.0)
        _, s_low, _ = self.engine._evaluate(
            tx_low, 100.0, self.peer_stats, self.hist_stats
        )
        _, s_high, _ = self.engine._evaluate(
            tx_high, 100.0, self.peer_stats, self.hist_stats
        )
        self.assertLess(s_high, s_low)


class TestEngineTaxRiskAndSuggestion(unittest.TestCase):
    """_tax_risk / _suggestion。"""

    def setUp(self):
        self.engine = _make_engine()

    def _tx(self, **over):
        base = {"amount": 1000.0, "ownership_pct": 0.3}
        base.update(over)
        return base

    def test_tax_risk_high_for_large_significantly_biased(self):
        """significantly_biased + 金额>1000万 → high。"""
        self.assertEqual(
            self.engine._tax_risk("significantly_biased", self._tx(amount=15_000_000)),
            "high",
        )

    def test_tax_risk_medium_for_small_significantly_biased(self):
        """significantly_biased + 金额≤1000万 → medium。"""
        self.assertEqual(
            self.engine._tax_risk("significantly_biased", self._tx(amount=5_000_000)),
            "medium",
        )

    def test_tax_risk_medium_for_slightly_biased_high_ownership(self):
        """slightly_biased + 持股>50% → medium。"""
        self.assertEqual(
            self.engine._tax_risk("slightly_biased", self._tx(ownership_pct=0.6)),
            "medium",
        )

    def test_tax_risk_low_for_fair(self):
        """fair → low。"""
        self.assertEqual(
            self.engine._tax_risk("fair", self._tx()), "low"
        )

    def test_suggestion_fair(self):
        """fair 建议保留原合同。"""
        self.assertIn("保留原合同", self.engine._suggestion("fair", self._tx()))

    def test_suggestion_significantly_biased(self):
        """significantly_biased 建议调整至公允区间。"""
        s = self.engine._suggestion("significantly_biased", self._tx())
        self.assertIn("调整", s)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：汇总与统计。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_fixture("sample_input.json")
        self.result = self.engine.execute(self.sample)

    def test_result_has_items_and_summary(self):
        """输出含 items / summary / adjustment_suggestions。"""
        self.assertIn("items", self.result)
        self.assertIn("summary", self.result)
        self.assertIn("adjustment_suggestions", self.result)

    def test_summary_total_transactions(self):
        """summary.total_transactions = 5。"""
        self.assertEqual(self.result["summary"]["total_transactions"], 5)

    def test_summary_fairness_distribution(self):
        """公允分布：fair=2 / slightly_biased=1 / significantly_biased=2。"""
        dist = self.result["summary"]["fairness_distribution"]
        self.assertEqual(dist.get("fair", 0), 2)
        self.assertEqual(dist.get("slightly_biased", 0), 1)
        self.assertEqual(dist.get("significantly_biased", 0), 2)

    def test_summary_tax_risk_distribution(self):
        """税务风险分布：high=1 / medium=1 / low=3。"""
        dist = self.result["summary"]["tax_risk_distribution"]
        self.assertEqual(dist.get("high", 0), 1)
        self.assertEqual(dist.get("medium", 0), 1)
        self.assertEqual(dist.get("low", 0), 3)

    def test_summary_fair_rate(self):
        """fair_rate = 2/5 = 0.4。"""
        self.assertAlmostEqual(
            self.result["summary"]["fair_rate"], 0.4, places=3
        )

    def test_adjustment_suggestions_exclude_fair(self):
        """调整建议仅含非 fair 交易（3 条）。"""
        suggestions = self.result["adjustment_suggestions"]
        self.assertEqual(len(suggestions), 3)
        tx_ids = {s["tx_id"] for s in suggestions}
        self.assertNotIn("RP-001", tx_ids)
        self.assertNotIn("RP-004", tx_ids)

    def test_biased_amount_excludes_fair(self):
        """biased_amount = 非 fair 交易金额合计。"""
        expected = 1537500.0 + 15000000.0 + 5000000.0
        self.assertAlmostEqual(
            self.result["summary"]["biased_amount"], expected, places=2
        )

    def test_critical_biased_amount_only_significant(self):
        """critical_biased_amount = significantly_biased 金额合计。"""
        expected = 15000000.0 + 5000000.0
        self.assertAlmostEqual(
            self.result["summary"]["critical_biased_amount"], expected, places=2
        )


class TestEngineFixtureConsistency(unittest.TestCase):
    """与 expected_output.json 一致性。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_fixture("sample_input.json")
        self.expected = _load_fixture("expected_output.json")

    def test_items_count_matches_expected(self):
        """engine 输出交易数与 expected 一致（5）。"""
        result = self.engine.execute(self.sample)
        self.assertEqual(len(result["items"]), len(self.expected["items"]))

    def test_tx_ids_match_expected(self):
        """交易 ID 顺序与 expected 一致。"""
        result = self.engine.execute(self.sample)
        got = [i["tx_id"] for i in result["items"]]
        want = [i["tx_id"] for i in self.expected["items"]]
        self.assertEqual(got, want)

    def test_fairness_levels_match_expected(self):
        """每笔交易 fairness_level 与 expected 一致。"""
        result = self.engine.execute(self.sample)
        for got, want in zip(result["items"], self.expected["items"]):
            self.assertEqual(got["fairness_level"], want["fairness_level"])
            self.assertEqual(got["tax_risk_level"], want["tax_risk_level"])

    def test_deviation_rates_match_expected(self):
        """每笔交易 deviation_rate 与 expected 一致。"""
        result = self.engine.execute(self.sample)
        for got, want in zip(result["items"], self.expected["items"]):
            self.assertAlmostEqual(
                got["deviation_rate"], want["deviation_rate"], places=4
            )


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_input(self):
        """空输入 → 0 交易。"""
        result = self.engine.execute({"transactions": []})
        self.assertEqual(result["summary"]["total_transactions"], 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["adjustment_suggestions"], [])

    def test_no_peers_no_history(self):
        """无可比/历史数据 → 仍能给出评估（methods 可能为空）。"""
        result = self.engine.execute({
            "transactions": [
                {"tx_id": "T1", "unit_price": 100, "amount": 1000,
                 "profit_margin": 0.1, "ownership_pct": 0.2, "dependence": 0.1},
            ],
        })
        self.assertEqual(len(result["items"]), 1)
        self.assertIn(result["items"][0]["fairness_level"],
                      {"fair", "slightly_biased", "significantly_biased"})

    def test_unit_price_derived_from_amount_quantity(self):
        """未给 unit_price 时由 amount/quantity 推导。"""
        result = self.engine.execute({
            "transactions": [
                {"tx_id": "T1", "amount": 1000, "quantity": 10,
                 "profit_margin": 0.0, "ownership_pct": 0.0, "dependence": 0.0},
            ],
            "peers": [{"price": 100}, {"price": 102}, {"price": 98}],
        })
        self.assertEqual(result["items"][0]["unit_price"], 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
