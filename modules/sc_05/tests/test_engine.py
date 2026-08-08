"""[SC-05] engine 单测：品类画像 / 百分位基准 / 线性趋势 / 对标分析。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.sc_05.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {
        "threshold": {"acceptable_pct": 10.0, "marginal_pct": 25.0},
        "db_path": str(Path(tmpdir) / "sc_05_test.db"),
    }
    config.update(overrides)
    eng = MLEngine(config=config)
    eng.setup()
    return eng


def _history(category, prices):
    """构造某品类历史价记录。"""
    return [
        {"category": category, "price": p, "source": "市场",
         "record_date": f"2025-{i+1:02d}-01"}
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

    def test_db_has_three_tables(self):
        """PortableDB 含 price_histories / category_baselines / benchmark_results。"""
        tables = set(self.engine.db.tables())
        self.assertIn("price_histories", tables)
        self.assertIn("category_baselines", tables)
        self.assertIn("benchmark_results", tables)

    def test_model_defaults(self):
        """模型默认参数：百分位列表 / 基准区间 / R²阈值 / 权重。"""
        self.assertEqual(self.engine.model["percentiles"], [10, 25, 50, 75, 90, 95])
        self.assertEqual(self.engine.model["baseline_range"], [10, 90])
        self.assertEqual(self.engine.model["r2_threshold"], 0.5)
        self.assertAlmostEqual(self.engine.model["market_weight"], 0.3, places=4)
        self.assertAlmostEqual(self.engine.model["history_weight"], 0.7, places=4)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：历史价分组 / 查询清洗。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_groups_prices_by_category(self):
        """历史价按品类分组。"""
        prepared = self.engine._preprocess({
            "price_history": [
                {"category": "A", "price": 100},
                {"category": "A", "price": 110},
                {"category": "B", "price": 200},
            ],
            "benchmark_queries": [],
        })
        self.assertEqual(prepared["by_category"]["A"], [100.0, 110.0])
        self.assertEqual(prepared["by_category"]["B"], [200.0])

    def test_skips_invalid_prices(self):
        """非正价/非法价被剔除。"""
        prepared = self.engine._preprocess({
            "price_history": [
                {"category": "A", "price": 100},
                {"category": "A", "price": 0},
                {"category": "A", "price": -5},
                {"category": "A", "price": "x"},
                {"category": "", "price": 50},
            ],
            "benchmark_queries": [],
        })
        self.assertEqual(prepared["by_category"]["A"], [100.0])

    def test_cleans_queries(self):
        """查询清洗：price 转 float，缺 benchmark_id 自动生成。"""
        prepared = self.engine._preprocess({
            "price_history": [],
            "benchmark_queries": [
                {"category": "A", "price": "100"},
                {"category": "A", "price": 0},
                {"category": "", "price": 50},
            ],
        })
        queries = prepared["queries"]
        self.assertEqual(len(queries), 1)
        self.assertEqual(queries[0]["price"], 100.0)
        self.assertTrue(queries[0]["benchmark_id"].startswith("B-"))

    def test_non_dict_input_rejected(self):
        """非 dict 输入 → ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess([{"category": "A", "price": 100}])


class TestEnginePercentile(unittest.TestCase):
    """_percentile：线性插值百分位。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_percentile_endpoints(self):
        """P0 = 最小值，P100 = 最大值。"""
        vals = [10, 20, 30, 40, 50]
        self.assertEqual(self.engine._percentile(vals, 0), 10)
        self.assertEqual(self.engine._percentile(vals, 100), 50)

    def test_percentile_median(self):
        """P50 = 中位数。"""
        vals = [10, 20, 30, 40, 50]
        self.assertEqual(self.engine._percentile(vals, 50), 30)

    def test_percentile_interpolation(self):
        """P90 线性插值正确。"""
        vals = [10, 20, 30, 40, 50]
        # pos = 0.9 * 4 = 3.6 → 40*0.4 + 50*0.6 = 46
        self.assertEqual(self.engine._percentile(vals, 90), 46)

    def test_percentile_empty(self):
        """空列表 → 0.0。"""
        self.assertEqual(self.engine._percentile([], 50), 0.0)


class TestEngineLinearRegression(unittest.TestCase):
    """_linear_slope / _r_squared：线性回归趋势。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_perfect_linear_slope(self):
        """完美线性 y=2x+1 → slope=2。"""
        xs = [0, 1, 2, 3]
        ys = [1, 3, 5, 7]
        self.assertAlmostEqual(self.engine._linear_slope(xs, ys), 2.0, places=4)

    def test_r_squared_perfect_fit(self):
        """完美拟合 → R²=1.0。"""
        xs = [0, 1, 2, 3]
        ys = [1, 3, 5, 7]
        slope = self.engine._linear_slope(xs, ys)
        intercept = self.engine._linear_intercept(xs, ys, slope)
        self.assertAlmostEqual(
            self.engine._r_squared(xs, ys, slope, intercept), 1.0, places=4
        )

    def test_r_squared_poor_fit(self):
        """非单调数据 → R² 较低。"""
        xs = [0, 1, 2, 3, 4]
        ys = [10, 1, 10, 1, 10]
        slope = self.engine._linear_slope(xs, ys)
        intercept = self.engine._linear_intercept(xs, ys, slope)
        r2 = self.engine._r_squared(xs, ys, slope, intercept)
        self.assertLess(r2, 0.5)

    def test_zero_variance_returns_one(self):
        """常数序列（方差为0）→ R²=1.0。"""
        xs = [0, 1, 2, 3]
        ys = [5, 5, 5, 5]
        slope = self.engine._linear_slope(xs, ys)
        intercept = self.engine._linear_intercept(xs, ys, slope)
        self.assertEqual(
            self.engine._r_squared(xs, ys, slope, intercept), 1.0
        )


class TestEngineInferAndPostprocess(unittest.TestCase):
    """_infer / _postprocess：基准构建 / 对标 / 趋势。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.data = _load_sample()
        self.result = self.engine.execute(self.data)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_baselines_built_for_categories(self):
        """≥5 条历史价的品类构建基准（钢材/水泥/电缆）。"""
        baselines = self.result["baselines"]
        self.assertIn("钢材", baselines)
        self.assertIn("水泥", baselines)
        self.assertIn("电缆", baselines)

    def test_baseline_excludes_insufficient_category(self):
        """<5 条历史价的品类（木材）不构建基准。"""
        self.assertNotIn("木材", self.result["baselines"])

    def test_baseline_percentiles_present(self):
        """基准含 P10/P25/P50/P75/P90/P95。"""
        bl = self.result["baselines"]["钢材"]
        pcts = bl["percentiles"]
        for p in ("10", "25", "50", "75", "90", "95"):
            self.assertIn(p, pcts)
        self.assertEqual(bl["baseline_price"], bl["median"])

    def test_baseline_low_high_bounds(self):
        """基准 low_bound=P10, high_bound=P90。"""
        bl = self.result["baselines"]["钢材"]
        self.assertEqual(bl["low_bound"], bl["percentiles"]["10"])
        self.assertEqual(bl["high_bound"], bl["percentiles"]["90"])

    def test_results_count_matches_queries(self):
        """对标结果数 = 查询数。"""
        self.assertEqual(
            len(self.result["results"]), len(self.data["benchmark_queries"])
        )

    def test_no_baseline_query_handled(self):
        """木材查询无基准 → status=no_baseline。"""
        wood = [r for r in self.result["results"] if r["category"] == "木材"]
        self.assertEqual(len(wood), 3)
        for r in wood:
            self.assertEqual(r["status"], "no_baseline")

    def test_high_price_flagged_as_high(self):
        """钢材 6500 高于 high_bound → position=偏高。"""
        by_id = {r["benchmark_id"]: r for r in self.result["results"]}
        self.assertEqual(by_id["B-0001"]["position"], "偏高")
        self.assertGreater(by_id["B-0001"]["deviation_pct"], 25)

    def test_normal_price_position(self):
        """电缆 1000 在合理区间 → position=正常。"""
        by_id = {r["benchmark_id"]: r for r in self.result["results"]}
        self.assertEqual(by_id["B-0004"]["position"], "正常")

    def test_deviation_calculation(self):
        """deviation_pct = (test - baseline)/baseline * 100。"""
        by_id = {r["benchmark_id"]: r for r in self.result["results"]}
        r = by_id["B-0001"]
        expected = (r["test_price"] - r["baseline_price"]) / r["baseline_price"] * 100
        self.assertAlmostEqual(r["deviation_pct"], expected, places=1)

    def test_declining_trend_detected(self):
        """电缆历史价下降 → trend_direction=下降, trend_stable=True。"""
        bl = self.result["baselines"]["电缆"]
        self.assertEqual(bl["trend_direction"], "下降")
        self.assertTrue(bl["trend_stable"])

    def test_rising_trend_detected(self):
        """钢材历史价上升 → trend_direction=上升。"""
        bl = self.result["baselines"]["钢材"]
        self.assertEqual(bl["trend_direction"], "上升")

    def test_postprocess_trend_counts(self):
        """_postprocess 注入 stable/unstable 趋势品类数。"""
        s = self.result["summary"]
        self.assertEqual(
            s["stable_trend_categories"] + s["unstable_trend_categories"],
            len(self.result["baselines"]),
        )
        self.assertGreater(s["stable_trend_categories"], 0)

    def test_summary_assessments(self):
        """summary.assessments 含 正常/偏高/no_baseline 计数。"""
        a = self.result["summary"]["assessments"]
        self.assertIn("正常", a)
        self.assertIn("偏高", a)
        self.assertIn("no_baseline", a)
        self.assertEqual(a["no_baseline"], 3)

    def test_top_high_deviation_sorted(self):
        """top_high_deviation 按 |deviation_pct| 降序，最多 10 条。"""
        top = self.result["summary"]["top_high_deviation"]
        self.assertLessEqual(len(top), 10)
        devs = [abs(t["deviation_pct"]) for t in top]
        self.assertEqual(devs, sorted(devs, reverse=True))


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_input(self):
        """空输入 → 0 基准、0 查询。"""
        result = self.engine.execute({"price_history": [], "benchmark_queries": []})
        self.assertEqual(result["baselines"], {})
        self.assertEqual(result["results"], [])
        self.assertEqual(result["summary"]["category_count"], 0)

    def test_no_queries(self):
        """仅有历史价、无查询 → 有基准但 0 对标结果。"""
        result = self.engine.execute({
            "price_history": _history("A", [100, 110, 120, 130, 140]),
            "benchmark_queries": [],
        })
        self.assertIn("A", result["baselines"])
        self.assertEqual(result["results"], [])

    def test_query_without_baseline(self):
        """查询品类无历史价 → no_baseline。"""
        result = self.engine.execute({
            "price_history": _history("A", [100, 110, 120, 130, 140]),
            "benchmark_queries": [{"category": "Z", "price": 50}],
        })
        self.assertEqual(result["results"][0]["status"], "no_baseline")

    def test_insufficient_history_no_baseline(self):
        """品类历史价 <5 条 → 不构建基准，查询返回 no_baseline。"""
        result = self.engine.execute({
            "price_history": _history("A", [100, 110, 120]),
            "benchmark_queries": [{"category": "A", "price": 110}],
        })
        self.assertNotIn("A", result["baselines"])
        self.assertEqual(result["results"][0]["status"], "no_baseline")

    def test_list_input_rejected(self):
        """非 dict 输入 → ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute([{"category": "A", "price": 100}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
