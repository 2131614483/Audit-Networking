"""[FO-02] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化 + custom 生效。

unittest 风格（不依赖 pytest）。
Windows 下测试结束前显式 pipe.engine.close() 释放 db 句柄，避免 PermissionError。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_02.pipeline import Pipeline
from modules.fo_02.custom.custom_thresholds import apply_thresholds
from modules.fo_02.custom.custom_rules import apply_custom_rules
from modules.fo_02.custom.custom_formatter import format_output
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class _PipeTestBase(unittest.TestCase):
    """Pipeline 测试基类：隔离 tmp 目录 + 自动关闭 engine db。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._pipes: list[Pipeline] = []
        # addCleanup 为 LIFO：后注册先执行 → 先关连接再删目录，避免 PermissionError
        self.addCleanup(self.tmpdir.cleanup)
        self.addCleanup(self._close_pipes)

    def _close_pipes(self):
        for pipe in self._pipes:
            try:
                pipe.engine.close()
            except Exception:
                pass

    def _make_pipeline(self, **overrides) -> Pipeline:
        """构造隔离 db 的 pipeline。"""
        config = {"db_path": str(Path(self.tmpdir.name) / "fo_02_pipeline.db")}
        config.update(overrides)
        pipe = Pipeline(config=config)
        self._pipes.append(pipe)
        return pipe


class TestPipelineEndToEnd(_PipeTestBase):
    """端到端跑通。"""

    def test_pipeline_run_with_sample(self):
        """用 sample_input.json 端到端跑通，输出含舞弊网络报告结构。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "FO-02")
        self.assertIn("summary", output)
        self.assertIn("key_findings", output)
        self.assertIn("entities", output)
        self.assertIn("relationships", output)

    def test_pipeline_summary_complete(self):
        """摘要含全部统计字段 + network_risk_level。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        s = output["summary"]
        for k in ("entity_count", "transaction_count", "community_count",
                  "anomaly_count", "pattern_count", "high_risk_entities",
                  "total_volume", "network_risk_level"):
            self.assertIn(k, s)
        self.assertEqual(s["entity_count"], 7)
        self.assertEqual(s["transaction_count"], 13)

    def test_pipeline_detects_fraud_ring(self):
        """样本含循环交易 E1→E2→E3→E1 → key_findings.fraud_ring_flag=True。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        self.assertTrue(output["key_findings"]["fraud_ring_flag"])
        self.assertGreater(len(output["key_findings"]["fraud_ring_entities"]), 0)

    def test_pipeline_detects_anomaly_entities(self):
        """样本含异常大额交易 → key_findings.anomaly_entities 含 E1。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        self.assertGreater(len(output["key_findings"]["anomaly_entities"]), 0)
        self.assertIn("E1", output["key_findings"]["anomaly_entities"])

    def test_pipeline_visualization_complete(self):
        """可视化数据含 nodes / edges / community_map。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        vis = output["visualization"]
        self.assertEqual(len(vis["nodes"]), 7)
        self.assertEqual(len(vis["edges"]), 13)
        self.assertIsInstance(vis["community_map"], dict)

    def test_pipeline_communities_list_built(self):
        """社区列表构造正确，含成员与风险等级。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        comms = output["communities"]
        self.assertGreater(len(comms), 0)
        for c in comms:
            self.assertIn("community_id", c)
            self.assertIn("member_count", c)
            self.assertIn("members", c)

    def test_pipeline_relationships_preserved(self):
        """交易关系边完整保留。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        rels = output["relationships"]
        self.assertEqual(len(rels), 13)
        for r in rels:
            self.assertIn("src", r)
            self.assertIn("dst", r)
            self.assertIn("amount", r)

    def test_pipeline_total_volume_matches(self):
        """总交易额 = 各边金额之和。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        expected = sum(r["amount"] for r in output["relationships"])
        self.assertAlmostEqual(output["summary"]["total_volume"], expected)


class TestPipelinePortableDB(_PipeTestBase):
    """PortableDB 持久化。"""

    def test_pipeline_persists_entities(self):
        """Pipeline 把实体持久化到 fraud_entities 表。"""
        db_path = Path(self.tmpdir.name) / "fo_02_pipeline.db"
        pipe = self._make_pipeline()
        sample = _load_sample()
        pipe.run(sample)
        with PortableDB(db_path) as db:
            count = db.count("fraud_entities")
        self.assertEqual(count, len(sample["entities"]))

    def test_pipeline_persists_transactions(self):
        """Pipeline 把交易持久化到 fraud_transactions 表。"""
        db_path = Path(self.tmpdir.name) / "fo_02_pipeline.db"
        pipe = self._make_pipeline()
        sample = _load_sample()
        pipe.run(sample)
        with PortableDB(db_path) as db:
            count = db.count("fraud_transactions")
        self.assertEqual(count, len(sample["transactions"]))

    def test_pipeline_persists_patterns(self):
        """Pipeline 把发现的模式持久化到 fraud_patterns 表。"""
        db_path = Path(self.tmpdir.name) / "fo_02_pipeline.db"
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample())
        with PortableDB(db_path) as db:
            rows = db.all("fraud_patterns")
        self.assertEqual(len(rows), output["summary"]["pattern_count"])
        # JSON 软类型字段自动反序列化
        for r in rows:
            self.assertIsInstance(r["entities_involved"], list)
            self.assertIsInstance(r["extra"], dict)

    def test_pipeline_db_has_three_tables(self):
        """Pipeline run 后 PortableDB 含 3 张表。"""
        db_path = Path(self.tmpdir.name) / "fo_02_pipeline.db"
        pipe = self._make_pipeline()
        pipe.run(_load_sample())
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        self.assertIn("fraud_entities", tables)
        self.assertIn("fraud_transactions", tables)
        self.assertIn("fraud_patterns", tables)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效（纯函数测试，无需隔离 db）。"""

    def test_thresholds_assign_grades(self):
        """apply_thresholds 按分数设置 network_risk_grade。"""
        result = {
            "risk_scores": {
                "E1": {"total": 0.8, "pagerank": 0.5},
                "E2": {"total": 0.4, "pagerank": 0.2},
                "E3": {"total": 0.1, "pagerank": 0.1},
            },
            "entities": {"E1": {"name": "A"}, "E2": {"name": "B"}, "E3": {"name": "C"}},
            "communities": {"E1": "C1", "E2": "C1", "E3": "C2"},
        }
        out = apply_thresholds(result, {})
        self.assertEqual(out["risk_scores"]["E1"]["network_risk_grade"], "critical")
        self.assertEqual(out["risk_scores"]["E2"]["network_risk_grade"], "medium")
        self.assertEqual(out["risk_scores"]["E3"]["network_risk_grade"], "low")
        self.assertIn("applied_thresholds", out)

    def test_thresholds_key_persons(self):
        """高中心性 + 高风险 → key_persons_of_interest。"""
        result = {
            "risk_scores": {
                "E1": {"total": 0.8, "pagerank": 0.9},
            },
            "entities": {"E1": {"name": "关键"}},
            "communities": {"E1": "C1"},
        }
        out = apply_thresholds(result, {})
        self.assertEqual(len(out["key_persons_of_interest"]), 1)
        self.assertEqual(out["key_persons_of_interest"][0]["entity_id"], "E1")

    def test_custom_rules_fraud_ring(self):
        """循环交易 → fraud_ring_flag=True。"""
        result = {
            "patterns": [{"type": "循环交易", "entities_involved": ["A", "B", "C"]}],
            "risk_scores": {},
            "communities": {},
            "anomalies": [],
        }
        out = apply_custom_rules(result, {})
        self.assertTrue(out["fraud_ring_flag"])
        self.assertIn("fraud_ring_detected", [f["rule"] for f in out["rule_flags"]])

    def test_custom_rules_anomaly_entities(self):
        """异常交易关联实体标记。"""
        result = {
            "patterns": [],
            "risk_scores": {},
            "communities": {},
            "anomalies": [{"src": "A", "dst": "B", "amount": 999}],
        }
        out = apply_custom_rules(result, {})
        self.assertIn("A", out["anomaly_entities"])
        self.assertIn("B", out["anomaly_entities"])

    def test_formatter_invalid_input(self):
        """非法输入 → error 状态。"""
        out = format_output("not a dict")
        self.assertEqual(out["status"], "error")


class TestPipelineCollect(_PipeTestBase):
    """_collect：输入归一化 + 持久化。"""

    def test_collect_non_dict_returns_empty(self):
        """非 dict 输入返回空结构。"""
        pipe = self._make_pipeline()
        collected = pipe._collect([1, 2, 3])
        self.assertEqual(collected, {"entities": [], "transactions": []})

    def test_collect_persists_to_db(self):
        """_collect 把数据持久化到 PortableDB。"""
        db_path = Path(self.tmpdir.name) / "fo_02_pipeline.db"
        pipe = self._make_pipeline()
        sample = _load_sample()
        pipe._collect(sample)
        with PortableDB(db_path) as db:
            ent_count = db.count("fraud_entities")
            tx_count = db.count("fraud_transactions")
        self.assertEqual(ent_count, len(sample["entities"]))
        self.assertEqual(tx_count, len(sample["transactions"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
