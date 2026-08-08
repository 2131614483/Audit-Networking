"""[IP-01] pipeline 单测 —— unittest 风格，端到端 + PortableDB 持久化。

覆盖：
  * Pipeline.run() 端到端（collect → execute → thresholds → rules → output）
  * 输出结构（dashboard / task_list / findings / cycle_statistics）
  * PortableDB 四张运行时表持久化（ipo_tasks / checkpoints / findings / acceleration_logs）
  * 自定义阈值分级（passed / partial / needs_optimization）
  * 自定义业务规则（财务异常复核 / 关联交易重点核查 / 内控缺陷升级）
"""
import json
import tempfile
import unittest
from pathlib import Path

from modules.ip_01.pipeline import Pipeline

_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "fixtures"


def _load_mock_input():
    with open(_FIXTURES_DIR / "mock_input.json", encoding="utf-8") as f:
        return json.load(f)


# ==================================================================
# 1. 端到端 pipeline.run() 校验
# ==================================================================
class PipelineEndToEndTests(unittest.TestCase):
    """端到端 pipeline.run()：从 mock_input 到格式化输出。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pipe = Pipeline(config={
            "db_path": str(Path(self.tmpdir.name) / "test_pipeline.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
            "threshold": {"confidence": 0.85, "bottleneck": 0.5},
        })
        self.mock = _load_mock_input()

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_run_returns_ok_status(self):
        out = self.pipe.run(self.mock)
        self.assertEqual(out["status"], "ok")

    def test_run_dashboard_structure(self):
        """看板含 project_id / enterprise_name / overview / by_category / tech_stack。"""
        out = self.pipe.run(self.mock)
        dash = out["dashboard"]
        self.assertEqual(dash["project_id"], "IPO-2026-001")
        self.assertEqual(dash["enterprise_name"], "智造未来科技股份有限公司")
        self.assertIn("overview", dash)
        self.assertIn("by_category", dash)
        self.assertIn("tech_stack", dash)

    def test_run_task_list_nonempty(self):
        """任务清单非空，每项含 task_id / category / status / acceleration_ratio / tier。"""
        out = self.pipe.run(self.mock)
        self.assertGreater(len(out["task_list"]), 0)
        for t in out["task_list"]:
            self.assertIn("task_id", t)
            self.assertIn("category", t)
            self.assertIn("status", t)
            self.assertIn("acceleration_ratio", t)
            self.assertIn("acceleration_tier", t)

    def test_run_findings_nonempty(self):
        """核查发现非空，含四栈来源。"""
        out = self.pipe.run(self.mock)
        self.assertGreater(len(out["findings"]), 0)
        sources = {f["source"] for f in out["findings"]}
        # 至少含 ml 与 kg 来源（mock_input 必然触发）
        self.assertIn("ml", sources)
        self.assertIn("kg", sources)

    def test_run_cycle_statistics(self):
        """周期统计含总任务/加速比例/缩短比例/天数。"""
        out = self.pipe.run(self.mock)
        cs = out["cycle_statistics"]
        self.assertGreater(cs["total_tasks"], 0)
        self.assertGreater(cs["overall_acceleration_ratio"], 0)
        self.assertGreater(cs["estimated_cycle_reduction_pct"], 0)
        self.assertGreater(cs["cycle_before_days"], cs["cycle_after_days"])
        self.assertGreater(cs["total_saved_hours"], 0)

    def test_run_tech_stack_coverage(self):
        """四技术栈均有贡献：RPA/ML/LLM/KG。"""
        out = self.pipe.run(self.mock)
        ts = out["dashboard"]["tech_stack"]
        self.assertGreater(ts["rpa"]["automated_count"], 0)
        self.assertGreater(ts["ml"]["anomaly_count"], 0)
        self.assertGreater(ts["llm"]["doc_count"], 0)
        self.assertGreater(ts["kg"]["related_transactions"], 0)

    def test_run_overview_metrics(self):
        """看板 overview 含总任务/已完成/加速比例/发现数/瓶颈数/缩短比例。"""
        out = self.pipe.run(self.mock)
        ov = out["dashboard"]["overview"]
        self.assertIn("total_tasks", ov)
        self.assertIn("completed_tasks", ov)
        self.assertIn("auto_done_tasks", ov)
        self.assertIn("overall_acceleration_ratio", ov)
        self.assertIn("findings_count", ov)
        self.assertIn("bottleneck_count", ov)
        self.assertIn("estimated_cycle_reduction_pct", ov)

    def test_run_by_category_has_four_categories(self):
        """by_category 含四类：financial/legal/business/internal_control。"""
        out = self.pipe.run(self.mock)
        cats = out["dashboard"]["by_category"]
        for cat in ("financial", "legal", "business", "internal_control"):
            self.assertIn(cat, cats)
            self.assertIn("total", cats[cat])
            self.assertIn("saved_hours", cats[cat])

    def test_run_task_list_has_acceleration_tier(self):
        """任务清单含 acceleration_tier 字段（thresholds 已应用）。"""
        out = self.pipe.run(self.mock)
        tiers = {t["acceleration_tier"] for t in out["task_list"]}
        # 应含 passed（≥0.85）与 needs_optimization（<0.5）
        self.assertIn("passed", tiers)
        self.assertIn("needs_optimization", tiers)


# ==================================================================
# 2. PortableDB 四张运行时表持久化
# ==================================================================
class PipelinePersistenceTests(unittest.TestCase):
    """PortableDB 四张运行时表持久化校验。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_persist.db"
        self.pipe = Pipeline(config={
            "db_path": str(self.db_path),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        self.mock = _load_mock_input()
        self.pipe.run(self.mock)

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_ipo_tasks_persisted(self):
        """ipo_tasks 表非空，每行含 task_id/status/acceleration_ratio。"""
        db = self.pipe.engine.db
        rows = db.all("ipo_tasks")
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertIn("task_id", r)
            self.assertIn("status", r)
            self.assertIn("acceleration_ratio", r)

    def test_ipo_tasks_count_matches_templates(self):
        """ipo_tasks 行数 = 审计任务模板数（20 个）。"""
        db = self.pipe.engine.db
        count = db.count("ipo_tasks")
        templates = self.pipe.engine.model["audit_task_templates"]
        self.assertEqual(count, len(templates))

    def test_checkpoints_persisted(self):
        """checkpoints 表非空，含 financial 类核查点。"""
        db = self.pipe.engine.db
        rows = db.all("checkpoints")
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertIn("checkpoint_id", r)
            self.assertIn("rule_id", r)
            self.assertIn("status", r)
            self.assertIn(r["status"], ("passed", "flagged"))

    def test_findings_persisted(self):
        """findings 表非空，含 ml/kg 来源。"""
        db = self.pipe.engine.db
        rows = db.all("findings")
        self.assertGreater(len(rows), 0)
        sources = {r["source"] for r in rows}
        self.assertIn("ml", sources)

    def test_acceleration_logs_persisted(self):
        """acceleration_logs 表非空，含阶段日志与每任务日志。"""
        db = self.pipe.engine.db
        rows = db.all("acceleration_logs")
        self.assertGreater(len(rows), 0)
        phases = {r["phase"] for r in rows}
        # 阶段日志（rpa/ml/llm/kg）+ 每任务日志（acceleration）
        self.assertIn("acceleration", phases)
        self.assertIn("rpa", phases)

    def test_acceleration_logs_count_matches_tasks(self):
        """acceleration_logs 中 phase=acceleration 的行数 = 任务数。"""
        db = self.pipe.engine.db
        accel_count = db.count("acceleration_logs", where="phase = :p",
                                params={"p": "acceleration"})
        templates = self.pipe.engine.model["audit_task_templates"]
        self.assertEqual(accel_count, len(templates))

    def test_persisted_task_has_payload_json(self):
        """ipo_tasks.payload 列为 JSON（含 project_id）。"""
        db = self.pipe.engine.db
        rows = db.all("ipo_tasks")
        for r in rows:
            payload = r.get("payload")
            self.assertIsNotNone(payload)
            self.assertIsInstance(payload, dict)
            self.assertIn("project_id", payload)


# ==================================================================
# 3. 自定义阈值与业务规则
# ==================================================================
class PipelineCustomRulesTests(unittest.TestCase):
    """自定义阈值分级 + 业务规则应用。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_rules.db"
        self.pipe = Pipeline(config={
            "db_path": str(self.db_path),
            "fixtures_dir": str(_FIXTURES_DIR),
            "threshold": {
                "confidence": 0.85,
                "bottleneck": 0.5,
                "related_tx_amount": 5_000_000,
            },
        })
        self.mock = _load_mock_input()

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_acceleration_tier_passed(self):
        """加速比例 ≥ 0.85 → passed。"""
        out = self.pipe.run(self.mock)
        passed_tasks = [t for t in out["task_list"]
                        if t["acceleration_tier"] == "passed"]
        self.assertGreater(len(passed_tasks), 0)
        for t in passed_tasks:
            self.assertGreaterEqual(t["acceleration_ratio"], 0.85)

    def test_acceleration_tier_needs_optimization(self):
        """加速比例 < 0.5 → needs_optimization。"""
        out = self.pipe.run(self.mock)
        needs_opt = [t for t in out["task_list"]
                     if t["acceleration_tier"] == "needs_optimization"]
        self.assertGreater(len(needs_opt), 0)
        for t in needs_opt:
            self.assertLess(t["acceleration_ratio"], 0.5)

    def test_high_severity_findings_need_manual_review(self):
        """high 严重程度的发现强制人工复核（custom_thresholds 规则）。"""
        out = self.pipe.run(self.mock)
        for f in out["findings"]:
            if f["severity"] == "high":
                self.assertTrue(f["need_manual_review"])

    def test_related_transaction_key_check(self):
        """关联交易超阈值 → key_check=True（custom_rules 规则 2）。"""
        out = self.pipe.run(self.mock)
        key_checks = [f for f in out["findings"] if f.get("key_check")]
        self.assertGreater(len(key_checks), 0)

    def test_ml_findings_force_manual_review(self):
        """ML 财务异常发现强制人工复核（custom_rules 规则 1）。"""
        out = self.pipe.run(self.mock)
        ml_findings = [f for f in out["findings"] if f["source"] == "ml"]
        for f in ml_findings:
            self.assertTrue(f["need_manual_review"])

    def test_pipeline_idempotent_run(self):
        """Pipeline 可重复运行（每次 run 独立执行）。"""
        out1 = self.pipe.run(self.mock)
        out2 = self.pipe.run(self.mock)
        self.assertEqual(out1["status"], "ok")
        self.assertEqual(out2["status"], "ok")
        self.assertEqual(
            out1["cycle_statistics"]["total_tasks"],
            out2["cycle_statistics"]["total_tasks"])


# ==================================================================
# 4. 边界与容错
# ==================================================================
class PipelineEdgeCaseTests(unittest.TestCase):
    """边界与容错：空输入 / 缺失字段。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.pipe = Pipeline(config={
            "db_path": str(Path(self.tmpdir.name) / "test_edge.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })

    def tearDown(self):
        self.pipe.engine.close()
        self.tmpdir.cleanup()

    def test_run_with_minimal_input(self):
        """最小输入（仅 enterprise）也能跑通，不报错。"""
        minimal = {
            "project_id": "IPO-MIN-001",
            "enterprise": {"name": "测试公司"},
        }
        out = self.pipe.run(minimal)
        self.assertEqual(out["status"], "ok")
        self.assertGreater(len(out["task_list"]), 0)

    def test_run_with_empty_financial_data(self):
        """空财务数据也能跑通（ML 核查返回零值）。"""
        minimal = {
            "project_id": "IPO-EMPTY-001",
            "enterprise": {"name": "空财务公司"},
            "financial_data": {},
        }
        out = self.pipe.run(minimal)
        self.assertEqual(out["status"], "ok")
        ts = out["dashboard"]["tech_stack"]
        self.assertEqual(ts["ml"]["anomaly_count"], 0)

    def test_run_with_empty_documents(self):
        """空文档列表也能跑通（LLM 处理返回 0 摘要）。"""
        minimal = {
            "project_id": "IPO-NODOC-001",
            "enterprise": {"name": "无文档公司"},
            "documents": [],
            "legal_documents": [],
        }
        out = self.pipe.run(minimal)
        self.assertEqual(out["status"], "ok")
        ts = out["dashboard"]["tech_stack"]
        self.assertEqual(ts["llm"]["doc_count"], 0)


if __name__ == "__main__":
    unittest.main()
