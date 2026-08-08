"""[FA-07] pipeline 端到端单测：run(mock_input) 全流程 + PortableDB 持久化。

unittest 风格（不依赖 pytest）。用独立临时 PortableDB 隔离持久化。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fa_07.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_mock_input() -> dict:
    with open(_FIXTURES / "mock_input.json", encoding="utf-8") as f:
        return json.load(f)


class PipelineE2ETest(unittest.TestCase):
    """pipeline 端到端测试。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = Path(self._tmp.name) / "fa_07.db"
        self.pipe = Pipeline(config={
            "threshold": {"confidence": 0.85},
            "db_path": str(self.db_path),
            "fixtures_dir": str(_FIXTURES),
        })
        # LIFO：先关闭 PortableDB 连接，再清理临时目录（Windows 文件占用）
        self.addCleanup(self.pipe.engine.close)

    def test_pipeline_run_e2e(self) -> None:
        """端到端：run(mock_input) 返回 status=ok 且生成多份底稿。"""
        out = self.pipe.run(_load_mock_input())
        self.assertEqual(out["status"], "ok")
        self.assertGreater(len(out["workpaper_directory"]), 0)
        self.assertGreater(len(out["workpapers"]), 0)

    def test_statistics_fields(self) -> None:
        """统计字段齐全且数值合理。"""
        out = self.pipe.run(_load_mock_input())
        stats = out["statistics"]
        self.assertGreater(stats["total_workpapers"], 5)
        self.assertGreaterEqual(stats["covered_subjects"], 7)
        self.assertGreater(stats["cross_references"], 0)
        self.assertEqual(stats["core_templates"], 16)
        self.assertEqual(stats["library_total_meta"], 200)
        self.assertGreater(stats["completeness_avg"], 0.0)

    def test_cross_reference_graph(self) -> None:
        """交叉引用图 nodes/edges 非空，且存在 linked 边。"""
        out = self.pipe.run(_load_mock_input())
        graph = out["cross_reference_graph"]
        self.assertGreater(len(graph["nodes"]), 0)
        self.assertGreater(len(graph["edges"]), 0)
        linked = [e for e in graph["edges"] if e["status"] == "linked"]
        self.assertGreater(len(linked), 0)

    def test_tier_distribution(self) -> None:
        """完成度分级：complete 与 supplement 档均有出现。"""
        out = self.pipe.run(_load_mock_input())
        tiers = {wp["tier"] for wp in out["workpaper_directory"]}
        self.assertIn("complete", tiers)
        self.assertIn("supplement", tiers)

    def test_review_marking(self) -> None:
        """warning 级底稿标记 needs_review=True 且 review_reasons 非空。"""
        out = self.pipe.run(_load_mock_input())
        reviewed = [wp for wp in out["workpaper_directory"] if wp["needs_review"]]
        self.assertGreater(len(reviewed), 0)
        self.assertTrue(all(wp["review_reasons"] for wp in reviewed))

    def test_persistence_to_portable_db(self) -> None:
        """PortableDB 持久化：workpapers / cross_references / generation_logs 表有数据。"""
        self.pipe.run(_load_mock_input())
        db = self.pipe.engine.db
        self.assertIsNotNone(db)
        self.assertGreater(db.count("workpapers"), 0)
        self.assertGreater(db.count("cross_references"), 0)
        self.assertGreater(db.count("generation_logs"), 0)
        # generation_logs 应包含批次汇总与底稿生成两类动作
        actions = {row["action"] for row in db.all("generation_logs")}
        self.assertIn("generate_workpaper", actions)
        self.assertIn("batch_summary", actions)

    def test_persistence_workpaper_content_intact(self) -> None:
        """持久化的底稿含填充内容与结论（payload 反序列化为 dict）。"""
        self.pipe.run(_load_mock_input())
        db = self.pipe.engine.db
        row = db.all("workpapers", limit=1)[0]
        self.assertIsNotNone(row["filled_content"])
        self.assertIsNotNone(row["conclusion"])
        self.assertIsInstance(row["payload"], dict)
        self.assertIn("template_name", row["payload"])

    def test_db_file_created(self) -> None:
        """运行后 fa_07.db 文件实际生成在指定路径。"""
        self.pipe.run(_load_mock_input())
        self.assertTrue(self.db_path.exists())


if __name__ == "__main__":
    unittest.main()
