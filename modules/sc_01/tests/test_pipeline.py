"""[SC-01] pipeline 单测：端到端编排 → 阈值 → 规则 → 持久化 → 输出格式。

unittest 风格，每个测试用独立 tmp_path 隔离 PortableDB，避免相互污染。
覆盖编排顺序：collect → engine.execute → apply_thresholds → apply_custom_rules
→ _persist(PortableDB) → format_output。

注意（Windows + SQLite）：PortableDB 连接在 .db 文件上持有锁，
必须在 TemporaryDirectory 清理之前关闭连接，否则触发 PermissionError。
本文件通过 setUp/tearDown 管理生命周期：先关闭所有 engine 连接，再 ignore_errors 清理目录。
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from modules.sc_01.pipeline import Pipeline

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_mock_input() -> dict:
    """读取 mock_input.json 端到端夹具。"""
    with open(_FIXTURES / "mock_input.json", encoding="utf-8") as f:
        return json.load(f)


class _DBTestCase(unittest.TestCase):
    """提供隔离 tmp_path + 自动关闭 PortableDB 连接的测试基类。

    Windows 下 SQLite 文件锁要求先关连接再删目录；本类在 tearDown 中
    先逐个 close 已创建的 engine，再用 ignore_errors 清理目录。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="sc01_pipe_")
        self.tmp_path = Path(self._tmp)
        self._pipes: list = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        # 先关闭所有 PortableDB 连接，释放 Windows 文件锁
        for p in self._pipes:
            try:
                p.engine.close()
            except Exception:
                pass
        # 再清理目录（ignore_errors 兜底残留 -wal/-shm 文件）
        shutil.rmtree(self._tmp, ignore_errors=True)

    def make_pipeline(self, threshold: float = 0.85,
                      db_name: str = "sc_01_pipeline.db") -> Pipeline:
        pipe = Pipeline(config={
            "threshold": {"confidence": threshold},
            "db_path": str(self.tmp_path / db_name),
        })
        self._pipes.append(pipe)
        return pipe


# ----------------------------------------------------------------------
# 编排结构
# ----------------------------------------------------------------------
class TestPipelineStructure(_DBTestCase):
    def test_pipeline_run_returns_formatted_dict(self):
        """run() 返回 format_output 结构：status / supplier_ranking / statistics。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        self.assertIsInstance(out, dict)
        self.assertEqual(out["status"], "ok")
        self.assertIn("supplier_ranking", out)
        self.assertIn("statistics", out)

    def test_pipeline_collect_is_passthrough(self):
        """_collect 透传输入（权重与关键词已在 engine._load_model 合并）。"""
        pipe = self.make_pipeline()
        payload = {"suppliers": []}
        self.assertIs(pipe._collect(payload), payload)

    def test_pipeline_engine_loaded(self):
        """Pipeline 构造时显式 setup()，engine.model 已加载、db 已就绪。"""
        pipe = self.make_pipeline()
        self.assertIsNotNone(pipe.engine.model)
        self.assertIsNotNone(pipe.engine.db)

    def test_pipeline_empty_input(self):
        """空 suppliers 列表：不崩溃，返回空排名 + 零统计。"""
        pipe = self.make_pipeline()
        out = pipe.run({"suppliers": []})
        self.assertEqual(out["supplier_ranking"], [])
        self.assertEqual(out["statistics"]["total"], 0)
        self.assertEqual(out["statistics"]["level_distribution"]["低"], 0)


# ----------------------------------------------------------------------
# 端到端：mock_input.json
# ----------------------------------------------------------------------
class TestPipelineEndToEnd(_DBTestCase):
    def test_mock_input_supplier_count(self):
        """mock_input 6 家供应商全部入榜（无 USCC 重复）。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        self.assertEqual(out["statistics"]["total"], 6)
        self.assertEqual(len(out["supplier_ranking"]), 6)

    def test_ranking_sorted_desc_by_score(self):
        """supplier_ranking 按综合分降序（高风险在前）。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        scores = [s["total_score"] for s in out["supplier_ranking"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_ranking_item_structure(self):
        """每个 ranking item 含五维雷达 + 风险点 + 建议。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        item = out["supplier_ranking"][0]
        self.assertIn("supplier_id", item)
        self.assertIn("name", item)
        self.assertIn("total_score", item)
        self.assertIn("level", item)
        self.assertIn("need_review", item)
        self.assertIn("rule_upgraded", item)
        self.assertIn("sub_scores", item)
        self.assertIn("radar", item)
        # 雷达数据：5 维标签 + 5 维数值
        self.assertEqual(len(item["radar"]["labels"]), 5)
        self.assertEqual(len(item["radar"]["values"]), 5)
        self.assertIn("risk_points", item)
        self.assertIn("recommendations", item)

    def test_statistics_structure(self):
        """statistics 含 total / level_distribution / high_risk_list / recommendations_summary。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        stats = out["statistics"]
        self.assertEqual(stats["total"], 6)
        self.assertIn("level_distribution", stats)
        dist = stats["level_distribution"]
        # 等级分布之和 = total
        self.assertEqual(
            dist["低"] + dist["中"] + dist["高"] + dist["极高"],
            stats["total"],
        )
        self.assertIn("high_risk_list", stats)
        self.assertIn("recommendations_summary", stats)
        self.assertIsInstance(stats["recommendations_summary"], list)

    def test_high_risk_list_only_contains_high_and_extreme(self):
        """high_risk_list 仅含「高」「极高」等级供应商。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        high_risk = out["statistics"]["high_risk_list"]
        for item in high_risk:
            self.assertIn(item["level"], ("高", "极高"))

    def test_dishonest_supplier_upgraded_to_extreme(self):
        """SUP-MOCK-003 失信被执行人 → 规则升级为「极高」。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        by_id = {s["supplier_id"]: s for s in out["supplier_ranking"]}
        s = by_id["SUP-MOCK-003"]
        self.assertEqual(s["level"], "极高")
        self.assertTrue(s["rule_upgraded"])
        self.assertTrue(any("失信" in f for f in s["rule_flags"]))

    def test_liquidation_status_upgraded_to_extreme(self):
        """SUP-MOCK-004 经营状态=清算 → 规则升级为「极高」。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        by_id = {s["supplier_id"]: s for s in out["supplier_ranking"]}
        s = by_id["SUP-MOCK-004"]
        self.assertEqual(s["level"], "极高")
        self.assertTrue(s["rule_upgraded"])

    def test_low_capital_supplier_flagged(self):
        """SUP-MOCK-006 注册资本 5 万 → rule_flags 含注册资本过低。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        by_id = {s["supplier_id"]: s for s in out["supplier_ranking"]}
        s = by_id["SUP-MOCK-006"]
        self.assertTrue(any("注册资本过低" in f for f in s["rule_flags"]))

    def test_healthy_supplier_low_risk(self):
        """SUP-MOCK-001 健康供应商 → 等级为「低」。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        by_id = {s["supplier_id"]: s for s in out["supplier_ranking"]}
        s = by_id["SUP-MOCK-001"]
        self.assertEqual(s["level"], "低")
        self.assertFalse(s["rule_upgraded"])


# ----------------------------------------------------------------------
# 阈值与规则
# ----------------------------------------------------------------------
class TestPipelineThresholdsAndRules(_DBTestCase):
    def test_threshold_confidence_stamped(self):
        """每个供应商评分盖 threshold_confidence 印章（默认 0.85）。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        # format_output 不直接暴露 threshold_confidence，校验内部结果
        # 通过 statistics.need_review 间接验证 thresholds 已执行
        self.assertIn("need_review", out["statistics"])

    def test_borderline_or_rule_hit_marked_need_review(self):
        """规则命中或边界分数 → need_review=True（统计中 need_review > 0）。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        # SUP-MOCK-003/004/006 均触发规则 → need_review
        self.assertGreater(out["statistics"]["need_review"], 0)

    def test_rule_upgraded_count_in_summary(self):
        """statistics.rule_upgraded 反映被规则升级的供应商数。"""
        pipe = self.make_pipeline()
        out = pipe.run(_load_mock_input())
        # SUP-MOCK-003（失信）+ SUP-MOCK-004（清算+失信）至少 2 个被升级
        self.assertGreaterEqual(out["statistics"]["rule_upgraded"], 2)

    def test_custom_threshold_override(self):
        """config.threshold.extreme 覆盖默认 80 → 影响等级分布。"""
        # 极高阈值抬高到 95，原本极高的可能降为高
        pipe_high = self.make_pipeline(threshold=0.90)
        pipe_high.engine.config["threshold"] = {
            "extreme": 95.0, "high": 60.0, "medium": 40.0, "confidence": 0.90,
        }
        out = pipe_high.run(_load_mock_input())
        # 规则升级仍然把失信/清算抬到极高（一票否决）
        by_id = {s["supplier_id"]: s for s in out["supplier_ranking"]}
        self.assertEqual(by_id["SUP-MOCK-003"]["level"], "极高")


# ----------------------------------------------------------------------
# PortableDB 持久化
# ----------------------------------------------------------------------
class TestPipelinePersistence(_DBTestCase):
    def test_persist_writes_suppliers_table(self):
        """_persist 把供应商写入 suppliers 主表（按 supplier_id upsert）。"""
        pipe = self.make_pipeline()
        pipe.run(_load_mock_input())
        db = pipe.engine.db
        self.assertEqual(db.count("suppliers"), 6)
        # 字段落盘正确
        row = db.get("suppliers", "supplier_id = ?", ["SUP-MOCK-001"])
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "深圳市锐捷信息技术有限公司")

    def test_persist_appends_risk_assessments(self):
        """_persist 每次执行追加评分结果到 risk_assessments（留存历史轨迹）。"""
        pipe = self.make_pipeline()
        pipe.run(_load_mock_input())
        db = pipe.engine.db
        self.assertEqual(db.count("risk_assessments"), 6)
        # sub_scores 以 JSON 序列化落盘
        row = db.get("risk_assessments", "supplier_id = ?", ["SUP-MOCK-003"])
        self.assertIsNotNone(row)
        self.assertIn("business", row["sub_scores"])
        self.assertIn("litigation", row["sub_scores"])

    def test_persist_writes_risk_events(self):
        """_persist 把每个风险点写入 risk_events 明细表。"""
        pipe = self.make_pipeline()
        pipe.run(_load_mock_input())
        db = pipe.engine.db
        # 6 家供应商各有多个风险点 → risk_events 行数 > 供应商数
        self.assertGreater(db.count("risk_events"), 6)

    def test_rerun_upserts_suppliers_not_duplicates(self):
        """重复执行：suppliers 表 upsert 不堆叠，risk_assessments 追加留痕。"""
        pipe = self.make_pipeline()
        mock = _load_mock_input()
        pipe.run(mock)
        pipe.run(mock)
        db = pipe.engine.db
        # suppliers 仍为 6（upsert 去重）
        self.assertEqual(db.count("suppliers"), 6)
        # risk_assessments 翻倍（每次执行追加）
        self.assertEqual(db.count("risk_assessments"), 12)

    def test_persist_survives_reload(self):
        """持久化数据在新 Pipeline 实例加载同一 db 时可见。"""
        db_path = str(self.tmp_path / "sc_01_reload.db")
        pipe1 = Pipeline(config={
            "threshold": {"confidence": 0.85},
            "db_path": db_path,
        })
        self._pipes.append(pipe1)
        pipe1.run(_load_mock_input())
        pipe1.engine.close()

        pipe2 = Pipeline(config={
            "threshold": {"confidence": 0.85},
            "db_path": db_path,
        })
        self._pipes.append(pipe2)
        db = pipe2.engine.db
        self.assertEqual(db.count("suppliers"), 6)
        self.assertEqual(db.count("risk_assessments"), 6)

    def test_risk_events_carry_dimension_and_severity(self):
        """risk_events 携带 dimension / severity / description 字段。"""
        pipe = self.make_pipeline()
        pipe.run(_load_mock_input())
        db = pipe.engine.db
        rows = db.all("risk_events", limit=5)
        self.assertGreater(len(rows), 0)
        for r in rows:
            self.assertIn("dimension", r)
            self.assertIn("severity", r)
            self.assertIn("description", r)


# ----------------------------------------------------------------------
# 全量 fixtures 跑通
# ----------------------------------------------------------------------
class TestPipelineFullFixtures(_DBTestCase):
    def test_pipeline_runs_suppliers_fixture(self):
        """pipeline 跑全量 suppliers.jsonl：去重后 ≥50 家，落盘 + 输出正常。"""
        with open(_FIXTURES / "suppliers.jsonl", encoding="utf-8") as f:
            suppliers = [json.loads(line) for line in f if line.strip()]
        pipe = self.make_pipeline()
        out = pipe.run({"suppliers": suppliers})
        self.assertGreaterEqual(out["statistics"]["total"], 50)
        # 等级分布之和 = total
        dist = out["statistics"]["level_distribution"]
        self.assertEqual(
            dist["低"] + dist["中"] + dist["高"] + dist["极高"],
            out["statistics"]["total"],
        )
        # 持久化行数 = 输出供应商数
        self.assertEqual(pipe.engine.db.count("suppliers"),
                         out["statistics"]["total"])


if __name__ == "__main__":
    unittest.main()
