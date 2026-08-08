"""[FA-10] pipeline 端到端单测：Pipeline.run() 全流程跑通。

使用 unittest 风格，每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fa_10.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    """加载 fixtures 下的 json / jsonl 文件。"""
    p = _FIXTURES / name
    text = p.read_text(encoding="utf-8")
    if name.endswith(".json"):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _make_pipeline(test_case, tmp_path: Path) -> Pipeline:
    """构造隔离 db 的 pipeline，注册组合 cleanup。

    unittest 执行顺序为 tearDown() → doCleanups()，若在 tearDown 直接清理
    临时目录，此时 engine.db 仍占用 .db 文件（Windows 文件锁），导致
    PermissionError [WinError 32]。故把"先关 db 再清目录"打包成单个
    cleanup 函数注册到 addCleanup，并让 tearDown 退化为空操作。
    """
    pipe = Pipeline(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(tmp_path / "fa_10_pipeline.db"),
    })

    def _cleanup() -> None:
        try:
            pipe.engine.close()
        finally:
            try:
                test_case._tmp.cleanup()
            except Exception:
                pass

    test_case.addCleanup(_cleanup)
    return pipe


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_pipeline_end_to_end_with_mock_input(self):
        """用 fixtures/mock_input.json 端到端跑通，输出结构含 networks + summary。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        output = pipe.run(mock_input)

        self.assertEqual(output["status"], "ok")
        self.assertIn("networks", output)
        self.assertIn("summary", output)
        self.assertEqual(len(output["networks"]), 1)

        net = output["networks"][0]
        self.assertEqual(net["target_entity_id"], "E001")
        self.assertIn("related_parties", net)
        self.assertIn("hidden_links", net)
        self.assertIn("cycles", net)
        self.assertIn("statistics", net)

    def test_pipeline_output_summary(self):
        """summary 含 total_targets / total_related / total_hidden / total_cycles / max_hops。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        output = pipe.run(mock_input)

        summary = output["summary"]
        self.assertEqual(summary["total_targets"], 1)
        self.assertGreater(summary["total_related"], 0)
        self.assertGreater(summary["total_hidden"], 0)
        self.assertGreater(summary["total_cycles"], 0)
        self.assertGreater(summary["max_hops"], 0)

    def test_pipeline_related_parties_have_tier(self):
        """关联方经 custom_thresholds 分级后有 tier 字段。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        output = pipe.run(mock_input)

        related = output["networks"][0]["related_parties"]
        tiers = {rp["tier"] for rp in related}
        # 至少有一种分级
        self.assertGreater(len(tiers), 0)
        # tier 值在 strong / medium / weak 中
        valid_tiers = {"strong", "medium", "weak"}
        self.assertTrue(tiers.issubset(valid_tiers))

    def test_pipeline_custom_rules_applied(self):
        """custom_rules 应用后关联方有 rule_tags（循环持股 / 交叉担保 / 共享标记）。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        output = pipe.run(mock_input)

        related = output["networks"][0]["related_parties"]
        all_tags = set()
        for rp in related:
            all_tags.update(rp.get("rule_tags", []))
        # 至少有循环持股标记
        self.assertIn("circular_shareholding", all_tags)
        # 至少有交叉担保标记
        self.assertIn("cross_guarantee", all_tags)
        # 至少有共享类型标记
        self.assertTrue(all_tags & {"shared_address", "shared_phone", "shared_account"})

    def test_pipeline_strong_tier_count(self):
        """strong_count 统计与实际 strong tier 数一致。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        output = pipe.run(mock_input)

        net = output["networks"][0]
        strong_actual = sum(1 for rp in net["related_parties"] if rp.get("tier") == "strong")
        self.assertEqual(net["statistics"]["strong_count"], strong_actual)


class TestPipelinePersistence(unittest.TestCase):
    """PortableDB 持久化。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_pipeline_db_has_all_tables(self):
        """Pipeline 初始化后 PortableDB 含 entities / relations / hidden_links / scan_results 表。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        pipe.run(mock_input)

        with PortableDB(pipe.engine.db_path) as db:
            tables = set(db.tables())
        self.assertIn("entities", tables)
        self.assertIn("relations", tables)
        self.assertIn("hidden_links", tables)
        self.assertIn("scan_results", tables)

    def test_pipeline_persists_scan_results(self):
        """Pipeline 把扫描结果持久化到 scan_results 表。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        pipe.run(mock_input)

        with PortableDB(pipe.engine.db_path) as db:
            rows = db.all("scan_results")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_entity_id"], "E001")
        self.assertGreater(rows[0]["total_related"], 0)

    def test_pipeline_persists_hidden_links(self):
        """Pipeline 把隐藏关联持久化到 hidden_links 表。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        pipe.run(mock_input)

        with PortableDB(pipe.engine.db_path) as db:
            rows = db.all("hidden_links")
        self.assertGreater(len(rows), 0)
        hidden_rows = [r for r in rows if r["is_hidden"] == 1]
        self.assertGreater(len(hidden_rows), 0)

    def test_pipeline_persists_entities(self):
        """Pipeline 把实体持久化到 entities 表。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        pipe.run(mock_input)

        with PortableDB(pipe.engine.db_path) as db:
            rows = db.all("entities")
        self.assertEqual(len(rows), 35)  # 10公司+10人+5地址+5电话+5账户

    def test_pipeline_path_json_deserialized(self):
        """hidden_links 表的 path / relation_types 是 JSON 软类型，自动反序列化为 list。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        pipe.run(mock_input)

        with PortableDB(pipe.engine.db_path) as db:
            rows = db.all("hidden_links")
        for r in rows:
            self.assertIsInstance(r["path"], list)
            self.assertIsInstance(r["relation_types"], list)


class TestPipelineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_pipeline_empty_input(self):
        """空输入返回空网络列表。"""
        pipe = _make_pipeline(self, self.tmp_path)
        output = pipe.run({})
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["networks"], [])

    def test_pipeline_multiple_targets(self):
        """多目标实体：每个目标生成独立网络。"""
        pipe = _make_pipeline(self, self.tmp_path)
        mock_input = _load_fixture("mock_input.json")
        mock_input["target_entity_ids"] = ["E001", "E002"]
        mock_input.pop("target_entity_id", None)
        output = pipe.run(mock_input)

        self.assertEqual(len(output["networks"]), 2)
        target_ids = {n["target_entity_id"] for n in output["networks"]}
        self.assertEqual(target_ids, {"E001", "E002"})
        self.assertEqual(output["summary"]["total_targets"], 2)


if __name__ == "__main__":
    unittest.main()
