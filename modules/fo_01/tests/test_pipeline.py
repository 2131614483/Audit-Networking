"""[FO-01] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

unittest 风格（不依赖 pytest）。
Windows 下测试结束前显式 pipe.engine.close() 释放 db 句柄，避免 PermissionError。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_01.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_mock_input():
    """加载 mock_input.json。"""
    with open(_FIXTURES / "mock_input.json", encoding="utf-8") as f:
        return json.load(f)


def _load_fixture_txs():
    """加载 transactions.jsonl。"""
    path = _FIXTURES / "transactions.jsonl"
    txs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                txs.append(json.loads(line))
    return txs


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
        config = {
            "threshold": {"confidence": 0.85},
            "db_path": str(Path(self.tmpdir.name) / "fo_01_pipeline.db"),
            "fixtures_dir": str(_FIXTURES),
            "random_seed": 42,
        }
        config.update(overrides)
        pipe = Pipeline(config=config)
        self._pipes.append(pipe)
        return pipe


class TestPipelineEndToEnd(_PipeTestBase):
    """端到端跑通。"""

    def test_pipeline_run_with_mock_input(self):
        """用 mock_input.json 端到端跑通，输出含可疑交易 + 统计。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "FO-01")
        self.assertIn("suspicious_transactions", output)
        self.assertIn("layer_summary", output)
        self.assertIn("statistics", output)

    def test_pipeline_statistics_complete(self):
        """统计含：总交易数 / 可疑数 / 各层命中数 / 覆盖率 / 风险分布。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        stats = output["statistics"]
        self.assertEqual(stats["total_transactions"], len(mock["transactions"]))
        self.assertGreaterEqual(stats["suspicious_count"], 0)
        self.assertEqual(stats["coverage_rate"], 1.0)
        self.assertIn("layer_hit_counts", stats)
        self.assertIn("risk_distribution", stats)
        # 风险分布含 high / medium / low
        dist = stats["risk_distribution"]
        self.assertIn("high", dist)
        self.assertIn("medium", dist)
        self.assertIn("low", dist)

    def test_pipeline_detects_anomalies_in_mock(self):
        """mock_input 含注入异常 → 可疑交易列表非空。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        suspicious = output["suspicious_transactions"]
        self.assertGreater(len(suspicious), 0)
        # 大额异常交易（MOCK021: 500万）应在可疑列表中
        tx_ids = {s["tx_id"] for s in suspicious}
        self.assertIn("MOCK021", tx_ids)

    def test_pipeline_layer_summary_populated(self):
        """各层摘要含 statistical / unsupervised / supervised / graph。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        summary = output["layer_summary"]
        self.assertIn("statistical", summary)
        self.assertIn("unsupervised", summary)
        self.assertIn("supervised", summary)
        self.assertIn("graph", summary)

    def test_pipeline_graph_layer_detects_hidden_links(self):
        """mock_input 含影子公司丙/丁（共享地址+法人）→ 图谱层发现隐藏关联。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        graph_summary = output["layer_summary"]["graph"]
        self.assertGreater(graph_summary["hidden_links"], 0)
        # 影子公司丙/丁的交易应被标记
        suspicious = output["suspicious_transactions"]
        tx_ids = {s["tx_id"] for s in suspicious}
        self.assertIn("MOCK029", tx_ids)
        self.assertIn("MOCK030", tx_ids)

    def test_pipeline_full_fixture_run(self):
        """用全量 transactions.jsonl（115条）端到端跑通。"""
        pipe = self._make_pipeline()
        txs = _load_fixture_txs()
        output = pipe.run({"transactions": txs})

        self.assertEqual(output["status"], "ok")
        stats = output["statistics"]
        self.assertEqual(stats["total_transactions"], len(txs))
        self.assertGreater(stats["suspicious_count"], 0)
        # 各层至少有命中
        layer_hits = stats["layer_hit_counts"]
        self.assertGreater(layer_hits["statistical"], 0)
        self.assertGreater(layer_hits["supervised"], 0)
        self.assertGreater(layer_hits["graph"], 0)


class TestPipelinePortableDB(_PipeTestBase):
    """PortableDB 持久化。"""

    def test_pipeline_db_has_four_tables(self):
        """Pipeline 初始化后 PortableDB 含 4 张表。"""
        db_path = Path(self.tmpdir.name) / "fo_01_pipeline.db"
        self._make_pipeline()
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        self.assertIn("transactions", tables)
        self.assertIn("fraud_flags", tables)
        self.assertIn("fraud_patterns", tables)
        self.assertIn("scan_results", tables)

    def test_pipeline_persists_transactions(self):
        """Pipeline 把交易持久化到 transactions 表。"""
        db_path = Path(self.tmpdir.name) / "fo_01_pipeline.db"
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        pipe.run(mock)

        with PortableDB(db_path) as db:
            count = db.count("transactions")
        self.assertEqual(count, len(mock["transactions"]))

    def test_pipeline_persists_scan_results(self):
        """Pipeline 把可疑交易扫描结果持久化到 scan_results 表。"""
        db_path = Path(self.tmpdir.name) / "fo_01_pipeline.db"
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        with PortableDB(db_path) as db:
            rows = db.all("scan_results")
        self.assertEqual(len(rows), output["statistics"]["suspicious_count"])
        # JSON 软类型字段自动反序列化
        for r in rows:
            self.assertIsInstance(r["hit_layers"], list)
            self.assertIsInstance(r["evidence_chain"], list)
            self.assertIsInstance(r["matched_patterns"], list)
            self.assertIn(r["risk_level"], ("high", "medium", "low"))

    def test_pipeline_persists_fraud_flags(self):
        """Pipeline 把命中标记持久化到 fraud_flags 表（按层分解）。"""
        db_path = Path(self.tmpdir.name) / "fo_01_pipeline.db"
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        pipe.run(mock)

        with PortableDB(db_path) as db:
            rows = db.all("fraud_flags")
            layers = {r["layer"] for r in rows}
        self.assertGreater(len(rows), 0)
        # 至少含 statistical 层标记
        self.assertIn("statistical", layers)

    def test_pipeline_fraud_patterns_seeded(self):
        """Pipeline 初始化后 fraud_patterns 表从 fixtures 导入至少 10 条。"""
        db_path = Path(self.tmpdir.name) / "fo_01_pipeline.db"
        self._make_pipeline()
        with PortableDB(db_path) as db:
            count = db.count("fraud_patterns")
        self.assertGreaterEqual(count, 10)


class TestPipelineCustomization(_PipeTestBase):
    """custom_thresholds + custom_rules 生效。"""

    def test_thresholds_applied(self):
        """apply_thresholds 标记 confirmed_suspicious（score >= 0.85）。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        # 至少有一个可疑交易的 risk_score >= 0.85
        confirmed = [
            s for s in output["suspicious_transactions"]
            if s.get("confirmed_suspicious")
        ]
        # mock 含大额异常（多层命中）→ 应有高置信度可疑
        self.assertGreater(len(confirmed), 0)

    def test_custom_rules_large_amount_upgraded(self):
        """金额 > 100万 → 自动升级为 high。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        # MOCK021: 500万大额 → 应为 high
        for s in output["suspicious_transactions"]:
            if s["tx_id"] == "MOCK021":
                self.assertEqual(s["risk_level"], "high")
                break

    def test_custom_rules_related_party_review(self):
        """关联方交易 → need_review = True。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        # MOCK028: 关联方交易
        for s in output["suspicious_transactions"]:
            if s["tx_id"] == "MOCK028":
                self.assertTrue(s["need_review"])
                break

    def test_custom_rules_off_hours_marked(self):
        """非营业时间交易 → off_hours = True。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        # MOCK027: 23:30 非营业时间
        for s in output["suspicious_transactions"]:
            if s["tx_id"] == "MOCK027":
                self.assertTrue(s["off_hours"])
                break

    def test_risk_distribution_consistent(self):
        """风险分布：high + medium + low = suspicious_count。"""
        pipe = self._make_pipeline()
        mock = _load_mock_input()
        output = pipe.run(mock)

        stats = output["statistics"]
        dist = stats["risk_distribution"]
        self.assertEqual(
            dist["high"] + dist["medium"] + dist["low"],
            stats["suspicious_count"],
        )


class TestPipelineReproducibility(_PipeTestBase):
    """可复现性（固定 random_seed）。"""

    def test_same_seed_same_results(self):
        """相同 random_seed → 相同 iForest 结果。"""
        mock = _load_mock_input()
        out1 = self._make_pipeline(
            db_path=str(Path(self.tmpdir.name) / "p1.db")
        ).run(mock)
        out2 = self._make_pipeline(
            db_path=str(Path(self.tmpdir.name) / "p2.db")
        ).run(mock)

        # iForest 异常评分应一致
        s1 = out1["layer_summary"]["unsupervised"]["iso_forest_flagged"]
        s2 = out2["layer_summary"]["unsupervised"]["iso_forest_flagged"]
        self.assertEqual(s1, s2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
