"""[SC-04] engine 单测：Benford / Z-Score / IQR / IsolationForest / 评分分级。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from modules.sc_04.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {
        "threshold": {"critical": 0.85, "high": 0.70, "medium": 0.40},
        "db_path": str(Path(tmpdir) / "sc_04_test.db"),
    }
    config.update(overrides)
    eng = MLEngine(config=config)
    eng.setup()
    return eng


def _orders(prices, category="钢材", supplier="S001"):
    """构造同品类订单列表（单价从 prices 取，quantity=10）。"""
    return [
        {
            "order_id": f"O-{i+1:04d}",
            "supplier_id": supplier,
            "category": category,
            "unit_price": p,
            "quantity": 10,
            "total_amount": p * 10,
        }
        for i, p in enumerate(prices)
    ]


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + 模型默认值。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_db_has_two_tables(self):
        """PortableDB 含 purchase_orders / anomaly_results 两张表。"""
        tables = set(self.engine.db.tables())
        self.assertIn("purchase_orders", tables)
        self.assertIn("anomaly_results", tables)

    def test_benford_expected_distribution(self):
        """Benford 期望频率：digit 1 ≈ 0.301, digit 9 ≈ 0.046。"""
        exp = self.engine.model["benford_expected"]
        self.assertAlmostEqual(exp[1], 0.30103, places=3)
        self.assertAlmostEqual(exp[9], 0.04576, places=3)
        # 9 个数字概率和为 1
        self.assertAlmostEqual(sum(exp.values()), 1.0, places=4)

    def test_layer_weights_sum_to_one(self):
        """四层权重之和 = 1.0。"""
        w = self.engine.model["layer_weights"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)

    def test_model_defaults(self):
        """模型默认参数：z_threshold=3.0, iqr_multiplier=1.5, benford_critical=15.507。"""
        self.assertEqual(self.engine.model["z_threshold"], 3.0)
        self.assertEqual(self.engine.model["iqr_multiplier"], 1.5)
        self.assertAlmostEqual(self.engine.model["benford_critical"], 15.507, places=3)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据清洗 / 特征工程。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_cleans_orders(self):
        """预处理：单价/数量转 float，特征字段生成。"""
        prepared = self.engine._preprocess({"orders": [
            {"order_id": "PO1", "supplier_id": "S1", "category": "钢材",
             "unit_price": "100", "quantity": "5", "total_amount": "500"},
        ]})
        o = prepared["orders"][0]
        self.assertEqual(o["order_id"], "PO1")
        self.assertEqual(o["unit_price"], 100.0)
        self.assertEqual(o["quantity"], 5.0)
        self.assertEqual(o["total_amount"], 500.0)
        self.assertIn("features", o)
        self.assertAlmostEqual(o["features"]["log_price"], math.log(100), places=4)

    def test_preprocess_skips_invalid_price(self):
        """单价 <= 0 或非法的订单被剔除。"""
        prepared = self.engine._preprocess({"orders": [
            {"order_id": "A", "unit_price": 0, "quantity": 1},
            {"order_id": "B", "unit_price": -5, "quantity": 1},
            {"order_id": "C", "unit_price": "abc", "quantity": 1},
            {"order_id": "D", "unit_price": 100, "quantity": 1},
        ]})
        ids = [o["order_id"] for o in prepared["orders"]]
        self.assertEqual(ids, ["D"])

    def test_preprocess_generates_order_id(self):
        """缺 order_id 时自动生成 O-NNNNNN。"""
        prepared = self.engine._preprocess({"orders": [
            {"unit_price": 100, "quantity": 1, "category": "X"},
        ]})
        self.assertTrue(prepared["orders"][0]["order_id"].startswith("O-"))

    def test_preprocess_default_total_amount(self):
        """缺 total_amount 时用 unit_price * quantity 兜底。"""
        prepared = self.engine._preprocess({"orders": [
            {"order_id": "T", "unit_price": 50, "quantity": 4},
        ]})
        self.assertEqual(prepared["orders"][0]["total_amount"], 200.0)


class TestEngineBenford(unittest.TestCase):
    """Benford 定律卡方检验。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_benford_returns_zero_for_few_amounts(self):
        """少于 10 条记录 → 返回 0.0。"""
        prepared = self.engine._preprocess({"orders": _orders([100, 200, 300])})
        self.assertEqual(self.engine._benford_analysis(prepared["orders"]), 0.0)

    def test_benford_returns_score_for_enough_amounts(self):
        """≥10 条记录 → 返回 [0,1] 区间得分。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100 * (i + 1) for i in range(15)]
        )})
        score = self.engine._benford_analysis(prepared["orders"])
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_benford_sample_flagged(self):
        """sample_input 总额首位分布偏离 → benford 被标记。"""
        data = _load_sample()
        result = self.engine.execute(data)
        self.assertTrue(result["summary"]["benford_flagged"])
        self.assertGreater(result["summary"]["benford_statistic"], 0)


class TestEngineStatisticalScore(unittest.TestCase):
    """_statistical_score：Z-Score + IQR 贡献。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_few_prices_returns_default(self):
        """品类少于 3 条价格 → 返回 0.5 默认值。"""
        prepared = self.engine._preprocess({"orders": _orders([100, 200])})
        score = self.engine._statistical_score(
            prepared["orders"][0], prepared["orders"]
        )
        self.assertEqual(score, 0.5)

    def test_normal_price_low_score(self):
        """正常价格（无离群）→ 统计得分较低。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 100, 100, 100, 100]
        )})
        score = self.engine._statistical_score(
            prepared["orders"][0], prepared["orders"]
        )
        self.assertLess(score, 0.1)

    def test_high_outlier_high_score(self):
        """高价离群点 → 统计得分显著高于正常点。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 100, 100, 100, 200]
        )})
        normal = self.engine._statistical_score(
            prepared["orders"][0], prepared["orders"]
        )
        outlier = self.engine._statistical_score(
            prepared["orders"][4], prepared["orders"]
        )
        self.assertGreater(outlier, normal)
        self.assertGreater(outlier, 0.5)

    def test_low_outlier_flagged(self):
        """低价离群点（低于 IQR 下界）→ 得分高于正常点。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 100, 100, 100, 10]
        )})
        normal = self.engine._statistical_score(
            prepared["orders"][0], prepared["orders"]
        )
        low_outlier = self.engine._statistical_score(
            prepared["orders"][4], prepared["orders"]
        )
        self.assertGreater(low_outlier, normal)

    def test_score_bounded_by_one(self):
        """统计得分不超过 1.0。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 100, 100, 100, 10000]
        )})
        score = self.engine._statistical_score(
            prepared["orders"][4], prepared["orders"]
        )
        self.assertLessEqual(score, 1.0)


class TestEngineIsolationForest(unittest.TestCase):
    """_isolation_forest_score：模拟 IsolationForest。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_returns_score_per_order(self):
        """返回每个订单一个评分，长度一致。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 110, 120, 130, 140, 150, 160, 170, 180, 5000]
        )})
        scores = self.engine._isolation_forest_score(prepared["orders"])
        self.assertEqual(len(scores), len(prepared["orders"]))

    def test_scores_in_range(self):
        """所有评分 ∈ [0,1]。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 110, 120, 130, 140, 150, 160, 170, 180, 5000]
        )})
        for s in self.engine._isolation_forest_score(prepared["orders"]):
            self.assertGreaterEqual(s, 0.0)
            self.assertLessEqual(s, 1.0)

    def test_deterministic_with_same_input(self):
        """相同输入 → 相同评分（random.Random(42) 固定种子）。"""
        prepared = self.engine._preprocess({"orders": _orders(
            [100, 110, 120, 130, 140, 150, 160, 170, 180, 5000, 10, 200]
        )})
        s1 = self.engine._isolation_forest_score(prepared["orders"])
        s2 = self.engine._isolation_forest_score(prepared["orders"])
        self.assertEqual(s1, s2)


class TestEngineInferAndPostprocess(unittest.TestCase):
    """_infer / _postprocess：结果结构 / 分级 / 汇总。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.data = _load_sample()
        self.result = self.engine.execute(self.data)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_results_count_matches_orders(self):
        """结果数 = 订单数。"""
        self.assertEqual(
            len(self.result["results"]), len(self.data["orders"])
        )

    def test_results_sorted_by_score_desc(self):
        """结果按 anomaly_score 降序排列。"""
        scores = [r["anomaly_score"] for r in self.result["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_anomaly_level_valid(self):
        """anomaly_level 为 高/中/低 之一。"""
        valid = {"高", "中", "低"}
        for r in self.result["results"]:
            self.assertIn(r["anomaly_level"], valid)

    def test_anomaly_score_in_range(self):
        """anomaly_score ∈ [0,1]。"""
        for r in self.result["results"]:
            self.assertGreaterEqual(r["anomaly_score"], 0.0)
            self.assertLessEqual(r["anomaly_score"], 1.0)

    def test_indicators_present(self):
        """每个结果含三层贡献指标。"""
        for r in self.result["results"]:
            ind = r["indicators"]
            self.assertIn("benford_contribution", ind)
            self.assertIn("statistical_contribution", ind)
            self.assertIn("iso_forest_contribution", ind)

    def test_summary_fields(self):
        """summary 含 order_count / anomaly_distribution / top_anomalies。"""
        s = self.result["summary"]
        self.assertEqual(s["order_count"], len(self.data["orders"]))
        self.assertIn("高", s["anomaly_distribution"])
        self.assertIn("中", s["anomaly_distribution"])
        self.assertIn("低", s["anomaly_distribution"])

    def test_postprocess_category_stats(self):
        """_postprocess 注入 category_stats（含每个品类的 count/avg_score）。"""
        cats = self.result["summary"]["category_stats"]
        self.assertIn("钢材", cats)
        self.assertIn("水泥", cats)
        self.assertEqual(cats["钢材"]["count"], 13)
        self.assertGreater(cats["钢材"]["avg_score"], 0)

    def test_postprocess_anomaly_count(self):
        """anomaly_count = 非"低"级结果数。"""
        s = self.result["summary"]
        expected = sum(
            1 for r in self.result["results"] if r["anomaly_level"] != "低"
        )
        self.assertEqual(s["anomaly_count"], expected)
        self.assertGreater(s["anomaly_count"], 0)

    def test_top_anomalies_capped_at_ten(self):
        """top_anomalies 最多 10 条。"""
        self.assertLessEqual(len(self.result["summary"]["top_anomalies"]), 10)

    def test_outliers_detected_in_sample(self):
        """sample 含注入高价离群 → PO-0012(9500)/PO-0021(900) 被识别为中高异常。"""
        by_id = {r["order_id"]: r for r in self.result["results"]}
        self.assertGreater(by_id["PO-0012"]["anomaly_score"], 0.4)
        self.assertGreater(by_id["PO-0021"]["anomaly_score"], 0.4)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_orders(self):
        """空订单 → 0 结果、order_count=0。"""
        result = self.engine.execute({"orders": []})
        self.assertEqual(result["results"], [])
        self.assertEqual(result["summary"]["order_count"], 0)

    def test_list_input_rejected(self):
        """非 dict 输入 → ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute([{"unit_price": 100, "quantity": 1}])

    def test_single_category_few_orders(self):
        """单品类 <3 单 → statistical_score 走 0.5 默认。"""
        prepared = self.engine._preprocess({"orders": _orders([100, 200])})
        self.assertEqual(
            self.engine._statistical_score(
                prepared["orders"][0], prepared["orders"]
            ),
            0.5,
        )

    def test_invalid_records_filtered(self):
        """含非法记录的输入 → 仅保留合法订单（保留 ≥2 条以支持 IsolationForest）。"""
        result = self.engine.execute({"orders": [
            {"order_id": "OK1", "unit_price": 100, "quantity": 1},
            {"order_id": "OK2", "unit_price": 110, "quantity": 1},
            {"order_id": "BAD", "unit_price": "x", "quantity": 1},
            {"order_id": "ZERO", "unit_price": 0, "quantity": 1},
        ]})
        ids = {r["order_id"] for r in result["results"]}
        self.assertEqual(ids, {"OK1", "OK2"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
