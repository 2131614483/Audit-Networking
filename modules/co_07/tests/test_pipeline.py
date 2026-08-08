"""[CO-07] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

unittest 风格（不依赖 pytest）。
Windows 下测试结束前显式 pipe.engine.close() 释放 db 句柄，避免 PermissionError。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_07.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
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
        config = {"db_path": str(Path(self.tmpdir.name) / "co_07_pipeline.db")}
        config.update(overrides)
        pipe = Pipeline(config=config)
        self._pipes.append(pipe)
        return pipe


class TestPipelineEndToEnd(_PipeTestBase):
    """端到端跑通。"""

    def test_pipeline_run_with_sample(self):
        """用 sample_input.json 端到端跑通。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample_input())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-07")
        self.assertIn("asset_catalog", output)
        self.assertIn("classification_summary", output)
        self.assertIn("sensitivity_summary", output)
        self.assertIn("alerts", output)
        self.assertIn("statistics", output)

    def test_pipeline_asset_catalog_populated(self):
        """资产目录含 5 条资产。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample_input())
        catalog = output["asset_catalog"]
        self.assertEqual(len(catalog), 5)
        ids = {a["asset_id"] for a in catalog}
        self.assertIn("AST001", ids)
        self.assertIn("AST005", ids)

    def test_pipeline_statistics_complete(self):
        """统计含 total_assets / total_fields / l3_l4_count / rule_summary。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample_input())
        stats = output["statistics"]
        self.assertEqual(stats["total_assets"], 5)
        self.assertEqual(stats["total_fields"], 20)
        self.assertIn("l3_l4_count", stats)
        self.assertIn("rule_summary", stats)

    def test_pipeline_thresholds_applied(self):
        """apply_thresholds 为每个资产写入 sensitivity_grade。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample_input())
        for a in output["asset_catalog"]:
            self.assertIn(a["sensitivity_grade"],
                          ("public", "internal", "confidential", "restricted"))
        grade_dist = output["classification_summary"]["grade_distribution"]
        total = sum(grade_dist.values())
        self.assertEqual(total, 5)

    def test_pipeline_pii_encryption_alert(self):
        """PII 资产未加密 → needs_encryption + critical 告警。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample_input())
        ast001 = next(
            a for a in output["asset_catalog"] if a["asset_id"] == "AST001"
        )
        self.assertTrue(ast001["needs_encryption"])
        pii_alerts = [
            al for al in output["alerts"]
            if al["rule"] == "pii_without_encryption"
        ]
        self.assertGreater(len(pii_alerts), 0)

    def test_pipeline_public_zone_alert(self):
        """敏感数据在公开区域 → public_zone_exposure + high 告警。"""
        pipe = self._make_pipeline()
        output = pipe.run(_load_sample_input())
        ast005 = next(
            a for a in output["asset_catalog"] if a["asset_id"] == "AST005"
        )
        self.assertTrue(ast005["public_zone_exposure"])
        zone_alerts = [
            al for al in output["alerts"]
            if al["rule"] == "sensitive_in_public_zone"
        ]
        self.assertGreater(len(zone_alerts), 0)

    def test_pipeline_persists_assets_to_db(self):
        """Pipeline 把资产持久化到 assets 表。"""
        db_path = Path(self.tmpdir.name) / "co_07_pipeline.db"
        pipe = self._make_pipeline()
        pipe.run(_load_sample_input())
        with PortableDB(db_path) as db:
            self.assertEqual(db.count("assets"), 5)

    def test_pipeline_persists_fields_to_db(self):
        """Pipeline 把字段持久化到 fields 表。"""
        db_path = Path(self.tmpdir.name) / "co_07_pipeline.db"
        pipe = self._make_pipeline()
        pipe.run(_load_sample_input())
        with PortableDB(db_path) as db:
            self.assertEqual(db.count("fields"), 20)

    def test_pipeline_list_input(self):
        """裸 list 输入也可处理。"""
        pipe = self._make_pipeline()
        sample = _load_sample_input()
        output = pipe.run(sample["assets"])
        self.assertEqual(output["status"], "ok")
        self.assertEqual(len(output["asset_catalog"]), 5)

    def test_pipeline_reproducibility(self):
        """相同输入 → 相同输出（确定性）。"""
        sample = _load_sample_input()
        out1 = self._make_pipeline(
            db_path=str(Path(self.tmpdir.name) / "p1.db")
        ).run(sample)
        out2 = self._make_pipeline(
            db_path=str(Path(self.tmpdir.name) / "p2.db")
        ).run(sample)

        self.assertEqual(
            out1["statistics"]["total_assets"],
            out2["statistics"]["total_assets"],
        )
        self.assertEqual(
            out1["classification_summary"]["by_level"],
            out2["classification_summary"]["by_level"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
