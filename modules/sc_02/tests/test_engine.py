"""[SC-02] engine 单测：图构建 / PageRank / 社区发现 / 风险传导 / 路径发现。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.sc_02.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> KGEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {
        "db_path": str(Path(tmpdir) / "sc_02_test.db"),
        "fixtures_dir": str(_FIXTURES),
    }
    config.update(overrides)
    eng = KGEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + 模型参数。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_db_has_three_tables(self):
        """PortableDB 含 suppliers / relations / graph_analysis 三张表。"""
        tables = set(self.engine.db.tables())
        self.assertIn("suppliers", tables)
        self.assertIn("relations", tables)
        self.assertIn("graph_analysis", tables)

    def test_model_params_loaded(self):
        """模型参数：damping=0.85、max_iter=50、risk_decay=0.7。"""
        self.assertAlmostEqual(self.engine.model["damping"], 0.85)
        self.assertEqual(self.engine.model["max_iter"], 50)
        self.assertAlmostEqual(self.engine.model["risk_decay"], 0.7)

    def test_edge_weights_defined(self):
        """边权重表含 supplies/owns/related/executes/shares_address/shares_phone。"""
        w = self.engine.model["edge_weights"]
        for k in ("supplies", "owns", "related", "executes",
                  "shares_address", "shares_phone"):
            self.assertIn(k, w)
        self.assertAlmostEqual(w["supplies"], 1.0)
        self.assertAlmostEqual(w["owns"], 0.8)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：图构建 / 邻接表。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_builds_nodes_and_edges(self):
        """预处理：节点与边正确构建。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A", "name": "甲"},
                          {"supplier_id": "B", "name": "乙"}],
            "relations": [{"source": "A", "target": "B",
                           "relation_type": "supplies"}],
        })
        self.assertEqual(set(prepared["nodes"]), {"A", "B"})
        self.assertEqual(len(prepared["edges"]), 1)
        self.assertEqual(prepared["edges"][0]["source"], "A")
        self.assertEqual(prepared["edges"][0]["target"], "B")

    def test_preprocess_adjacency_correct(self):
        """邻接表 adj_out / adj_in 正确。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A"}, {"supplier_id": "B"}],
            "relations": [{"source": "A", "target": "B",
                           "relation_type": "supplies"}],
        })
        self.assertEqual(prepared["adj_out"]["A"], [("B", 1.0)])
        self.assertEqual(prepared["adj_in"]["B"], [("A", 1.0)])
        self.assertEqual(prepared["adj_out"]["B"], [])

    def test_preprocess_non_dict_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute([])
        with self.assertRaises(ValueError):
            self.engine.execute("not a dict")

    def test_preprocess_source_id_target_id_aliases(self):
        """relations 支持 source_id/target_id 别名。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A"}, {"supplier_id": "B"}],
            "relations": [{"source_id": "A", "target_id": "B",
                           "type": "supplies"}],
        })
        self.assertEqual(prepared["edges"][0]["source"], "A")
        self.assertEqual(prepared["edges"][0]["target"], "B")
        self.assertEqual(prepared["edges"][0]["relation_type"], "supplies")

    def test_preprocess_unknown_nodes_added(self):
        """relations 引用的未声明节点自动加入图（node_type=unknown）。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A"}],
            "relations": [{"source": "A", "target": "GHOST",
                           "relation_type": "supplies"}],
        })
        self.assertIn("GHOST", prepared["nodes"])
        self.assertEqual(
            prepared["node_attrs"]["GHOST"]["node_type"], "unknown"
        )

    def test_preprocess_custom_relation_weight(self):
        """显式 weight 覆盖默认边权重。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A"}, {"supplier_id": "B"}],
            "relations": [{"source": "A", "target": "B",
                           "relation_type": "supplies", "weight": 2.5}],
        })
        self.assertAlmostEqual(prepared["edges"][0]["weight"], 2.5)

    def test_preprocess_default_weight_for_unknown_type(self):
        """未知 relation_type 默认权重 1.0。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A"}, {"supplier_id": "B"}],
            "relations": [{"source": "A", "target": "B",
                           "relation_type": "subcontract"}],
        })
        self.assertAlmostEqual(prepared["edges"][0]["weight"], 1.0)


class TestEngineInferAndPostprocess(unittest.TestCase):
    """_infer / _postprocess：PageRank / 社区 / 风险 / 路径 / 汇总。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample()
        self.result = self.engine.execute(self.sample)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_result_has_all_keys(self):
        """结果含 nodes/edges/pagerank/communities/risk_scores/paths/summary。"""
        for k in ("nodes", "edges", "pagerank", "communities",
                  "risk_scores", "paths", "summary"):
            self.assertIn(k, self.result)

    def test_pagerank_sums_to_one(self):
        """PageRank 归一化后总和 ≈ 1。"""
        total = sum(self.result["pagerank"].values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_pagerank_values_in_range(self):
        """所有 PageRank 值 ∈ [0, 1]。"""
        for v in self.result["pagerank"].values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_communities_assigned(self):
        """每个节点都被分配社区（community_id >= 0）。"""
        for n in self.result["nodes"]:
            self.assertGreaterEqual(n["community_id"], 0)

    def test_risk_scores_in_range(self):
        """所有风险得分 ∈ [0, 1]。"""
        for v in self.result["risk_scores"].values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_top_pagerank_sorted_desc(self):
        """summary.top_pagerank 按 PageRank 降序排列（enriched_nodes 保持原序）。"""
        top = self.result["summary"]["top_pagerank"]
        prs = [n["pagerank"] for n in top]
        self.assertEqual(prs, sorted(prs, reverse=True))

    def test_node_enrichment_fields(self):
        """每个节点含 supplier_id/name/node_type/pagerank/community_id/risk_score。"""
        for n in self.result["nodes"]:
            for k in ("supplier_id", "name", "node_type",
                      "pagerank", "community_id", "risk_score"):
                self.assertIn(k, n)

    def test_summary_fields_populated(self):
        """summary 含 node_count/edge_count/community_count/avg_degree。"""
        s = self.result["summary"]
        self.assertEqual(s["node_count"], len(self.result["nodes"]))
        self.assertEqual(s["edge_count"], len(self.result["edges"]))
        self.assertIn("community_count", s)
        self.assertIn("avg_degree", s)

    def test_postprocess_community_distribution(self):
        """_postprocess 注入 community_distribution。"""
        s = self.result["summary"]
        self.assertIn("community_distribution", s)
        total = sum(s["community_distribution"].values())
        self.assertEqual(total, s["node_count"])

    def test_postprocess_high_risk(self):
        """_postprocess 注入 high_risk_count / high_risk_top。"""
        s = self.result["summary"]
        self.assertIn("high_risk_count", s)
        self.assertIn("high_risk_top", s)
        self.assertEqual(len(s["high_risk_top"]), min(s["high_risk_count"], 10))

    def test_top_pagerank_in_summary(self):
        """summary 含 top_pagerank 前 10。"""
        s = self.result["summary"]
        self.assertLessEqual(len(s["top_pagerank"]), 10)

    def test_risk_paths_structure(self):
        """风险路径结构：path 为列表、length 为正、end_risk 为 float。"""
        for p in self.result["paths"]:
            self.assertIsInstance(p["path"], list)
            self.assertGreaterEqual(p["length"], 1)
            self.assertIsInstance(p["end_risk"], (int, float))


class TestEngineGraphAlgorithms(unittest.TestCase):
    """图算法直接测试。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_pagerank_empty(self):
        """空节点列表 PageRank 返回 {}。"""
        self.assertEqual(self.engine._pagerank([], {}), {})

    def test_pagerank_single_node(self):
        """单节点 PageRank = 1.0。"""
        pr = self.engine._pagerank(["X"], {"X": []})
        self.assertAlmostEqual(pr["X"], 1.0)

    def test_risk_propagation_max_is_one(self):
        """风险传导后最大值被归一化为 1.0。"""
        nodes = ["A", "B", "C", "D"]
        adj = {"A": [("B", 1.0)], "B": [("C", 1.0)],
               "C": [("D", 1.0)], "D": []}
        risk = self.engine._risk_propagation(nodes, adj)
        self.assertAlmostEqual(max(risk.values()), 1.0)

    def test_find_risk_paths_chain(self):
        """3+ 节点链式图能发现风险路径。"""
        nodes = ["A", "B", "C", "D"]
        adj_out = {"A": [("B", 1.0)], "B": [("C", 1.0)],
                   "C": [("D", 1.0)], "D": []}
        adj_in = {"A": [], "B": [("A", 1.0)], "C": [("B", 1.0)],
                  "D": [("C", 1.0)]}
        risk = {"A": 1.0, "B": 0.6, "C": 0.5, "D": 0.4}
        paths = self.engine._find_risk_paths(
            nodes, adj_out, adj_in, risk, max_paths=20
        )
        self.assertGreater(len(paths), 0)
        # 最高风险源 A（risk=1.0）排在首位 → 第一条路径以 A 开头
        self.assertEqual(paths[0]["path"][0], "A")
        # 所有路径均为非空列表、length 为正
        for p in paths:
            self.assertIsInstance(p["path"], list)
            self.assertGreaterEqual(p["length"], 1)

    def test_louvain_returns_communities(self):
        """Louvain 为每个节点返回非负社区 id。"""
        nodes = ["A", "B", "C"]
        adj_out = {"A": [("B", 1.0)], "B": [], "C": []}
        adj_in = {"A": [], "B": [("A", 1.0)], "C": []}
        comms = self.engine._louvain(nodes, adj_out, adj_in)
        self.assertEqual(len(comms), 3)
        for c in comms.values():
            self.assertGreaterEqual(c, 0)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_input(self):
        """空输入 → 空结果、node_count=0。"""
        result = self.engine.execute({"suppliers": [], "relations": []})
        self.assertEqual(result["summary"]["node_count"], 0)
        self.assertEqual(result["summary"]["edge_count"], 0)
        self.assertEqual(result["nodes"], [])

    def test_single_node_no_edges(self):
        """单节点无边 → pagerank=1.0、risk 归一化。"""
        result = self.engine.execute({
            "suppliers": [{"supplier_id": "SOLO", "name": "独体"}],
            "relations": [],
        })
        self.assertEqual(len(result["nodes"]), 1)
        self.assertAlmostEqual(result["pagerank"]["SOLO"], 1.0)
        self.assertGreaterEqual(result["risk_scores"]["SOLO"], 0.0)

    def test_missing_suppliers_key(self):
        """缺 suppliers 键 → 空结果而非异常。"""
        result = self.engine.execute({"relations": []})
        self.assertEqual(result["summary"]["node_count"], 0)

    def test_relation_with_missing_target_skipped(self):
        """缺 target 的 relation 被跳过。"""
        prepared = self.engine._preprocess({
            "suppliers": [{"supplier_id": "A"}],
            "relations": [{"source": "A", "relation_type": "supplies"}],
        })
        self.assertEqual(len(prepared["edges"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
