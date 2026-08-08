"""[CO-08] engine 单测：SQL血缘解析 + 图构建 + 跨境检测 + 风险评分 + BFS影响分析。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_08.engine import KGEngine, _parse_sql_tables, _strip_table_alias

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> KGEngine:
    config = {"db_path": str(Path(tmpdir) / "co_08_test.db")}
    config.update(overrides)
    eng = KGEngine(config=config)
    eng.setup()
    return eng


class TestSqlParsing(unittest.TestCase):
    """SQL 血缘解析函数测试。"""

    def test_parse_select(self):
        result = _parse_sql_tables("SELECT * FROM users WHERE 1=1")
        self.assertIn("users", result["sources"])
        self.assertEqual(len(result["targets"]), 0)

    def test_parse_join(self):
        result = _parse_sql_tables("SELECT * FROM orders JOIN customers ON orders.cid = customers.id")
        self.assertIn("orders", result["sources"])
        self.assertIn("customers", result["sources"])

    def test_parse_insert_into(self):
        result = _parse_sql_tables("INSERT INTO target_table SELECT * FROM source_table")
        self.assertIn("target_table", result["targets"])
        self.assertIn("source_table", result["sources"])

    def test_parse_create_as(self):
        result = _parse_sql_tables("CREATE TABLE new_table AS SELECT * FROM old_table")
        self.assertIn("new_table", result["targets"])
        self.assertIn("old_table", result["sources"])

    def test_parse_update(self):
        result = _parse_sql_tables("UPDATE target_tbl SET col = 1 WHERE id IN (SELECT id FROM src)")
        self.assertIn("target_tbl", result["targets"])

    def test_parse_empty(self):
        result = _parse_sql_tables("")
        self.assertEqual(len(result["sources"]), 0)
        self.assertEqual(len(result["targets"]), 0)

    def test_parse_with_comments(self):
        sql = "-- comment\nSELECT * FROM real_table /* block */"
        result = _parse_sql_tables(sql)
        self.assertIn("real_table", result["sources"])

    def test_strip_table_alias(self):
        self.assertEqual(_strip_table_alias("`my_table`"), "my_table")
        self.assertEqual(_strip_table_alias("  spaced  "), "spaced")


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + model 字典。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_model_loaded(self):
        self.assertIsNotNone(self.engine.model)
        self.assertIn("entities", self.engine.model)
        self.assertIn("adj", self.engine.model)
        self.assertIn("adj_rev", self.engine.model)
        self.assertIn("countries", self.engine.model)

    def test_db_tables_created(self):
        tables = self.engine.db.tables()
        self.assertIn("locations", tables)
        self.assertIn("entities", tables)
        self.assertIn("edges", tables)
        self.assertIn("flows", tables)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据血缘图构建。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_entities_built(self):
        prepared = self.engine._preprocess(self.sample)
        entities = prepared["entities"]
        self.assertIn("sys-erp", entities)
        self.assertIn("sys-crm", entities)
        self.assertIn("ds-gl", entities)
        self.assertEqual(entities["sys-erp"]["entity_type"], "System")
        self.assertEqual(entities["ds-gl"]["entity_type"], "Dataset")

    def test_adj_built(self):
        prepared = self.engine._preprocess(self.sample)
        adj = prepared["adj"]
        # SYS-ERP → DS-GL (PRODUCES)
        self.assertIn("ds-gl", adj.get("sys-erp", {}))
        # ETL transforms: DS-GL → DS-REPORT, DS-CUST → DS-REPORT
        self.assertIn("ds-report", adj.get("ds-gl", {}))

    def test_adj_rev_built(self):
        prepared = self.engine._preprocess(self.sample)
        adj_rev = prepared["adj_rev"]
        self.assertIn("sys-erp", adj_rev.get("ds-gl", {}))

    def test_countries_loaded(self):
        self.engine._preprocess(self.sample)
        countries = self.engine.model["countries"]
        self.assertEqual(countries.get("LOC-CN"), "CN")
        self.assertEqual(countries.get("LOC-US"), "US")

    def test_target_passed_through(self):
        prepared = self.engine._preprocess(self.sample)
        self.assertEqual(prepared["target"]["entity_id"], "DS-REPORT")

    def test_non_dict_input_raises(self):
        with self.assertRaises(ValueError):
            self.engine._preprocess([1, 2, 3])


class TestEngineInfer(unittest.TestCase):
    """_infer：跨境检测 + 路径风险评分 + 影响分析。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")
        self.prepared = self.engine._preprocess(self.sample)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_cross_border_detected(self):
        result = self.engine._infer(self.prepared)
        cb = result["cross_border_flows"]
        self.assertGreaterEqual(len(cb), 1)
        countries = {cb[0]["src_country"], cb[0]["dst_country"]}
        self.assertTrue(len(countries) >= 2)

    def test_flows_computed(self):
        result = self.engine._infer(self.prepared)
        flows = result["flows"]
        self.assertGreaterEqual(len(flows), 1)
        for f in flows:
            self.assertIn("risk_score", f)
            self.assertIn("risk_level", f)
            self.assertIn("path", f)
            self.assertIn("hops", f)

    def test_flows_sorted_by_risk(self):
        result = self.engine._infer(self.prepared)
        flows = result["flows"]
        if len(flows) >= 2:
            self.assertGreaterEqual(flows[0]["risk_score"], flows[-1]["risk_score"])

    def test_upstream_impact(self):
        result = self.engine._infer(self.prepared)
        upstream = result["upstream_impact"]
        self.assertIn("ds-report", upstream)
        self.assertIsInstance(upstream["ds-report"], list)

    def test_downstream_impact(self):
        result = self.engine._infer(self.prepared)
        downstream = result["downstream_impact"]
        self.assertIn("ds-report", downstream)

    def test_risk_level_values(self):
        result = self.engine._infer(self.prepared)
        valid_levels = {"low", "medium", "high", "critical"}
        for f in result["flows"]:
            self.assertIn(f["risk_level"], valid_levels)

    def test_compliance_tags_for_cross_border(self):
        result = self.engine._infer(self.prepared)
        for f in result["flows"]:
            if f.get("is_cross_border"):
                self.assertIn("cross_border_transfer", f["compliance_tags"])

    def test_empty_input(self):
        fresh_engine = _make_engine(tempfile.mkdtemp())
        prepared = fresh_engine._preprocess({})
        result = fresh_engine._infer(prepared)
        self.assertEqual(len(result["flows"]), 0)
        self.assertEqual(len(result["cross_border_flows"]), 0)
        fresh_engine.close()


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：持久化 + 统计摘要。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_fixture("sample_input.json")

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_statistics_generated(self):
        result = self.engine.execute(self.sample)
        stats = result["statistics"]
        self.assertIn("total_entities", stats)
        self.assertIn("total_flows", stats)
        self.assertIn("cross_border_count", stats)
        self.assertIn("by_risk_level", stats)
        self.assertIn("high_risk_flows", stats)

    def test_flows_persisted(self):
        result = self.engine.execute(self.sample)
        rows = self.engine.db.all("flows")
        self.assertEqual(len(rows), result["statistics"]["total_flows"])

    def test_statistics_counts_match(self):
        result = self.engine.execute(self.sample)
        stats = result["statistics"]
        self.assertEqual(stats["total_flows"], len(result["flows"]))
        self.assertEqual(stats["cross_border_count"], len(result["cross_border_flows"]))


class TestEngineExecute(unittest.TestCase):
    """execute：端到端集成。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_execute_full(self):
        sample = _load_fixture("sample_input.json")
        result = self.engine.execute(sample)
        self.assertIsInstance(result, dict)
        self.assertIn("entities", result)
        self.assertIn("flows", result)
        self.assertIn("cross_border_flows", result)
        self.assertIn("statistics", result)

    def test_execute_empty_dict(self):
        result = self.engine.execute({})
        self.assertEqual(result["statistics"]["total_entities"], 0)
        self.assertEqual(result["statistics"]["total_flows"], 0)

    def test_execute_no_target(self):
        sample = _load_fixture("sample_input.json")
        sample["target"] = {}
        result = self.engine.execute(sample)
        self.assertEqual(result["upstream_impact"], {})
        self.assertEqual(result["downstream_impact"], {})


if __name__ == "__main__":
    unittest.main()
