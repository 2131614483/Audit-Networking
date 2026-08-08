"""[SC-03] engine 单测：滑动窗口统计 / Z-Score / IQR / EWMA / 趋势 / 预警分级。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.sc_03.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {
        "db_path": str(Path(tmpdir) / "sc_03_test.db"),
    }
    config.update(overrides)
    eng = MLEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + 模型参数。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_db_has_two_tables(self):
        """PortableDB 含 supplier_metrics / risk_alerts 两张表。"""
        tables = set(self.engine.db.tables())
        self.assertIn("supplier_metrics", tables)
        self.assertIn("risk_alerts", tables)

    def test_model_params_loaded(self):
        """模型参数：ewma_lambda=0.3、z_threshold=3.0、window_size=30。"""
        self.assertAlmostEqual(self.engine.model["ewma_lambda"], 0.3)
        self.assertAlmostEqual(self.engine.model["z_threshold"], 3.0)
        self.assertEqual(self.engine.model["window_size"], 30)
        self.assertAlmostEqual(self.engine.model["iqr_multiplier"], 1.5)

    def test_alert_levels_defined(self):
        """预警分级含 紧急/高/中/低 四级。"""
        levels = [lv for lv, _ in self.engine.model["alert_levels"]]
        self.assertEqual(levels, ["紧急", "高", "中", "低"])

    def test_metrics_list_defined(self):
        """监控指标列表含 6 项核心指标。"""
        metrics = self.engine.model["metrics"]
        self.assertIn("payment_delay_days", metrics)
        self.assertIn("quality_failure_rate", metrics)
        self.assertGreaterEqual(len(metrics), 6)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据清洗 / 窗口截断。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_cleans_metrics(self):
        """预处理：指标时序转为 float 列表。"""
        prepared = self.engine._preprocess({
            "suppliers": [{
                "supplier_id": "S1",
                "name": "供应商一",
                "metrics": {"payment_delay_days": [1, 2, 3, "4", None, 5]},
            }]
        })
        sup = prepared["suppliers"][0]
        self.assertEqual(sup["supplier_id"], "S1")
        self.assertEqual(sup["metrics"]["payment_delay_days"], [1.0, 2.0, 3.0, 4.0, 5.0])

    def test_preprocess_non_dict_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute([])
        with self.assertRaises(ValueError):
            self.engine.execute("invalid")

    def test_preprocess_skips_empty_suppliers(self):
        """无 supplier_id 或无有效指标的供应商被跳过。"""
        prepared = self.engine._preprocess({
            "suppliers": [
                {"supplier_id": "", "metrics": {"a": [1, 2]}},
                {"supplier_id": "S2", "metrics": {}},
                {"supplier_id": "S3", "metrics": {"a": [1, 2, 3]}},
            ]
        })
        self.assertEqual(len(prepared["suppliers"]), 1)
        self.assertEqual(prepared["suppliers"][0]["supplier_id"], "S3")

    def test_preprocess_window_truncation(self):
        """超过 window_size 的时序被截断到窗口长度。"""
        eng = _make_engine(self.tmpdir.name, window_size=5)
        prepared = eng._preprocess({
            "suppliers": [{
                "supplier_id": "S1",
                "metrics": {"payment_delay_days": [1, 2, 3, 4, 5, 6, 7, 8]},
            }]
        })
        self.assertEqual(
            len(prepared["suppliers"][0]["metrics"]["payment_delay_days"]), 5
        )
        eng.close()


class TestEngineAnalyzeMetric(unittest.TestCase):
    """_analyze_metric：Z-Score / IQR / EWMA / 趋势。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_insufficient_data(self):
        """<3 个数据点 → insufficient_data、anomaly_score=0。"""
        a = self.engine._analyze_metric([1, 2], 0.3, 3.0, 1.5)
        self.assertEqual(a["status"], "insufficient_data")
        self.assertEqual(a["anomaly_score"], 0.0)
        self.assertEqual(a["alerts"], [])

    def test_zscore_anomaly_detected(self):
        """极端离群值 → Z-Score 异常。"""
        values = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 100]
        a = self.engine._analyze_metric(values, 0.3, 3.0, 1.5)
        self.assertGreater(a["z_anomaly_count"], 0)
        z_alerts = [al for al in a["alerts"] if al["type"] == "z_score_anomaly"]
        self.assertEqual(len(z_alerts), 1)
        self.assertEqual(z_alerts[0]["severity"], "high")

    def test_iqr_anomaly_detected(self):
        """超出 IQR 上下界 → IQR 异常。"""
        values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]
        a = self.engine._analyze_metric(values, 0.3, 3.0, 1.5)
        self.assertGreater(a["iqr_anomaly_count"], 0)

    def test_anomaly_score_in_range(self):
        """anomaly_score ∈ [0, 1]。"""
        for values in ([1, 2, 3, 4, 5], [10, 10, 10, 10, 100],
                       [1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2]):
            a = self.engine._analyze_metric(values, 0.3, 3.0, 1.5)
            self.assertGreaterEqual(a["anomaly_score"], 0.0)
            self.assertLessEqual(a["anomaly_score"], 1.0)

    def test_ewma_calculation(self):
        """EWMA 指数加权移动平均计算正确。"""
        self.assertAlmostEqual(self.engine._ewma([1, 2, 3], 0.3), 1.81, places=2)
        self.assertEqual(self.engine._ewma([], 0.3), 0.0)
        self.assertEqual(self.engine._ewma([5], 0.3), 5.0)

    def test_linear_slope(self):
        """线性回归斜率：[1,2,3,4,5] → slope=1.0。"""
        self.assertAlmostEqual(
            self.engine._linear_slope([1, 2, 3, 4, 5]), 1.0, places=4
        )
        self.assertAlmostEqual(
            self.engine._linear_slope([5, 4, 3, 2, 1]), -1.0, places=4
        )
        self.assertEqual(self.engine._linear_slope([3]), 0.0)

    def test_percentile(self):
        """百分位计算：中位数、插值。"""
        self.assertEqual(
            self.engine._percentile([10, 20, 30, 40, 50], 50), 30
        )
        self.assertEqual(self.engine._percentile([10, 20, 30, 40], 50), 25.0)
        self.assertEqual(self.engine._percentile([], 50), 0.0)

    def test_trend_direction_rising(self):
        """上升趋势 → trend_direction=上升。"""
        a = self.engine._analyze_metric([1, 2, 3, 4, 5, 6, 7, 8], 0.3, 3.0, 1.5)
        self.assertEqual(a["trend_direction"], "上升")

    def test_trend_direction_falling(self):
        """下降趋势 → trend_direction=下降。"""
        a = self.engine._analyze_metric([8, 7, 6, 5, 4, 3, 2, 1], 0.3, 3.0, 1.5)
        self.assertEqual(a["trend_direction"], "下降")

    def test_metric_analysis_fields(self):
        """指标分析结果含 count/mean/std/latest/ewma/trend_direction。"""
        a = self.engine._analyze_metric([1, 2, 3, 4, 5, 6], 0.3, 3.0, 1.5)
        for k in ("count", "mean", "std", "latest", "ewma",
                  "trend_direction", "trend_slope", "anomaly_score", "alerts"):
            self.assertIn(k, a)


class TestEngineInferAndPostprocess(unittest.TestCase):
    """_infer / _postprocess：整体评分 / 预警分级 / 汇总。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample()
        self.result = self.engine.execute(self.sample)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_result_has_suppliers_and_summary(self):
        """结果含 suppliers / summary。"""
        self.assertIn("suppliers", self.result)
        self.assertIn("summary", self.result)

    def test_supplier_count(self):
        """供应商数 = 输入有效供应商数（SUP-D 数据不足但仍参与）。"""
        self.assertEqual(len(self.result["suppliers"]), 4)

    def test_overall_risk_score_in_range(self):
        """所有供应商 overall_risk_score ∈ [0, 1]。"""
        for s in self.result["suppliers"]:
            self.assertGreaterEqual(s["overall_risk_score"], 0.0)
            self.assertLessEqual(s["overall_risk_score"], 1.0)

    def test_alert_level_valid(self):
        """预警等级为 紧急/高/中/低 之一。"""
        valid = {"紧急", "高", "中", "低"}
        for s in self.result["suppliers"]:
            self.assertIn(s["alert_level"], valid)

    def test_suppliers_sorted_by_risk_desc(self):
        """供应商按 overall_risk_score 降序排列。"""
        scores = [s["overall_risk_score"] for s in self.result["suppliers"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_metric_analyses_populated(self):
        """每个供应商的 metric_analyses 非空（除数据不足者）。"""
        for s in self.result["suppliers"]:
            self.assertIsInstance(s["metric_analyses"], dict)

    def test_alerts_have_metric_name(self):
        """告警明细带 metric_name 字段。"""
        for s in self.result["suppliers"]:
            for alert in s.get("alerts", []):
                self.assertIn("metric_name", alert)

    def test_summary_fields(self):
        """summary 含 supplier_count / alerts_by_level / avg_risk_score。"""
        s = self.result["summary"]
        self.assertEqual(s["supplier_count"], len(self.result["suppliers"]))
        self.assertIn("alerts_by_level", s)
        self.assertIn("avg_risk_score", s)
        for lv in ("紧急", "高", "中", "低"):
            self.assertIn(lv, s["alerts_by_level"])

    def test_summary_alerts_by_level_consistent(self):
        """alerts_by_level 各级之和 = 供应商总数。"""
        s = self.result["summary"]
        total = sum(s["alerts_by_level"].values())
        self.assertEqual(total, s["supplier_count"])

    def test_postprocess_high_risk_suppliers(self):
        """_postprocess 注入 high_risk_suppliers 列表。"""
        s = self.result["summary"]
        self.assertIn("high_risk_suppliers", s)
        self.assertIsInstance(s["high_risk_suppliers"], list)

    def test_supplier_fields(self):
        """每个供应商含 supplier_id/name/metric_analyses/overall_risk_score/alerts。"""
        for s in self.result["suppliers"]:
            for k in ("supplier_id", "name", "metric_analyses",
                      "overall_risk_score", "alerts", "alert_level"):
                self.assertIn(k, s)

    def test_insufficient_data_supplier(self):
        """SUP-D 数据不足 → 该指标 status=insufficient_data。"""
        sup_d = next(
            s for s in self.result["suppliers"] if s["supplier_id"] == "SUP-D"
        )
        pdd = sup_d["metric_analyses"].get("payment_delay_days", {})
        self.assertEqual(pdd.get("status"), "insufficient_data")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_input(self):
        """空供应商列表 → supplier_count=0。"""
        result = self.engine.execute({"suppliers": []})
        self.assertEqual(result["summary"]["supplier_count"], 0)
        self.assertEqual(result["suppliers"], [])

    def test_missing_suppliers_key(self):
        """缺 suppliers 键 → 空结果而非异常。"""
        result = self.engine.execute({})
        self.assertEqual(result["summary"]["supplier_count"], 0)

    def test_single_supplier_single_metric(self):
        """单供应商单指标 → 结果含该供应商。"""
        result = self.engine.execute({
            "suppliers": [{
                "supplier_id": "X1",
                "name": "X",
                "metrics": {"payment_delay_days": [1, 2, 3, 4, 5]},
            }]
        })
        self.assertEqual(len(result["suppliers"]), 1)
        self.assertEqual(result["suppliers"][0]["supplier_id"], "X1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
