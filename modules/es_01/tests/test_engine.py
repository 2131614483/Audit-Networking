"""[ES-01] engine 单测：多模态解析 / 指标融合 / 质量评分 / 单位归一化。

unittest 风格（不依赖 pytest），覆盖 CVEngine 各阶段与边界情况。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.es_01.engine import (
    CVEngine,
    _GRI_METRICS,
    _SOURCE_WEIGHTS,
    _UNIT_CONVERSIONS,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(**overrides) -> CVEngine:
    """构造已加载模型的 engine。"""
    config = {"threshold": {"confidence": 0.85}}
    config.update(overrides)
    eng = CVEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：解析器注册 + 标准库加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_parsers_registered(self):
        """五种多模态解析器注册到位。"""
        for dtype in ("structured", "semi_structured", "text", "time_series", "image_meta"):
            self.assertIn(dtype, self.engine.parsers)

    def test_metric_schema_loaded(self):
        """GRI 指标标准库含 8 个指标（E/S/G 三维度）。"""
        self.assertEqual(len(self.engine.metric_schema), 8)
        for mkey in ("GHG_Emissions", "Energy_Consumption", "Water_Intensity",
                     "Waste_Generated", "Employee_Turnover", "Diversity_Ratio",
                     "Board_Independence", "Anti_Corruption"):
            self.assertIn(mkey, self.engine.metric_schema)

    def test_source_weights_cover_credibility(self):
        """数据源权重：政府平台=1.0，社交媒体=0.40。"""
        self.assertEqual(self.engine.source_weights["政府平台"], 1.0)
        self.assertEqual(self.engine.source_weights["社交媒体"], 0.40)
        self.assertGreater(self.engine.source_weights["政府平台"],
                           self.engine.source_weights["新闻媒体"])

    def test_unit_map_loaded(self):
        """单位换算表覆盖 tCO2 / kWh / MJ / m3 / ha。"""
        for std_unit in ("tCO2", "kWh", "MJ", "m3", "ha"):
            self.assertIn(std_unit, self.engine.unit_map)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入规整 + 缺省值填充。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_list_input_preserved(self):
        """list 输入：每项被规整为含 source_weight 的预处理项。"""
        prepared = self.engine._preprocess([
            {"source": "政府平台", "metric_key": "GHG_Emissions", "content": {"value": 1}},
            {"source": "新闻媒体", "metric_key": "GHG_Emissions", "content": {"value": 2}},
        ])
        self.assertEqual(len(prepared["inputs"]), 2)
        self.assertEqual(prepared["inputs"][0]["source_weight"], 1.0)
        self.assertEqual(prepared["inputs"][1]["source_weight"], 0.55)

    def test_single_dict_wrapped(self):
        """单个 dict 输入被包成单元素列表。"""
        prepared = self.engine._preprocess(
            {"source": "企业年报", "metric_key": "Board_Independence", "content": {"v": 1}}
        )
        self.assertEqual(len(prepared["inputs"]), 1)

    def test_defaults_filled(self):
        """缺省 data_type/source/period/entity 被填充。"""
        prepared = self.engine._preprocess([{"content": {"value": 1}, "metric_key": "GHG_Emissions"}])
        inp = prepared["inputs"][0]
        self.assertEqual(inp["data_type"], "structured")
        self.assertEqual(inp["source"], "未知")
        self.assertEqual(inp["period"], "年度")
        self.assertEqual(inp["source_weight"], 0.6)  # 未知来源默认 0.6


class TestEngineGuessMetric(unittest.TestCase):
    """_guess_metric：关键词推断 ESG 指标。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_guess_carbon(self):
        self.assertEqual(self.engine._guess_metric("碳排放 CO2 排放"), "GHG_Emissions")

    def test_guess_energy(self):
        self.assertEqual(self.engine._guess_metric("年度能耗数据"), "Energy_Consumption")

    def test_guess_water(self):
        self.assertEqual(self.engine._guess_metric("用水量取水量"), "Water_Intensity")

    def test_guess_governance(self):
        self.assertEqual(self.engine._guess_metric("董事会独立董事"), "Board_Independence")

    def test_guess_default(self):
        """无关键词命中 → 默认 GHG_Emissions。"""
        self.assertEqual(self.engine._guess_metric("无关内容"), "GHG_Emissions")


class TestEngineParsers(unittest.TestCase):
    """五种多模态解析器。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_parse_structured_dict(self):
        """结构化 dict：提取数值字段。"""
        out = self.engine._parse_structured({"a": 100, "b": {"value": 200, "unit": "tCO2"}})
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["value"], 100.0)
        self.assertEqual(out[1]["value"], 200.0)
        self.assertEqual(out[1]["unit"], "tCO2")

    def test_parse_semi_structured_text(self):
        """半结构化文本：正则抽取 数值+单位。"""
        out = self.engine._parse_semi_structured("排放 12500 tCO2，用水 85000 m3")
        values = [r["value"] for r in out]
        self.assertIn(12500.0, values)
        self.assertIn(85000.0, values)

    def test_parse_text_carbon(self):
        """文本解析：抽取碳排放数值。"""
        out = self.engine._parse_text("该公司碳排放高达 25000 吨，温室气体排放严重")
        self.assertTrue(any(r["value"] == 25000.0 for r in out))

    def test_parse_timeseries(self):
        """时序数据：逐点提取 value。"""
        out = self.engine._parse_timeseries([
            {"value": 5000, "unit": "MJ"}, {"value": 5200, "unit": "MJ"},
        ])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["value"], 5000.0)

    def test_parse_image_meta_ndvi(self):
        """图像元数据：NDVI 提取。"""
        out = self.engine._parse_image_meta({"ndvi": 0.65})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["value"], 0.65)

    def test_parse_image_meta_landuse(self):
        """图像元数据：土地利用分类。"""
        out = self.engine._parse_image_meta({"land_use": {"forest": 50, "water": 30}})
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["unit"], "ha")


class TestEngineNormalizeUnit(unittest.TestCase):
    """_normalize_unit：单位归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_same_unit_returns_value(self):
        """同单位 → 原值返回。"""
        self.assertEqual(self.engine._normalize_unit(100, "tCO2", "tCO2"), 100)

    def test_empty_from_unit_returns_value(self):
        """源单位为空 → 原值返回。"""
        self.assertEqual(self.engine._normalize_unit(100, "", "tCO2"), 100)

    def test_kg_to_tco2_conversion(self):
        """kg → tCO2 按引擎换算表转换（非物理意义，锁定实现行为）。"""
        converted = self.engine._normalize_unit(1, "kg", "tCO2")
        self.assertEqual(converted, 1000.0)


class TestEngineInferMerge(unittest.TestCase):
    """_infer：多源融合 + 加权均值 + CV。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_merge_weighted_average(self):
        """两源加权均值：(100*1.0 + 200*0.8)/1.8 = 144.4444。"""
        prepared = self.engine._preprocess([
            {"source": "政府平台", "metric_key": "GHG_Emissions",
             "content": {"value": 100}, "unit": "tCO2"},
            {"source": "企业ESG报告", "metric_key": "GHG_Emissions",
             "content": {"value": 200}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        merged = result["merged_metrics"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["consolidated_value"], round(260 / 1.8, 4))
        self.assertEqual(merged[0]["source_count"], 2)

    def test_merge_cv_computation(self):
        """两源值差异大 → CV > 0（离散度）。"""
        prepared = self.engine._preprocess([
            {"source": "政府平台", "metric_key": "GHG_Emissions",
             "content": {"value": 100}, "unit": "tCO2"},
            {"source": "新闻媒体", "metric_key": "GHG_Emissions",
             "content": {"value": 5000}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        merged = result["merged_metrics"][0]
        self.assertGreater(merged["cv"], 0.3)
        self.assertEqual(merged["range"], [100.0, 5000.0])

    def test_records_carry_data_id(self):
        """每条记录生成 data_id（md5 摘要前 12 位）。"""
        prepared = self.engine._preprocess([
            {"source": "政府平台", "metric_key": "GHG_Emissions",
             "content": {"value": 100}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(len(result["records"][0]["data_id"]), 12)


class TestEngineQualityAssessment(unittest.TestCase):
    """_quality_assessment：质量评分 + 问题清单。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_quality_fields_populated(self):
        """质量报告含 coverage/accuracy/completeness/overall。"""
        prepared = self.engine._preprocess([
            {"source": "政府平台", "metric_key": "GHG_Emissions",
             "content": {"value": 100}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        q = result["quality_report"]
        for key in ("coverage", "accuracy", "completeness", "overall", "issues"):
            self.assertIn(key, q)
        self.assertGreaterEqual(q["overall"], 0.0)
        self.assertLessEqual(q["overall"], 1.0)

    def test_quality_issues_for_high_cv(self):
        """CV > 0.3 的指标 → issues 含离散度告警。"""
        prepared = self.engine._preprocess([
            {"source": "政府平台", "metric_key": "GHG_Emissions",
             "content": {"value": 100}, "unit": "tCO2"},
            {"source": "新闻媒体", "metric_key": "GHG_Emissions",
             "content": {"value": 9000}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        issues_text = " ".join(result["quality_report"]["issues"])
        self.assertIn("离散度", issues_text)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：数据目录 / 维度摘要 / 采集日志。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_sample_input()
        self.result = self.engine.execute(self.sample["data_sources"])

    def test_data_catalog_populated(self):
        """data_catalog 含 8 个融合指标。"""
        self.assertEqual(len(self.result["data_catalog"]), 8)

    def test_dimension_summary(self):
        """维度摘要：E=4, S=2, G=2。"""
        dim = self.result["dimension_summary"]
        self.assertEqual(dim["E"]["count"], 4)
        self.assertEqual(dim["S"]["count"], 2)
        self.assertEqual(dim["G"]["count"], 2)

    def test_collection_log(self):
        """采集日志含总记录数与错误列表。"""
        log = self.result["collection_log"]
        self.assertIn("total_records", log)
        self.assertIn("errors", log)
        self.assertIn("generated_at", log)
        self.assertGreater(log["total_records"], 0)

    def test_ghg_conflict_detected(self):
        """GHG 多源冲突 → cv > 0.3。"""
        ghg = next(m for m in self.result["data_catalog"]
                   if m["metric_key"] == "GHG_Emissions")
        self.assertGreater(ghg["cv"], 0.3)
        self.assertGreaterEqual(ghg["source_count"], 3)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_input(self):
        """空输入 → 空数据目录 + overall=0。"""
        result = self.engine.execute([])
        self.assertEqual(result["data_catalog"], [])
        self.assertEqual(result["quality_report"]["overall"], 0)
        self.assertIn("无数据", result["quality_report"]["issues"])

    def test_unknown_data_type_fallback(self):
        """未知 data_type → 回退到 structured 解析器。"""
        prepared = self.engine._preprocess([
            {"data_type": "unknown_type", "source": "政府平台",
             "metric_key": "GHG_Emissions", "content": {"value": 100}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["value"], 100.0)

    def test_parse_error_recorded(self):
        """解析异常被捕获并记入 errors，不影响其他记录。"""
        prepared = self.engine._preprocess([
            {"data_type": "structured", "source": "政府平台",
             "metric_key": "GHG_Emissions", "content": "不可解析的字符串", "unit": "tCO2"},
            {"data_type": "structured", "source": "政府平台",
             "metric_key": "GHG_Emissions", "content": {"value": 100}, "unit": "tCO2"},
        ])
        result = self.engine._infer(prepared)
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["source"], "政府平台")
        # 另一条正常解析
        self.assertEqual(len(result["records"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
