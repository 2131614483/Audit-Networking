"""[FO-02] engine 单测：图构建 / PageRank / 社区发现 / 模式识别 / 风险评分 / 异常检测。

unittest 风格（不依赖 pytest）。每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from modules.fo_02.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> KGEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {"db_path": str(Path(tmpdir) / "fo_02_test.db")}
    config.update(overrides)
    eng = KGEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + 模型加载。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_db_initialized(self):
        """PortableDB 已初始化。"""
        self.assertIsNotNone(self.engine.db)

    def test_model_has_fraud_patterns(self):
        """模型含 5 类舞弊模式定义。"""
        self.assertEqual(len(self.engine.model["fraud_patterns"]), 5)

    def test_risk_weights_sum_to_one(self):
        """风险权重之和 = 1.0。"""
        w = self.engine.model["risk_weights"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=4)

    def test_anomaly_threshold(self):
        """异常 z-score 阈值 = 2.0。"""
        self.assertEqual(self.engine.model["anomaly_z_threshold"], 2.0)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：图构建（实体 / 边解析）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_entities_parsed(self):
        """实体解析为 dict（按 entity_id 索引）。"""
        prepared = self.engine._preprocess(_load_sample())
        self.assertEqual(len(prepared["entities"]), 7)
        self.assertEqual(prepared["entities"]["E1"]["name"], "壳公司甲")

    def test_edges_parsed(self):
        """交易边解析为列表，amount 转 float。"""
        prepared = self.engine._preprocess(_load_sample())
        self.assertEqual(len(prepared["edges"]), 13)
        self.assertIsInstance(prepared["edges"][0]["amount"], float)

    def test_auto_creates_missing_entities(self):
        """交易引用未声明实体 → 自动创建（type=未知）。"""
        data = {"entities": [{"entity_id": "A", "name": "A"}],
                "transactions": [{"from": "A", "to": "B", "amount": 100}]}
        prepared = self.engine._preprocess(data)
        self.assertIn("B", prepared["entities"])
        self.assertEqual(prepared["entities"]["B"]["type"], "未知")

    def test_skips_invalid_edges(self):
        """缺 from/to 的边被跳过。"""
        data = {"entities": [{"entity_id": "A", "name": "A"}],
                "transactions": [{"from": "", "to": "B", "amount": 100},
                                 {"from": "A", "to": "", "amount": 200}]}
        prepared = self.engine._preprocess(data)
        self.assertEqual(len(prepared["edges"]), 0)

    def test_amount_to_float(self):
        """金额字符串转 float。"""
        data = {"entities": [{"entity_id": "A", "name": "A"}, {"entity_id": "B", "name": "B"}],
                "transactions": [{"from": "A", "to": "B", "amount": "12345"}]}
        prepared = self.engine._preprocess(data)
        self.assertEqual(prepared["edges"][0]["amount"], 12345.0)

    def test_non_dict_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess([1, 2, 3])


class TestEnginePageRank(unittest.TestCase):
    """_pagerank：中心性计算。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_hub_has_higher_pagerank(self):
        """枢纽节点（连接多个节点）PageRank 更高。"""
        nodes = ["hub", "a", "b", "c"]
        adj = defaultdict(list)
        adj["hub"] = [("a", 1, ""), ("b", 1, ""), ("c", 1, "")]
        pr = self.engine._pagerank(nodes, adj)
        self.assertGreater(pr["hub"], pr["a"])
        self.assertGreater(pr["hub"], pr["c"])

    def test_pagerank_sum_positive(self):
        """PageRank 值均为正。"""
        nodes = ["A", "B", "C"]
        adj = defaultdict(list, {"A": [("B", 1, "")], "B": [("C", 1, "")]})
        pr = self.engine._pagerank(nodes, adj)
        for v in pr.values():
            self.assertGreater(v, 0.0)

    def test_pagerank_single_node(self):
        """单节点无边 → PageRank = (1-d)/n = 0.15。"""
        pr = self.engine._pagerank(["solo"], defaultdict(list))
        self.assertAlmostEqual(pr["solo"], 0.15, places=2)


class TestEngineLouvain(unittest.TestCase):
    """_louvain：社区发现。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_assigns_all_nodes(self):
        """所有节点都被分配到某个社区。"""
        nodes = ["A", "B", "C"]
        adj = defaultdict(list, {"A": [("B", 1, "")], "B": [("C", 1, "")]})
        comms = self.engine._louvain(nodes, adj)
        self.assertEqual(len(comms), 3)
        for n in nodes:
            self.assertIn(n, comms)

    def test_isolated_node_own_community(self):
        """孤立节点（无边）保持自身社区。"""
        nodes = ["A", "B", "ISO"]
        adj = defaultdict(list, {"A": [("B", 1, "")], "B": [("A", 1, "")]})
        comms = self.engine._louvain(nodes, adj)
        self.assertEqual(comms["ISO"], "ISO")

    def test_connected_nodes_same_community(self):
        """紧密连接的节点归入同一社区。"""
        nodes = ["A", "B", "C"]
        adj = defaultdict(list, {"A": [("B", 1, "")], "B": [("A", 1, "")],
                                 "C": [("A", 1, "")]})
        comms = self.engine._louvain(nodes, adj)
        self.assertEqual(comms["A"], comms["B"])


class TestEnginePatternDetection(unittest.TestCase):
    """_detect_patterns：循环 / 对称 / 高频 模式识别。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_detect_cycle(self):
        """A→B→C→A 闭环 → 检测到循环交易。"""
        entities = {"A": {"entity_id": "A"}, "B": {"entity_id": "B"}, "C": {"entity_id": "C"}}
        edges = [{"src": "A", "dst": "B", "amount": 100, "time": "", "txn_type": "", "note": ""},
                 {"src": "B", "dst": "C", "amount": 100, "time": "", "txn_type": "", "note": ""},
                 {"src": "C", "dst": "A", "amount": 100, "time": "", "txn_type": "", "note": ""}]
        adj = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e["amount"], e["time"]))
        patterns = self.engine._detect_patterns(entities, edges, adj)
        cycle_patterns = [p for p in patterns if p["type"] == "循环交易"]
        self.assertGreater(len(cycle_patterns), 0)

    def test_detect_symmetric(self):
        """A→B 与 B→A 金额接近 → 对称资金流。"""
        entities = {"A": {"entity_id": "A"}, "B": {"entity_id": "B"}}
        edges = [{"src": "A", "dst": "B", "amount": 100, "time": "", "txn_type": "", "note": ""},
                 {"src": "B", "dst": "A", "amount": 85, "time": "", "txn_type": "", "note": ""}]
        adj = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e["amount"], e["time"]))
        patterns = self.engine._detect_patterns(entities, edges, adj)
        sym = [p for p in patterns if p["type"] == "对称资金流"]
        self.assertEqual(len(sym), 1)
        self.assertGreater(sym[0]["amount_ratio"], 0.7)

    def test_detect_high_frequency(self):
        """5+ 笔同向交易 → 高频交易。"""
        entities = {"A": {"entity_id": "A"}, "B": {"entity_id": "B"}}
        edges = [{"src": "A", "dst": "B", "amount": 100, "time": "", "txn_type": "", "note": ""}
                 for _ in range(5)]
        adj = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e["amount"], e["time"]))
        patterns = self.engine._detect_patterns(entities, edges, adj)
        hf = [p for p in patterns if p["type"] == "高频交易"]
        self.assertEqual(len(hf), 1)
        self.assertEqual(hf[0]["frequency"], 5)

    def test_no_patterns_simple_chain(self):
        """简单链 A→B→C 无循环/对称/高频。"""
        entities = {"A": {"entity_id": "A"}, "B": {"entity_id": "B"}, "C": {"entity_id": "C"}}
        edges = [{"src": "A", "dst": "B", "amount": 100, "time": "", "txn_type": "", "note": ""},
                 {"src": "B", "dst": "C", "amount": 100, "time": "", "txn_type": "", "note": ""}]
        adj = defaultdict(list)
        for e in edges:
            adj[e["src"]].append((e["dst"], e["amount"], e["time"]))
        patterns = self.engine._detect_patterns(entities, edges, adj)
        self.assertEqual(patterns, [])

    def test_find_cycle_returns_path(self):
        """_find_cycle 返回闭合路径。"""
        adj = defaultdict(list, {"A": [("B", 1, "")], "B": [("C", 1, "")],
                                 "C": [("A", 1, "")]})
        cycle = self.engine._find_cycle("A", "A", adj, {"A"}, ["A"], 4)
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle[0], "A")
        self.assertEqual(cycle[-1], "A")


class TestEngineRiskScoring(unittest.TestCase):
    """_infer：风险评分（中心性 / 异常 / 模式参与）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.result = self.engine.execute(_load_sample())

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_risk_scores_for_all_entities(self):
        """每个实体都有风险评分。"""
        self.assertEqual(len(self.result["risk_scores"]), 7)

    def test_risk_score_in_range(self):
        """风险评分 ∈ [0, 1]。"""
        for rs in self.result["risk_scores"].values():
            self.assertGreaterEqual(rs["total"], 0.0)
            self.assertLessEqual(rs["total"], 1.0)

    def test_risk_levels_valid(self):
        """风险等级为 高/中/低。"""
        for rs in self.result["risk_scores"].values():
            self.assertIn(rs["level"], ("高", "中", "低"))

    def test_e1_is_high_risk(self):
        """E1（壳公司甲）为高风险。"""
        self.assertEqual(self.result["risk_scores"]["E1"]["level"], "高")

    def test_risk_breakdown_has_components(self):
        """风险明细含 4 个分量。"""
        rs = self.result["risk_scores"]["E1"]
        for k in ("degree_centrality", "transaction_anomaly", "pattern_involvement", "amount_concentration"):
            self.assertIn(k, rs["breakdown"])

    def test_pagerank_recorded(self):
        """每个实体记录 pagerank 值。"""
        for rs in self.result["risk_scores"].values():
            self.assertIn("pagerank", rs)

    def test_hub_has_high_pagerank(self):
        """E1 作为枢纽 pagerank 最高。"""
        prs = {eid: rs["pagerank"] for eid, rs in self.result["risk_scores"].items()}
        self.assertEqual(max(prs, key=prs.get), "E1")


class TestEngineAnomalyDetection(unittest.TestCase):
    """异常交易检测（z-score）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_anomaly_detected(self):
        """样本含 500 万异常大额 → 检测到异常。"""
        result = self.engine.execute(_load_sample())
        self.assertGreater(len(result["anomalies"]), 0)

    def test_anomaly_z_score_above_threshold(self):
        """异常交易 |z-score| > 2.0。"""
        result = self.engine.execute(_load_sample())
        for a in result["anomalies"]:
            self.assertGreater(abs(a["z_score"]), 2.0)

    def test_anomaly_involves_e1_e5(self):
        """异常交易为 E1→E5（500 万）。"""
        result = self.engine.execute(_load_sample())
        a = result["anomalies"][0]
        self.assertEqual(a["src"], "E1")
        self.assertEqual(a["dst"], "E5")
        self.assertEqual(a["amount"], 5000000.0)

    def test_no_anomaly_uniform_amounts(self):
        """金额一致 → 无异常。"""
        data = {"entities": [{"entity_id": "A", "name": "A"}, {"entity_id": "B", "name": "B"}],
                "transactions": [{"from": "A", "to": "B", "amount": 100, "time": "t"} for _ in range(5)]}
        result = self.engine.execute(data)
        self.assertEqual(len(result["anomalies"]), 0)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：网络风险等级 / 摘要。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_network_risk_level_added(self):
        """_postprocess 添加 network_risk_level。"""
        result = self.engine.execute(_load_sample())
        self.assertIn("network_risk_level", result["summary"])

    def test_network_risk_level_valid(self):
        """网络风险等级为 高风险/中风险/低风险。"""
        result = self.engine.execute(_load_sample())
        self.assertIn(result["summary"]["network_risk_level"], ("高风险", "中风险", "低风险"))

    def test_summary_complete(self):
        """摘要含全部统计字段。"""
        result = self.engine.execute(_load_sample())
        s = result["summary"]
        for k in ("entity_count", "transaction_count", "community_count",
                  "anomaly_count", "pattern_count", "high_risk_entities", "total_volume"):
            self.assertIn(k, s)

    def test_sample_network_medium_risk(self):
        """样本网络为中风险（1/7 高风险 > 5% 但 < 15%）。"""
        result = self.engine.execute(_load_sample())
        self.assertEqual(result["summary"]["network_risk_level"], "中风险")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_input(self):
        """空输入 → 0 实体 0 交易。"""
        result = self.engine.execute({"entities": [], "transactions": []})
        self.assertEqual(result["summary"]["entity_count"], 0)
        self.assertEqual(result["summary"]["transaction_count"], 0)

    def test_single_entity_no_edges(self):
        """单实体无边 → 低风险。"""
        result = self.engine.execute({"entities": [{"entity_id": "X", "name": "X"}],
                                      "transactions": []})
        self.assertEqual(result["summary"]["entity_count"], 1)
        self.assertEqual(result["risk_scores"]["X"]["level"], "低")

    def test_execute_full_flow(self):
        """完整执行流程产出全部字段。"""
        result = self.engine.execute(_load_sample())
        for key in ("entities", "edges", "risk_scores", "anomalies",
                    "patterns", "communities", "summary"):
            self.assertIn(key, result)

    def test_total_volume_matches(self):
        """总交易额 = 各边金额之和。"""
        result = self.engine.execute(_load_sample())
        expected = sum(e["amount"] for e in result["edges"])
        self.assertAlmostEqual(result["summary"]["total_volume"], expected)

    def test_high_risk_count_consistent(self):
        """high_risk_entities 与 risk_levels 一致。"""
        result = self.engine.execute(_load_sample())
        high = sum(1 for rs in result["risk_scores"].values() if rs["level"] == "高")
        self.assertEqual(result["summary"]["high_risk_entities"], high)


if __name__ == "__main__":
    unittest.main(verbosity=2)
