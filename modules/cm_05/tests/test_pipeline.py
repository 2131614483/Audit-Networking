"""[CM-05] pipeline 单测 —— 端到端编排 collect→execute→thresholds→rules→output。

使用 unittest.TestCase，pytest 与 unittest 均可发现并运行。

已知 pipeline bug（不修改 pipeline.py，测试层规避）：
  BUG-2: Pipeline.run() 未调用 engine.setup()，导致 model/db 为 None。
         规避：测试中手动调用 pipe.engine.setup()。
  BUG-1: engine._get_projects 引用不存在的 created_at 列（见 test_engine.py）。
         规避：setup 后 ALTER TABLE projects ADD COLUMN created_at DATETIME。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.cm_05.pipeline import Pipeline  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_input.json"

_ALERTS = [
    {"alert_id": "A001", "severity": "critical", "category": "财务", "bu": "华北",
     "amount": 500000, "description": "重大财务异常", "resolved": 1},
    {"alert_id": "A002", "severity": "high", "category": "合规", "bu": "华南",
     "amount": 200000, "description": "合规违规", "resolved": 0},
]
_FINDINGS = [
    {"finding_id": "F001", "title": "内控缺陷", "category": "内控", "severity": "high",
     "bu": "华北", "impact_amount": 300000, "status": "remediated", "project_id": "P001"},
]
_PROJECTS = [
    {"project_id": "P001", "name": "年度审计", "bu": "华北", "status": "completed",
     "planned_hours": 200, "actual_hours": 180, "risk_score": 8.5},
]


def _load_sample():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _patch_projects_schema(eng):
    cols = eng.db.columns("projects")
    if "created_at" not in cols:
        eng.db._conn.execute("ALTER TABLE projects ADD COLUMN created_at DATETIME")
        eng.db._col_types.pop("projects", None)


class TestPipeline(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.pipe = Pipeline(config={"db_path": self.db_path})
        # BUG-2 规避：pipeline 未调 setup，手动触发
        self.pipe.engine.setup()
        # BUG-1 规避：补 projects.created_at 列
        _patch_projects_schema(self.pipe.engine)

    def tearDown(self):
        if self.pipe.engine.db is not None:
            self.pipe.engine.db.close()
        for ext in ("", "-wal", "-shm"):
            p = self.db_path + ext
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _ingest_all(self):
        self.pipe.run({"action": "ingest", "entity_type": "alerts", "records": _ALERTS})
        self.pipe.run({"action": "ingest", "entity_type": "findings", "records": _FINDINGS})
        self.pipe.run({"action": "ingest", "entity_type": "projects", "records": _PROJECTS})

    def test_pipeline_ingest_alerts(self):
        out = self.pipe.run({"action": "ingest", "entity_type": "alerts", "records": _ALERTS})
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["action"], "ingest")
        self.assertEqual(self.pipe.engine.db.count("alerts"), 2)

    def test_pipeline_dashboard_end_to_end(self):
        self._ingest_all()
        out = self.pipe.run({"action": "dashboard", "role": "strategic", "period": "yearly"})
        self.assertEqual(out["action"], "dashboard")
        self.assertEqual(out["role"], "strategic")
        self.assertEqual(out["kpis"]["alert_count"], 2)
        self.assertEqual(out["kpis"]["finding_count"], 1)
        self.assertEqual(out["kpis"]["project_count"], 1)

    def test_pipeline_dashboard_with_sample_fixture(self):
        """使用 sample_input.json 端到端跑通 dashboard。"""
        self._ingest_all()
        sample = _load_sample()
        out = self.pipe.run(sample)
        self.assertEqual(out["action"], "dashboard")
        self.assertEqual(out["role"], "strategic")
        self.assertEqual(out["period"], "yearly")
        self.assertIn("kpis", out)
        self.assertIn("role_view", out)

    def test_pipeline_story_report(self):
        self._ingest_all()
        out = self.pipe.run({"action": "story_report", "period": "yearly", "audience": "executive"})
        chapters = [s["chapter"] for s in out["story"]]
        self.assertEqual(chapters, ["概览", "风险聚焦", "行动建议", "价值总结"])

    def test_pipeline_insights(self):
        self._ingest_all()
        out = self.pipe.run({"action": "insights", "role": "operational", "period": "monthly"})
        self.assertEqual(out["action"], "insights")
        self.assertIsInstance(out["insights"], list)

    def test_pipeline_kpi_snapshot(self):
        self._ingest_all()
        out = self.pipe.run({"action": "kpi_snapshot", "role": "strategic", "period": "monthly"})
        self.assertIn("snapshot_id", out)
        self.assertEqual(self.pipe.engine.db.count("kpi_snapshots"), 1)

    def test_pipeline_postprocess_adds_engine_tag(self):
        self._ingest_all()
        out = self.pipe.run({"action": "dashboard", "role": "strategic", "period": "monthly"})
        self.assertEqual(out["engine"], "CM-05-AuditDashboard")
        self.assertIn("timestamp", out)

    def test_pipeline_custom_stages_pass_through(self):
        """custom_thresholds / custom_rules / format_output 均为 pass-through。"""
        self._ingest_all()
        out = self.pipe.run({"action": "dashboard", "role": "strategic", "period": "yearly"})
        # pass-through 不改变 result 结构
        self.assertIn("kpis", out)
        self.assertIn("distribution", out)
        self.assertIn("top_findings", out)

    def test_pipeline_trend(self):
        self._ingest_all()
        out = self.pipe.run({"action": "trend", "kpi_name": "alert_count",
                             "days": 30, "granularity": "day"})
        self.assertEqual(out["action"], "trend")
        self.assertGreater(len(out["points"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
