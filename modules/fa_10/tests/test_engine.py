"""[FA-10] engine 单测：图构建 / BFS 多跳 / 关联强度 / 环路检测 / 隐藏关联发现。

使用 unittest 风格，每个测试用独立 tmp 目录隔离 PortableDB。
addCleanup 确保断言失败时也能关闭 DB 连接（Windows 文件锁）。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fa_10.engine import MLEngine

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str):
    """加载 fixtures 下的 json / jsonl 文件。"""
    p = _FIXTURES / name
    text = p.read_text(encoding="utf-8")
    if name.endswith(".json"):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _make_engine(test_case, tmp_path: Path, threshold: float = 0.85) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型，注册组合 cleanup。

    unittest 执行顺序为 tearDown() → doCleanups()，若在 tearDown 直接清理
    临时目录，此时 engine.db 仍占用 .db 文件（Windows 文件锁），导致
    PermissionError [WinError 32]。故把"先关 db 再清目录"打包成单个
    cleanup 函数注册到 addCleanup，并让 tearDown 退化为空操作。
    """
    eng = MLEngine(config={
        "threshold": {"confidence": threshold},
        "db_path": str(tmp_path / "fa_10_engine.db"),
    })
    eng.setup()

    def _cleanup() -> None:
        try:
            eng.close()
        finally:
            try:
                test_case._tmp.cleanup()
            except Exception:
                pass

    test_case.addCleanup(_cleanup)
    return eng


def _make_mock_input() -> dict:
    """构造包含完整 fixtures 数据的输入。"""
    return {
        "target_entity_id": "E001",
        "max_hops": 5,
        "entities": _load_fixture("entities.jsonl"),
        "relations": _load_fixture("relations.jsonl"),
    }


class TestGraphConstruction(unittest.TestCase):
    """图构建：邻接表 + 派生共享关系。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_graph_built_from_entities_and_relations(self):
        """图构建后邻接表含所有实体与关系。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        graph = eng.model["graph"]
        self.assertIn("E001", graph)
        neighbors = graph["E001"]
        self.assertIn("P001", neighbors)   # legal_rep
        self.assertIn("ADDR1", neighbors)  # address
        self.assertIn("E002", neighbors)   # address_share / account_share (derived)
        self.assertIn("E004", neighbors)   # shareholder (E004→E001, bidirectional)

    def test_derived_share_relations(self):
        """派生共享关系：同一地址/电话/账户连接多家公司 → 直接边。

        E001↔E002 共享地址 ADDR1 + 账户 ACC1 → account_share(0.7) 胜出
        E001↔E003 共享电话 PH1 → phone_share(0.4)
        E007↔E008 共享地址 ADDR4 → address_share(0.5)
        """
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        graph = eng.model["graph"]
        # E001 与 E002 共享地址+账户 → account_share 权重 0.7 > address_share 0.5
        self.assertEqual(graph["E001"].get("E002"), "account_share")
        # E001 与 E003 共享电话 PH1 → phone_share
        self.assertEqual(graph["E001"].get("E003"), "phone_share")
        # E007 与 E008 共享地址 ADDR4 → address_share
        self.assertEqual(graph["E007"].get("E008"), "address_share")

    def test_entities_persisted_to_db(self):
        """实体持久化到 PortableDB entities 表。"""
        eng = _make_engine(self, self.tmp_path)
        eng.execute(_make_mock_input())
        rows = eng.db.query("entities")
        self.assertEqual(len(rows), 35)  # 10公司 + 10自然人 + 5地址 + 5电话 + 5账户


class TestBFSMultiHop(unittest.TestCase):
    """BFS 多跳发现：从目标实体出发，遍历 3-6 跳路径。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_bfs_discovers_related_parties(self):
        """BFS 从 E001 出发发现关联方（related_count > 0）。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        net = result["networks"][0]
        self.assertGreater(net["statistics"]["related_count"], 0)

    def test_bfs_hop_levels(self):
        """BFS 发现 1跳 / 2跳 / 3跳 关联方（hop 分布合理）。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        related = result["networks"][0]["related_parties"]
        hop_counts = {rp["hops"] for rp in related}
        self.assertIn(1, hop_counts)
        self.assertIn(2, hop_counts)
        self.assertIn(3, hop_counts)

    def test_bfs_max_hops_respected(self):
        """max_hops 限制遍历深度。"""
        eng = _make_engine(self, self.tmp_path)
        data = _make_mock_input()
        data["max_hops"] = 2
        result = eng.execute(data)
        related = result["networks"][0]["related_parties"]
        max_hops_found = max(rp["hops"] for rp in related)
        self.assertLessEqual(max_hops_found, 2)

    def test_bfs_path_starts_from_target(self):
        """BFS 路径以目标实体开头。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        related = result["networks"][0]["related_parties"]
        for rp in related:
            self.assertEqual(rp["path"][0], "E001")


class TestAssociationStrength(unittest.TestCase):
    """关联强度计算：路径越短强度越高、关系权重越高强度越高。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_shorter_path_higher_strength(self):
        """1跳关联方强度高于3跳关联方强度。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        related = result["networks"][0]["related_parties"]
        one_hop = [rp for rp in related if rp["hops"] == 1]
        three_hop = [rp for rp in related if rp["hops"] == 3]
        if one_hop and three_hop:
            max_one = max(rp["strength"] for rp in one_hop)
            max_three = max(rp["strength"] for rp in three_hop)
            self.assertGreater(max_one, max_three)

    def test_legal_rep_higher_than_phone(self):
        """法人关系（权重1.0）强度高于电话关系（权重0.4）。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        related = result["networks"][0]["related_parties"]
        by_id = {rp["entity_id"]: rp for rp in related}
        p001 = by_id.get("P001")  # legal_rep, 1跳, 权重1.0
        phone_rels = [rp for rp in related if rp["hops"] == 1 and "phone" in rp["relation_types"]]
        if p001 and phone_rels:
            self.assertGreater(p001["strength"], phone_rels[0]["strength"])

    def test_strength_range_0_to_1(self):
        """关联强度在 [0, 1] 范围内。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        related = result["networks"][0]["related_parties"]
        for rp in related:
            self.assertGreaterEqual(rp["strength"], 0.0)
            self.assertLessEqual(rp["strength"], 1.0)


class TestCycleDetection(unittest.TestCase):
    """环路检测：循环持股 / 交叉担保。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_circular_shareholding_detected(self):
        """循环持股检测：E004 持股 E001，E001 可达 E004。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        cycles = result["networks"][0]["cycles"]
        types = [c["type"] for c in cycles]
        self.assertIn("circular_shareholding", types)
        cs = [c for c in cycles if c["type"] == "circular_shareholding"]
        entities = set()
        for c in cs:
            entities.update(c["entities"])
        self.assertIn("E001", entities)
        self.assertIn("E004", entities)

    def test_cross_guarantee_detected(self):
        """交叉担保检测：E005 与 E006 互保。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        cycles = result["networks"][0]["cycles"]
        types = [c["type"] for c in cycles]
        self.assertIn("cross_guarantee", types)
        cg = [c for c in cycles if c["type"] == "cross_guarantee"]
        entities = set()
        for c in cg:
            entities.update(c["entities"])
        self.assertIn("E005", entities)
        self.assertIn("E006", entities)

    def test_cycle_risk_level_high(self):
        """环路检测风险级别为 high。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        cycles = result["networks"][0]["cycles"]
        for c in cycles:
            self.assertEqual(c["risk_level"], "high")


class TestHiddenLinkDiscovery(unittest.TestCase):
    """隐藏关联发现：3-6 跳路径发现非直接关联方。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_hidden_links_discovered(self):
        """隐藏关联（hops >= 3）被发现并标记。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        net = result["networks"][0]
        hidden = net["hidden_links"]
        self.assertGreater(len(hidden), 0)
        for h in hidden:
            self.assertTrue(h["is_hidden"])
            self.assertGreaterEqual(h["hops"], 3)

    def test_hidden_count_in_statistics(self):
        """统计中 hidden_count 与实际隐藏关联数一致。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute(_make_mock_input())
        net = result["networks"][0]
        self.assertEqual(net["statistics"]["hidden_count"], len(net["hidden_links"]))

    def test_hidden_links_persisted_to_db(self):
        """隐藏关联持久化到 PortableDB hidden_links 表。"""
        eng = _make_engine(self, self.tmp_path)
        eng.execute(_make_mock_input())
        rows = eng.db.query("hidden_links")
        self.assertGreater(len(rows), 0)
        hidden_rows = [r for r in rows if r["is_hidden"] == 1]
        self.assertGreater(len(hidden_rows), 0)

    def test_scan_results_persisted_to_db(self):
        """扫描结果持久化到 PortableDB scan_results 表。"""
        eng = _make_engine(self, self.tmp_path)
        eng.execute(_make_mock_input())
        rows = eng.db.query("scan_results")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_entity_id"], "E001")
        self.assertGreater(rows[0]["total_related"], 0)


class TestEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        # 临时目录由 addCleanup(_cleanup) 在 engine.close 之后清理，
        # 此处不再直接 cleanup，规避 Windows .db 文件锁。
        pass

    def test_empty_input(self):
        """空输入：无目标实体时返回空网络。"""
        eng = _make_engine(self, self.tmp_path)
        result = eng.execute({"entities": [], "relations": []})
        self.assertEqual(result["networks"], [])

    def test_invalid_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        eng = _make_engine(self, self.tmp_path)
        with self.assertRaises(ValueError):
            eng.execute(["not", "a", "dict"])

    def test_target_not_in_entities(self):
        """目标实体不在实体表中时跳过（不报错）。"""
        eng = _make_engine(self, self.tmp_path)
        data = _make_mock_input()
        data["target_entity_id"] = "NONEXIST"
        result = eng.execute(data)
        self.assertEqual(result["networks"], [])

    def test_multiple_targets(self):
        """多目标实体：为每个目标生成独立网络。"""
        eng = _make_engine(self, self.tmp_path)
        data = _make_mock_input()
        data["target_entity_ids"] = ["E001", "E002"]
        data.pop("target_entity_id", None)
        result = eng.execute(data)
        self.assertEqual(len(result["networks"]), 2)
        target_ids = {n["target_entity_id"] for n in result["networks"]}
        self.assertEqual(target_ids, {"E001", "E002"})


if __name__ == "__main__":
    unittest.main()
