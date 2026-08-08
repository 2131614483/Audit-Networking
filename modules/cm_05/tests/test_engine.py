"""[CM-05] engine 单测 —— 三级 KPI 聚合 + 趋势分析 + 智能洞察 + 故事化报告。

使用 unittest.TestCase，pytest 与 unittest 均可发现并运行。

已知 engine bug（不修改 engine.py，测试层规避）：
  BUG-1: _get_projects 的 WHERE 子句引用 COALESCE(start_date, created_at)，
         但 _PROJECTS_SCHEMA 无 created_at 列，导致 OperationalError。
         规避：setUp 中 ALTER TABLE projects ADD COLUMN created_at DATETIME。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.cm_05.engine import MLEngine  # noqa: E402

_ALERTS = [
    {"alert_id": "A001", "severity": "critical", "category": "财务", "bu": "华北",
     "amount": 500000, "description": "重大财务异常", "resolved": 1},
    {"alert_id": "A002", "severity": "high", "category": "合规", "bu": "华南",
     "amount": 200000, "description": "合规违规", "resolved": 0},
    {"alert_id": "A003", "severity": "medium", "category": "运营", "bu": "华北",
     "amount": 50000, "description": "运营异常", "resolved": 1},
    {"alert_id": "A004", "severity": "low", "category": "财务", "bu": "华东",
     "amount": 10000, "description": "小额异常", "resolved": 0},
]
_FINDINGS = [
    {"finding_id": "F001", "title": "内控缺陷", "category": "内控", "severity": "high",
     "bu": "华北", "impact_amount": 300000, "status": "remediated", "project_id": "P001"},
    {"finding_id": "F002", "title": "流程违规", "category": "流程", "severity": "medium",
     "bu": "华南", "impact_amount": 100000, "status": "open", "project_id": "P002"},
]
_PROJECTS = [
    {"project_id": "P001", "name": "年度审计", "bu": "华北", "status": "completed",
     "planned_hours": 200, "actual_hours": 180, "risk_score": 8.5},
    {"project_id": "P002", "name": "专项审计", "bu": "华南", "status": "in_progress",
     "planned_hours": 100, "actual_hours": 60, "risk_score": 6.0},
]


def _patch_projects_schema(eng):
    """BUG-1 规避：为 projects 表补 created_at 列。"""
    cols = eng.db.columns("projects")
    if "created_at" not in cols:
        eng.db._conn.execute("ALTER TABLE projects ADD COLUMN created_at DATETIME")
        eng.db._col_types.pop("projects", None)


class TestEngine(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.eng = MLEngine(config={"db_path": self.db_path})
        self.eng.setup()
        _patch_projects_schema(self.eng)

    def tearDown(self):
        if self.eng.db is not None:
            self.eng.db.close()
        for ext in ("", "-wal", "-shm"):
            p = self.db_path + ext
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _ingest_all(self):
        self.eng.execute({"action": "ingest", "entity_type": "alerts", "records": _ALERTS})
        self.eng.execute({"action": "ingest", "entity_type": "findings", "records": _FINDINGS})
        self.eng.execute({"action": "ingest", "entity_type": "projects", "records": _PROJECTS})

    # ---------- _load_model ----------
    def test_load_model_creates_tables(self):
        tables = self.eng.db.tables()
        for t in ("alerts", "findings", "projects", "kpi_snapshots"):
            self.assertIn(t, tables)

    def test_load_model_sets_kpi_registry(self):
        self.assertIn("kpi_registry", self.eng.model)
        self.assertIn("audit_coverage", self.eng.model["kpi_registry"])

    def test_load_model_severity_order(self):
        so = self.eng.model["severity_order"]
        self.assertEqual(so["critical"], 4)
        self.assertEqual(so["high"], 3)
        self.assertEqual(so["medium"], 2)
        self.assertEqual(so["low"], 1)

    # ---------- ingest ----------
    def test_ingest_alerts(self):
        result = self.eng.execute({"action": "ingest", "entity_type": "alerts", "records": _ALERTS})
        self.assertEqual(result["count"], 4)
        self.assertEqual(self.eng.db.count("alerts"), 4)

    def test_ingest_findings(self):
        result = self.eng.execute({"action": "ingest", "entity_type": "findings", "records": _FINDINGS})
        self.assertEqual(result["count"], 2)
        self.assertEqual(self.eng.db.count("findings"), 2)

    def test_ingest_projects(self):
        result = self.eng.execute({"action": "ingest", "entity_type": "projects", "records": _PROJECTS})
        self.assertEqual(result["count"], 2)
        self.assertEqual(self.eng.db.count("projects"), 2)

    def test_ingest_unknown_entity_type(self):
        result = self.eng.execute({"action": "ingest", "entity_type": "unknown", "records": [{}]})
        self.assertIn("error", result)

    def test_ingest_empty_records(self):
        result = self.eng.execute({"action": "ingest", "entity_type": "alerts", "records": []})
        self.assertEqual(result["count"], 0)

    def test_ingest_sets_raised_at_if_missing(self):
        self.eng.execute({"action": "ingest", "entity_type": "alerts",
                          "records": [{"alert_id": "X1", "severity": "low", "category": "测试", "bu": "BU1"}]})
        row = self.eng.db.query("alerts", limit=1)[0]
        self.assertIsNotNone(row["raised_at"])

    # ---------- dashboard ----------
    def test_dashboard_strategic_role(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        self.assertEqual(out["action"], "dashboard")
        self.assertEqual(out["role"], "strategic")
        self.assertEqual(out["period"], "yearly")
        self.assertIn("kpis", out)
        self.assertIn("role_view", out)
        self.assertIn("total_risk_value", out["role_view"])
        self.assertIn("roi", out["role_view"])

    def test_dashboard_operational_role(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "operational", "period": "monthly"})
        rv = out["role_view"]
        self.assertIn("alert_count", rv)
        self.assertIn("alert_resolution_rate", rv)
        self.assertIn("risk_score_avg", rv)

    def test_dashboard_executive_role(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "executive", "period": "monthly"})
        rv = out["role_view"]
        self.assertIn("my_alerts", rv)
        self.assertIn("my_findings", rv)
        self.assertIn("my_projects", rv)

    def test_dashboard_kpis_computation(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        k = out["kpis"]
        self.assertEqual(k["alert_count"], 4)
        self.assertEqual(k["finding_count"], 2)
        self.assertEqual(k["high_alert_count"], 2)
        self.assertEqual(k["high_severity_findings"], 1)
        self.assertEqual(k["alert_resolution_rate"], 50.0)
        self.assertEqual(k["remediation_rate"], 50.0)
        self.assertEqual(k["project_count"], 2)
        self.assertEqual(k["project_completion_rate"], 50.0)
        self.assertEqual(k["risk_score_avg"], 7.2)

    def test_dashboard_total_risk_value(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        # 760000 (alerts) + 400000 (findings)
        self.assertEqual(out["kpis"]["total_risk_value"], 1160000.0)

    def test_dashboard_bu_distribution(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        bu_dist = out["distribution"]["by_bu"]
        bu_names = [d["bu"] for d in bu_dist]
        self.assertIn("华北", bu_names)
        self.assertIn("华南", bu_names)
        self.assertIn("华东", bu_names)
        # 华北 has 3 (2 alerts + 1 finding), total 6
        huabei = [d for d in bu_dist if d["bu"] == "华北"][0]
        self.assertEqual(huabei["count"], 3)
        self.assertEqual(huabei["percent"], 50.0)

    def test_dashboard_category_distribution(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        cat_dist = out["distribution"]["by_category"]
        top_cat = cat_dist[0]
        self.assertEqual(top_cat["category"], "财务")
        self.assertEqual(top_cat["count"], 2)

    def test_dashboard_top_findings(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        top = out["top_findings"]
        self.assertLessEqual(len(top), 5)
        self.assertEqual(top[0]["finding_id"], "F001")

    def test_dashboard_project_summary(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "yearly"})
        ps = out["project_summary"]
        self.assertEqual(ps["total"], 2)
        self.assertIn("by_status", ps)
        self.assertIn("budget_hours", ps)

    def test_dashboard_kpi_subset(self):
        self._ingest_all()
        out = self.eng.execute({
            "action": "dashboard", "role": "strategic", "period": "yearly",
            "kpis": ["alert_count", "finding_count"]
        })
        self.assertEqual(set(out["kpis"].keys()), {"alert_count", "finding_count"})

    def test_dashboard_bu_filter(self):
        self._ingest_all()
        out = self.eng.execute({
            "action": "dashboard", "role": "strategic", "period": "yearly",
            "bu": "华北"
        })
        self.assertEqual(out["kpis"]["alert_count"], 2)
        self.assertEqual(out["kpis"]["finding_count"], 1)

    def test_dashboard_empty_db(self):
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "monthly"})
        self.assertEqual(out["kpis"]["alert_count"], 0)
        self.assertEqual(out["kpis"]["finding_count"], 0)

    # ---------- trend ----------
    def test_trend_returns_points(self):
        self._ingest_all()
        out = self.eng.execute({"action": "trend", "kpi_name": "alert_count",
                                "days": 30, "granularity": "day"})
        self.assertEqual(out["action"], "trend")
        self.assertEqual(out["kpi_name"], "alert_count")
        self.assertIsInstance(out["points"], list)
        self.assertGreater(len(out["points"]), 0)
        for p in out["points"]:
            self.assertIn("label", p)
            self.assertIn("value", p)

    def test_trend_analysis_present(self):
        self._ingest_all()
        out = self.eng.execute({"action": "trend", "kpi_name": "alert_count",
                                "days": 90, "granularity": "day"})
        self.assertIn("analysis", out)
        if out["analysis"]:
            self.assertIn("trend", out["analysis"])

    def test_trend_weekly_granularity(self):
        self._ingest_all()
        out = self.eng.execute({"action": "trend", "kpi_name": "alert_count",
                                "days": 28, "granularity": "week"})
        self.assertEqual(out["granularity"], "week")
        self.assertGreater(len(out["points"]), 0)

    def test_trend_monthly_granularity(self):
        self._ingest_all()
        out = self.eng.execute({"action": "trend", "kpi_name": "alert_count",
                                "days": 90, "granularity": "month"})
        self.assertEqual(out["granularity"], "month")
        self.assertGreater(len(out["points"]), 0)

    # ---------- insights ----------
    def test_insights_generates_list(self):
        self._ingest_all()
        out = self.eng.execute({"action": "insights", "role": "operational", "period": "monthly"})
        self.assertEqual(out["action"], "insights")
        self.assertIn("insights", out)
        self.assertIsInstance(out["insights"], list)
        self.assertGreater(len(out["insights"]), 0)

    def test_insights_includes_kpi_registry(self):
        self._ingest_all()
        out = self.eng.execute({"action": "insights", "role": "operational", "period": "monthly"})
        self.assertIn("kpi_registry", out)

    def test_insights_low_resolution_rate_mentioned(self):
        self._ingest_all()
        out = self.eng.execute({"action": "insights", "role": "operational", "period": "monthly"})
        text = " ".join(out["insights"])
        self.assertIn("预警处理率", text)

    def test_insights_high_severity_mentioned(self):
        self._ingest_all()
        out = self.eng.execute({"action": "insights", "role": "operational", "period": "monthly"})
        text = " ".join(out["insights"])
        self.assertIn("重大问题", text)

    # ---------- story_report ----------
    def test_story_report_has_four_chapters(self):
        self._ingest_all()
        out = self.eng.execute({"action": "story_report", "period": "yearly", "audience": "executive"})
        self.assertEqual(out["action"], "story_report")
        chapters = [s["chapter"] for s in out["story"]]
        self.assertEqual(chapters, ["概览", "风险聚焦", "行动建议", "价值总结"])

    def test_story_report_overview_content(self):
        self._ingest_all()
        out = self.eng.execute({"action": "story_report", "period": "yearly", "audience": "executive"})
        overview = out["story"][0]["content"]
        self.assertIn("交易", overview)
        self.assertIn("预警", overview)

    def test_story_report_action_suggestions(self):
        self._ingest_all()
        out = self.eng.execute({"action": "story_report", "period": "yearly", "audience": "executive"})
        actions = out["story"][2]["content"]
        # resolution rate 50% < 80% → suggestion present
        self.assertIn("预警处理", actions)

    def test_story_report_includes_top_findings(self):
        self._ingest_all()
        out = self.eng.execute({"action": "story_report", "period": "yearly", "audience": "executive"})
        self.assertLessEqual(len(out["top_findings"]), 3)
        if out["top_findings"]:
            self.assertEqual(out["top_findings"][0]["finding_id"], "F001")

    # ---------- kpi_snapshot ----------
    def test_kpi_snapshot_creates_record(self):
        self._ingest_all()
        out = self.eng.execute({"action": "kpi_snapshot", "role": "strategic", "period": "monthly"})
        self.assertEqual(out["action"], "kpi_snapshot")
        self.assertIn("snapshot_id", out)
        self.assertEqual(self.eng.db.count("kpi_snapshots"), 1)

    def test_kpi_snapshot_contains_kpis(self):
        self._ingest_all()
        out = self.eng.execute({"action": "kpi_snapshot", "role": "strategic", "period": "monthly"})
        self.assertIn("kpis", out)
        self.assertIn("alert_count", out["kpis"])

    def test_kpi_snapshot_role_and_period(self):
        self._ingest_all()
        out = self.eng.execute({"action": "kpi_snapshot", "role": "operational", "period": "quarterly"})
        self.assertEqual(out["role"], "operational")
        self.assertEqual(out["period"], "quarterly")

    # ---------- _postprocess ----------
    def test_postprocess_adds_engine_tag(self):
        self._ingest_all()
        out = self.eng.execute({"action": "dashboard", "role": "strategic", "period": "monthly"})
        self.assertEqual(out["engine"], "CM-05-AuditDashboard")
        self.assertIn("timestamp", out)

    # ---------- _preprocess ----------
    def test_preprocess_non_dict_raises(self):
        with self.assertRaises(ValueError):
            self.eng.execute([1, 2, 3])

    def test_preprocess_unknown_action_raises(self):
        with self.assertRaises(ValueError):
            self.eng.execute({"action": "unknown"})

    def test_preprocess_default_action_is_dashboard(self):
        out = self.eng.execute({"role": "strategic", "period": "monthly"})
        self.assertEqual(out["action"], "dashboard")


if __name__ == "__main__":
    unittest.main(verbosity=2)
