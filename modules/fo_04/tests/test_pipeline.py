"""[FO-04] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_04.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class _PipelineTestBase(unittest.TestCase):
    """公共 setUp/tearDown：管理 tmpdir + pipeline 生命周期。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._pipes: list[Pipeline] = []

    def tearDown(self):
        for p in self._pipes:
            try:
                p.close()
            except Exception:
                pass
        self._pipes.clear()
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass

    def _make_pipeline(self, **overrides) -> Pipeline:
        config = {
            "db_path": str(Path(self.tmpdir.name) / "fo_04_pipeline.db"),
        }
        config.update(overrides)
        pipe = Pipeline(config=config)
        self._pipes.append(pipe)
        return pipe

    def _load_sample(self) -> dict:
        return _load_sample_input()


class TestPipelineEndToEnd(_PipelineTestBase):
    """端到端跑通。"""

    def test_pipeline_run_with_sample_input(self):
        """用 sample_input.json 端到端跑通。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "FO-04")
        self.assertIn("evidence_catalog", output)
        self.assertIn("hash_chain", output)
        self.assertIn("integrity_status", output)

    def test_pipeline_statistics_complete(self):
        """统计含 total_items / unique_hashes / file_types。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        stats = output["statistics"]
        self.assertEqual(
            stats["total_items"], len(sample["evidence_items"])
        )
        self.assertGreater(stats["unique_hashes"], 0)
        self.assertIn("file_types", stats)
        self.assertIn("alert_count", stats)

    def test_pipeline_detects_duplicates(self):
        """sample_input 含重复物证（EV-001/EV-005）→ duplicates 非空。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertGreater(len(output["duplicates"]), 0)
        self.assertTrue(
            any(g["count"] >= 2 for g in output["duplicates"])
        )

    def test_pipeline_integrity_status_populated(self):
        """完整性状态含 integrity_score / integrity_level。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        status = output["integrity_status"]
        self.assertIn("integrity_score", status)
        self.assertIn("integrity_level", status)
        self.assertIn(status["integrity_level"],
                      ("verified", "partial", "tampered"))

    def test_pipeline_alerts_generated(self):
        """sample_input 含缺失元数据 → alerts 非空。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertGreater(len(output["alerts"]), 0)
        alert_types = {a["type"] for a in output["alerts"]}
        self.assertIn("missing_metadata", alert_types)

    def test_pipeline_hash_chain_built(self):
        """哈希链包含所有物证。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertEqual(
            len(output["hash_chain"]),
            len(sample["evidence_items"]),
        )

    def test_pipeline_custody_trail_sorted(self):
        """时间线按时间戳排序。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        trail = output["custody_trail"]
        timestamps = [
            ev["time"] for ev in trail if ev.get("time")
        ]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_pipeline_empty_input(self):
        """空输入 → 0 items，不报错。"""
        pipe = self._make_pipeline()
        output = pipe.run({"evidence_items": []})

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["statistics"]["total_items"], 0)


class TestPipelinePortableDB(_PipelineTestBase):
    """PortableDB 持久化。"""

    def test_pipeline_creates_tables(self):
        """Pipeline 初始化后 PortableDB 含 evidence_items / forensic_timeline 表。"""
        db_path = Path(self.tmpdir.name) / "fo_04_pipeline.db"
        self._make_pipeline()
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        self.assertIn("evidence_items", tables)
        self.assertIn("forensic_timeline", tables)

    def test_pipeline_persists_evidence_items(self):
        """Pipeline 把原始取证物持久化到 evidence_items 表。"""
        db_path = Path(self.tmpdir.name) / "fo_04_pipeline.db"
        pipe = self._make_pipeline()
        sample = self._load_sample()
        pipe.run(sample)

        with PortableDB(db_path) as db:
            count = db.count("evidence_items")
        self.assertEqual(count, len(sample["evidence_items"]))

    def test_pipeline_persists_chain_hashes(self):
        """Pipeline 更新 evidence_items 的 content_hash / chain_hash。"""
        db_path = Path(self.tmpdir.name) / "fo_04_pipeline.db"
        pipe = self._make_pipeline()
        sample = self._load_sample()
        pipe.run(sample)

        with PortableDB(db_path) as db:
            rows = db.all("evidence_items")
        # 所有行都应有 content_hash（非空）
        for r in rows:
            self.assertTrue(r["content_hash"])
            self.assertTrue(r["chain_hash"])

    def test_pipeline_persists_timeline(self):
        """Pipeline 把时间线持久化到 forensic_timeline 表。"""
        db_path = Path(self.tmpdir.name) / "fo_04_pipeline.db"
        pipe = self._make_pipeline()
        sample = self._load_sample()
        pipe.run(sample)

        with PortableDB(db_path) as db:
            count = db.count("forensic_timeline")
        self.assertEqual(count, len(sample["evidence_items"]))


class TestPipelineCustomization(_PipelineTestBase):
    """custom_thresholds + custom_rules 生效。"""

    def test_thresholds_integrity_level(self):
        """apply_thresholds 标记 integrity_level。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        status = output["integrity_status"]
        self.assertIn(status["integrity_level"],
                      ("verified", "partial", "tampered"))
        self.assertGreaterEqual(status["integrity_score"], 0.0)
        self.assertLessEqual(status["integrity_score"], 1.0)

    def test_custom_rules_missing_metadata_alert(self):
        """缺失元数据的物证触发 missing_metadata 告警。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        # EV-004 author 为空, EV-008 author+timestamp 为空
        meta_alerts = [
            a for a in output["alerts"]
            if a["type"] == "missing_metadata"
        ]
        self.assertGreater(len(meta_alerts), 0)
        alert_ids = {a["evidence_id"] for a in meta_alerts}
        self.assertIn("EV-004", alert_ids)
        self.assertIn("EV-008", alert_ids)

    def test_custom_rules_custody_gap_alert(self):
        """大时间间隙触发 custody_gap 告警。"""
        pipe = self._make_pipeline(rules={"custody_gap_hours": 48})
        sample = self._load_sample()
        output = pipe.run(sample)

        gap_alerts = [
            a for a in output["alerts"] if a["type"] == "custody_gap"
        ]
        self.assertGreater(len(gap_alerts), 0)

    def test_custom_rules_tamper_alert(self):
        """expected_hash 与 content_hash 不匹配 → tamper_alert。"""
        sample = self._load_sample()
        # 给第一个物证注入错误的 expected_hash
        sample["evidence_items"][0]["expected_hash"] = "wrong_hash"
        pipe = self._make_pipeline()
        output = pipe.run(sample)

        catalog = output["evidence_catalog"]
        tampered = [c for c in catalog if c.get("tamper_alert")]
        self.assertGreater(len(tampered), 0)

    def test_statistics_alert_count_consistent(self):
        """统计的 alert_count 与 alerts 列表长度一致。"""
        pipe = self._make_pipeline()
        sample = self._load_sample()
        output = pipe.run(sample)

        self.assertEqual(
            output["statistics"]["alert_count"],
            len(output["alerts"]),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
