"""[CO-04] engine 单测：五模式可疑交易检测 / 风险评分 / 告警汇总。

unittest 风格（不依赖 pytest），覆盖：
  * 模型加载 (_load_model)
  * 预处理 (_preprocess)
  * 模式 ① 结构化交易 Smurfing
  * 模式 ② 快速往返 Round-trip
  * 模式 ③ 高风险地区
  * 模式 ④ 大额现金
  * 模式 ⑤ 非工作时段密集交易
  * 风险评分与排序
  * 后处理 summary 汇总
  * 边界情况
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_04.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：模型参数加载。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_model_has_report_threshold(self):
        """模型含 report_threshold（默认 50000）。"""
        self.assertEqual(self.engine.model["report_threshold"], 50000)

    def test_model_has_smurf_ratio(self):
        """模型含 smurf_ratio（默认 0.9）。"""
        self.assertAlmostEqual(self.engine.model["smurf_ratio"], 0.9)

    def test_model_has_cash_threshold(self):
        """模型含 cash_threshold（默认 200000）。"""
        self.assertEqual(self.engine.model["cash_threshold"], 200000)

    def test_model_has_high_risk_jurisdictions(self):
        """模型含高风险地区清单。"""
        jurisdictions = self.engine.model["high_risk_jurisdictions"]
        self.assertIn("IRAN", jurisdictions)
        self.assertIn("NK", jurisdictions)
        self.assertIn("SYRIA", jurisdictions)

    def test_config_overrides_report_threshold(self):
        """config.threshold.report 可覆盖报告阈值。"""
        eng = KGEngine(config={"threshold": {"report": 100000}})
        eng.setup()
        self.assertEqual(eng.model["report_threshold"], 100000.0)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入归一化。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_preprocess_dict_with_transactions(self):
        """dict 含 transactions → 返回交易列表。"""
        prepared = self.engine._preprocess(
            {"transactions": [{"tx_id": "T1"}]}
        )
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["tx_id"], "T1")

    def test_preprocess_bare_list(self):
        """裸 list 输入 → 直接返回。"""
        prepared = self.engine._preprocess([{"tx_id": "T1"}, {"tx_id": "T2"}])
        self.assertEqual(len(prepared), 2)

    def test_preprocess_invalid_input(self):
        """无效输入 → 返回空列表。"""
        prepared = self.engine._preprocess("invalid")
        self.assertEqual(prepared, [])

    def test_preprocess_lazy_load_model(self):
        """未 setup 时 _preprocess 懒加载模型。"""
        eng = KGEngine()
        prepared = eng._preprocess([])
        self.assertIsNotNone(eng.model)


class TestEngineSmurfingPattern(unittest.TestCase):
    """模式 ① 结构化交易（Smurfing）检测。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_smurfing_detected(self):
        """同一客户 3+ 笔接近阈值交易 → 触发 Smurfing SAR。"""
        txs = [
            {"tx_id": f"T{i}", "customer_id": "C1",
             "amount": 47000 + i * 100, "channel": "online",
             "jurisdiction": "CN", "hour": 10}
            for i in range(4)
        ]
        result = self.engine.execute(txs)
        smurf = [s for s in result["sars"] if "Smurfing" in s["pattern"]]
        self.assertEqual(len(smurf), 1)
        self.assertEqual(smurf[0]["customer_id"], "C1")
        self.assertEqual(smurf[0]["transaction_count"], 4)
        self.assertEqual(smurf[0]["risk_score"], 85)

    def test_smurfing_not_triggered_below_count(self):
        """少于 3 笔接近阈值交易 → 不触发 Smurfing。"""
        txs = [
            {"tx_id": "T1", "customer_id": "C1", "amount": 47000,
             "channel": "online", "jurisdiction": "CN", "hour": 10},
            {"tx_id": "T2", "customer_id": "C1", "amount": 48000,
             "channel": "online", "jurisdiction": "CN", "hour": 11},
        ]
        result = self.engine.execute(txs)
        smurf = [s for s in result["sars"] if "Smurfing" in s["pattern"]]
        self.assertEqual(len(smurf), 0)

    def test_smurfing_amount_range(self):
        """Smurfing 金额范围：[threshold*0.9, threshold)。"""
        txs = [
            {"tx_id": "T1", "customer_id": "C1", "amount": 45000,
             "channel": "online", "jurisdiction": "CN", "hour": 10},
            {"tx_id": "T2", "customer_id": "C1", "amount": 45000,
             "channel": "online", "jurisdiction": "CN", "hour": 11},
            {"tx_id": "T3", "customer_id": "C1", "amount": 49999,
             "channel": "online", "jurisdiction": "CN", "hour": 12},
        ]
        result = self.engine.execute(txs)
        smurf = [s for s in result["sars"] if "Smurfing" in s["pattern"]]
        self.assertEqual(len(smurf), 1)
        # 45000 是边界（>= threshold*0.9 = 45000）
        self.assertEqual(smurf[0]["transaction_count"], 3)

    def test_smurfing_total_amount(self):
        """Smurfing SAR 的 total_amount 为各笔金额之和。"""
        amounts = [47000, 48000, 49000]
        txs = [
            {"tx_id": f"T{i}", "customer_id": "C1", "amount": amt,
             "channel": "online", "jurisdiction": "CN", "hour": 10}
            for i, amt in enumerate(amounts)
        ]
        result = self.engine.execute(txs)
        smurf = [s for s in result["sars"] if "Smurfing" in s["pattern"]]
        self.assertAlmostEqual(smurf[0]["total_amount"], sum(amounts))


class TestEngineRoundTripPattern(unittest.TestCase):
    """模式 ② 快速往返（Round-trip）检测。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_roundtrip_detected(self):
        """资金出去后返回（>=80%）→ 触发 Round-trip SAR。"""
        txs = [
            {"tx_id": "OUT", "customer_id": "A", "counterparty": "B",
             "amount": 100000, "channel": "online", "jurisdiction": "CN",
             "hour": 10},
            {"tx_id": "BACK", "customer_id": "B", "counterparty": "A",
             "amount": 90000, "channel": "online", "jurisdiction": "CN",
             "hour": 14},
        ]
        result = self.engine.execute(txs)
        rounds = [s for s in result["sars"] if "Round-trip" in s["pattern"]]
        self.assertGreaterEqual(len(rounds), 1)
        self.assertEqual(rounds[0]["risk_score"], 75)

    def test_roundtrip_bidirectional(self):
        """Round-trip 双向触发（OUT 和 BACK 各产生一个 SAR）。"""
        txs = [
            {"tx_id": "OUT", "customer_id": "A", "counterparty": "B",
             "amount": 100000, "channel": "online", "jurisdiction": "CN",
             "hour": 10},
            {"tx_id": "BACK", "customer_id": "B", "counterparty": "A",
             "amount": 90000, "channel": "online", "jurisdiction": "CN",
             "hour": 14},
        ]
        result = self.engine.execute(txs)
        rounds = [s for s in result["sars"] if "Round-trip" in s["pattern"]]
        sar_ids = {s["sar_id"] for s in rounds}
        self.assertIn("SAR-ROUND-OUT", sar_ids)
        self.assertIn("SAR-ROUND-BACK", sar_ids)

    def test_roundtrip_not_triggered_no_reverse(self):
        """无反向交易 → 不触发 Round-trip。"""
        txs = [
            {"tx_id": "OUT", "customer_id": "A", "counterparty": "B",
             "amount": 100000, "channel": "online", "jurisdiction": "CN",
             "hour": 10},
            {"tx_id": "UNREL", "customer_id": "C", "counterparty": "D",
             "amount": 50000, "channel": "online", "jurisdiction": "CN",
             "hour": 14},
        ]
        result = self.engine.execute(txs)
        rounds = [s for s in result["sars"] if "Round-trip" in s["pattern"]]
        self.assertEqual(len(rounds), 0)


class TestEngineHighRiskPattern(unittest.TestCase):
    """模式 ③ 高风险地区交易检测。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_high_risk_jurisdiction_detected(self):
        """IRAN 交易 → 触发高风险地区 SAR。"""
        txs = [
            {"tx_id": "HR1", "customer_id": "C1", "amount": 50000,
             "channel": "online", "jurisdiction": "IRAN", "hour": 10},
        ]
        result = self.engine.execute(txs)
        hrisk = [s for s in result["sars"] if "高风险地区" in s["pattern"]]
        self.assertEqual(len(hrisk), 1)
        self.assertEqual(hrisk[0]["risk_score"], 90)
        self.assertEqual(hrisk[0]["jurisdiction"], "IRAN")

    def test_case_insensitive_jurisdiction(self):
        """jurisdiction 大小写不敏感（小写 iran 也命中）。"""
        txs = [
            {"tx_id": "HR1", "customer_id": "C1", "amount": 50000,
             "channel": "online", "jurisdiction": "iran", "hour": 10},
        ]
        result = self.engine.execute(txs)
        hrisk = [s for s in result["sars"] if "高风险地区" in s["pattern"]]
        self.assertEqual(len(hrisk), 1)

    def test_normal_jurisdiction_not_flagged(self):
        """CN 地区交易不触发高风险地区 SAR。"""
        txs = [
            {"tx_id": "N1", "customer_id": "C1", "amount": 50000,
             "channel": "online", "jurisdiction": "CN", "hour": 10},
        ]
        result = self.engine.execute(txs)
        hrisk = [s for s in result["sars"] if "高风险地区" in s["pattern"]]
        self.assertEqual(len(hrisk), 0)


class TestEngineCashAndNightPatterns(unittest.TestCase):
    """模式 ④ 大额现金 + 模式 ⑤ 非工作时段密集交易。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_large_cash_detected(self):
        """现金交易 > 200000 → 触发大额现金 SAR。"""
        txs = [
            {"tx_id": "CASH1", "customer_id": "C1", "amount": 300000,
             "channel": "cash", "jurisdiction": "CN", "hour": 12},
        ]
        result = self.engine.execute(txs)
        cash = [s for s in result["sars"] if "大额现金" in s["pattern"]]
        self.assertEqual(len(cash), 1)
        self.assertEqual(cash[0]["risk_score"], 70)

    def test_cash_below_threshold_not_flagged(self):
        """现金交易 <= 200000 → 不触发大额现金 SAR。"""
        txs = [
            {"tx_id": "CASH1", "customer_id": "C1", "amount": 200000,
             "channel": "cash", "jurisdiction": "CN", "hour": 12},
        ]
        result = self.engine.execute(txs)
        cash = [s for s in result["sars"] if "大额现金" in s["pattern"]]
        self.assertEqual(len(cash), 0)

    def test_night_transactions_detected(self):
        """同一客户 5+ 笔非工作时段交易 → 触发 Night SAR。"""
        txs = [
            {"tx_id": f"N{i}", "customer_id": "C1", "amount": 5000,
             "channel": "online", "jurisdiction": "CN", "hour": h}
            for i, h in enumerate([2, 3, 23, 1, 4])
        ]
        result = self.engine.execute(txs)
        night = [s for s in result["sars"] if "非工作时段" in s["pattern"]]
        self.assertEqual(len(night), 1)
        self.assertEqual(night[0]["transaction_count"], 5)
        self.assertEqual(night[0]["risk_score"], 65)

    def test_night_below_count_not_flagged(self):
        """少于 5 笔非工作时段交易 → 不触发 Night SAR。"""
        txs = [
            {"tx_id": f"N{i}", "customer_id": "C1", "amount": 5000,
             "channel": "online", "jurisdiction": "CN", "hour": h}
            for i, h in enumerate([2, 3, 23, 1])
        ]
        result = self.engine.execute(txs)
        night = [s for s in result["sars"] if "非工作时段" in s["pattern"]]
        self.assertEqual(len(night), 0)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：summary 汇总 + 风险分级。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()
        self.input_data = _load_sample_input()
        self.result = self.engine.execute(
            self.input_data["transactions"]
        )

    def test_summary_has_total_sars(self):
        """summary 含 total_sars。"""
        self.assertIn("summary", self.result)
        self.assertEqual(
            self.result["summary"]["total_sars"],
            len(self.result["sars"]),
        )

    def test_summary_risk_distribution(self):
        """summary 含 high_risk / medium_risk / low_risk 计数。"""
        summary = self.result["summary"]
        self.assertIn("high_risk", summary)
        self.assertIn("medium_risk", summary)
        self.assertIn("low_risk", summary)
        total = (
            summary["high_risk"]
            + summary["medium_risk"]
            + summary["low_risk"]
        )
        self.assertEqual(total, summary["total_sars"])

    def test_summary_patterns_list(self):
        """summary.patterns 含检测到的所有模式名。"""
        patterns = self.result["summary"]["patterns"]
        self.assertGreater(len(patterns), 0)
        # 应包含结构化交易
        self.assertTrue(
            any("Smurfing" in p for p in patterns)
        )

    def test_sars_sorted_by_risk_desc(self):
        """SAR 列表按 risk_score 降序排列。"""
        scores = [s["risk_score"] for s in self.result["sars"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_empty_transactions(self):
        """空交易列表 → 0 SAR。"""
        result = self.engine.execute([])
        self.assertEqual(result["sar_count"], 0)
        self.assertEqual(result["total_transactions"], 0)
        self.assertEqual(result["summary"]["total_sars"], 0)

    def test_no_suspicious_transactions(self):
        """正常交易不触发任何 SAR。"""
        txs = [
            {"tx_id": "N1", "customer_id": "C1", "amount": 1000,
             "channel": "online", "jurisdiction": "CN", "hour": 10},
            {"tx_id": "N2", "customer_id": "C2", "amount": 2000,
             "channel": "online", "jurisdiction": "CN", "hour": 11},
        ]
        result = self.engine.execute(txs)
        self.assertEqual(result["sar_count"], 0)

    def test_dict_input_with_transactions(self):
        """dict 含 transactions 输入可处理。"""
        result = self.engine.execute({
            "transactions": [
                {"tx_id": "T1", "customer_id": "C1", "amount": 1000,
                 "channel": "online", "jurisdiction": "CN", "hour": 10},
            ]
        })
        self.assertEqual(result["total_transactions"], 1)

    def test_full_fixture_run(self):
        """用 fixtures/sample_input.json 全量跑通。"""
        data = _load_sample_input()
        result = self.engine.execute(data["transactions"])
        self.assertEqual(result["total_transactions"], 20)
        self.assertGreater(result["sar_count"], 0)
        # 应触发全部 5 种模式
        patterns = set(result["summary"]["patterns"])
        self.assertEqual(len(patterns), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
