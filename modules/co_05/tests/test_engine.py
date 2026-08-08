"""[CO-05] engine 单测：图构建 / 模式检测 / 环路检测 / 资金流追踪 / 中心性分析。

unittest 风格（不依赖 pytest），覆盖：
  * 模型加载 (_load_model)
  * 预处理 (_preprocess)
  * 图构建 (_build_graph)
  * 模式检测 Smurfing / Structuring / Money Loop / Shell Company
  * 环路检测 (_detect_cycles)
  * 资金流追踪 (_trace_funds / BFS)
  * 中心性分析 (_centrality_analysis / PageRank / 度 / 中介)
  * 后处理 (_postprocess)
  * 边界情况
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_05.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：模型初始化。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_model_has_empty_nodes(self):
        """模型初始化 nodes 为空 dict。"""
        self.assertEqual(len(self.engine.model["nodes"]), 0)

    def test_model_has_empty_edges(self):
        """模型初始化 edges 为空 list。"""
        self.assertEqual(len(self.engine.model["edges"]), 0)

    def test_model_has_seed_patterns(self):
        """模型含 6 个种子模式。"""
        patterns = self.engine.model["patterns"]
        self.assertEqual(len(patterns), 6)
        pids = {p["pattern_id"] for p in patterns}
        self.assertIn("PAT-SMURFING", pids)
        self.assertIn("PAT-MONEY-LOOP", pids)
        self.assertIn("PAT-SHELL-COMPANY", pids)

    def test_model_has_adjacency(self):
        """模型含 adjacency（defaultdict）。"""
        self.assertEqual(len(self.engine.model["adjacency"]), 0)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入归一化。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_preprocess_default_action(self):
        """无 action → 默认 detect_patterns。"""
        prepared = self.engine._preprocess({"nodes": [], "edges": []})
        self.assertEqual(prepared["action"], "detect_patterns")

    def test_preprocess_extract_from_graph(self):
        """从 graph 字段提取 nodes/edges。"""
        prepared = self.engine._preprocess({
            "graph": {
                "nodes": [{"node_id": "N1", "node_type": "account"}],
                "edges": [{"src": "N1", "dst": "N2", "amount": 100}],
            }
        })
        self.assertEqual(len(prepared["nodes"]), 1)
        self.assertEqual(len(prepared["edges"]), 1)

    def test_preprocess_string_input(self):
        """字符串输入 → 默认 action detect_patterns。"""
        prepared = self.engine._preprocess("some_string")
        self.assertEqual(prepared["action"], "detect_patterns")
        self.assertEqual(len(prepared["nodes"]), 0)

    def test_preprocess_lazy_load_model(self):
        """未 setup 时 _preprocess 懒加载模型。"""
        eng = KGEngine()
        prepared = eng._preprocess({})
        self.assertIsNotNone(eng.model)
        self.assertEqual(prepared["action"], "detect_patterns")


class TestEngineBuildGraph(unittest.TestCase):
    """_build_graph：图构建。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_nodes_added(self):
        """节点正确添加到 model.nodes。"""
        nodes = [
            {"node_id": "N1", "node_type": "account", "attrs": {"owner": "A"}},
            {"node_id": "N2", "node_type": "company", "attrs": {}},
        ]
        self.engine._build_graph(nodes, [])
        self.assertIn("N1", self.engine.model["nodes"])
        self.assertIn("N2", self.engine.model["nodes"])
        self.assertEqual(
            self.engine.model["nodes"]["N1"]["node_type"], "account"
        )

    def test_edges_added(self):
        """边正确添加到 model.edges。"""
        nodes = [{"node_id": "A"}, {"node_id": "B"}]
        edges = [{"src": "A", "dst": "B", "amount": 1000, "edge_type": "transfer"}]
        self.engine._build_graph(nodes, edges)
        self.assertEqual(len(self.engine.model["edges"]), 1)
        e = self.engine.model["edges"][0]
        self.assertEqual(e["src"], "A")
        self.assertEqual(e["dst"], "B")
        self.assertEqual(e["amount"], 1000.0)

    def test_adjacency_bidirectional(self):
        """邻接表双向存储（A→B 同时出现在 A 和 B 的邻接中）。"""
        nodes = [{"node_id": "A"}, {"node_id": "B"}]
        edges = [{"src": "A", "dst": "B", "amount": 100}]
        self.engine._build_graph(nodes, edges)
        adj = self.engine.model["adjacency"]
        a_neighbors = [n["dst"] for n in adj.get("A", [])]
        b_neighbors = [n["dst"] for n in adj.get("B", [])]
        self.assertIn("B", a_neighbors)
        self.assertIn("A", b_neighbors)

    def test_node_type_counter(self):
        """node_types Counter 统计节点类型。"""
        nodes = [
            {"node_id": "N1", "node_type": "account"},
            {"node_id": "N2", "node_type": "account"},
            {"node_id": "N3", "node_type": "company"},
        ]
        self.engine._build_graph(nodes, [])
        self.assertEqual(self.engine.model["node_types"]["account"], 2)
        self.assertEqual(self.engine.model["node_types"]["company"], 1)


class TestEngineDetectPatterns(unittest.TestCase):
    """_detect_patterns：洗钱模式检测。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_smurfing_detected(self):
        """3+ 源账户向同一目标汇入 < 10000 → Smurfing。"""
        nodes = [{"node_id": f"A{i}"} for i in range(4)]
        edges = [
            {"src": f"A{i}", "dst": "A3", "edge_type": "transfer",
             "amount": 5000, "timestamp": "2025-06-01"}
            for i in range(3)
        ]
        self.engine._build_graph(nodes, edges)
        result = self.engine._detect_patterns()
        smurf = [d for d in result["patterns_detected"]
                 if d["pattern_id"] == "PAT-SMURFING"]
        self.assertEqual(len(smurf), 1)
        self.assertEqual(smurf[0]["target_node"], "A3")
        self.assertEqual(smurf[0]["source_count"], 3)

    def test_structuring_detected(self):
        """同一源 3+ 笔 8000-10000 金额 → Structuring。"""
        nodes = [{"node_id": f"A{i}"} for i in range(4)]
        edges = [
            {"src": "A0", "dst": f"A{i+1}", "edge_type": "transfer",
             "amount": 9000, "timestamp": "2025-06-01"}
            for i in range(3)
        ]
        self.engine._build_graph(nodes, edges)
        result = self.engine._detect_patterns()
        struct = [d for d in result["patterns_detected"]
                  if d["pattern_id"] == "PAT-STRUCTURING"]
        self.assertEqual(len(struct), 1)
        self.assertEqual(struct[0]["target_node"], "A0")
        self.assertEqual(struct[0]["transaction_count"], 3)

    def test_money_loop_detected(self):
        """A→B→C→A 闭环 + 金额衰减 < 30% → Money Loop。"""
        nodes = [{"node_id": n} for n in ("A", "B", "C")]
        edges = [
            {"src": "A", "dst": "B", "edge_type": "transfer", "amount": 10000},
            {"src": "B", "dst": "C", "edge_type": "transfer", "amount": 9500},
            {"src": "C", "dst": "A", "edge_type": "transfer", "amount": 9000},
        ]
        self.engine._build_graph(nodes, edges)
        result = self.engine._detect_patterns()
        loops = [d for d in result["patterns_detected"]
                 if d["pattern_id"] == "PAT-MONEY-LOOP"]
        self.assertGreaterEqual(len(loops), 1)
        self.assertEqual(loops[0]["hop_count"], 3)
        self.assertGreater(loops[0]["return_ratio"], 0.7)

    def test_shell_company_detected(self):
        """3+ 节点共享 phone → Shell Company。"""
        nodes = [
            {"node_id": f"C{i}", "node_type": "company",
             "attrs": {"phone": "010-99999999"}}
            for i in range(3)
        ]
        edges = [{"src": "C0", "dst": "C1", "edge_type": "transfer", "amount": 100}]
        self.engine._build_graph(nodes, edges)
        result = self.engine._detect_patterns()
        shells = [d for d in result["patterns_detected"]
                  if d["pattern_id"] == "PAT-SHELL-COMPANY"]
        self.assertGreaterEqual(len(shells), 1)
        self.assertEqual(shells[0]["node_count"], 3)

    def test_empty_graph_no_patterns(self):
        """空图 → 无检测（含 note 提示）。"""
        result = self.engine._detect_patterns()
        self.assertEqual(len(result["patterns_detected"]), 0)
        self.assertEqual(result.get("total_detections", 0), 0)
        self.assertIn("note", result)

    def test_full_fixture_run(self):
        """用 fixtures/sample_input.json 全量检测。"""
        data = _load_sample_input()
        self.engine.execute(data)
        result = self.engine._detect_patterns()
        self.assertGreater(result["total_detections"], 0)
        pids = {d["pattern_id"] for d in result["patterns_detected"]}
        self.assertIn("PAT-SMURFING", pids)
        self.assertIn("PAT-MONEY-LOOP", pids)
        self.assertIn("PAT-SHELL-COMPANY", pids)


class TestEngineDetectCycles(unittest.TestCase):
    """_detect_cycles：有向环检测。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()

    def test_simple_cycle_found(self):
        """A→B→C→A 闭环被检测到。"""
        nodes = [{"node_id": n} for n in ("A", "B", "C")]
        edges = [
            {"src": "A", "dst": "B", "amount": 100},
            {"src": "B", "dst": "C", "amount": 100},
            {"src": "C", "dst": "A", "amount": 100},
        ]
        self.engine._build_graph(nodes, edges)
        cycles = self.engine._detect_cycles(max_len=6)
        self.assertGreaterEqual(len(cycles), 1)
        # 环应包含 A, B, C
        cycle_nodes = set()
        for c in cycles:
            cycle_nodes.update(c)
        self.assertEqual(cycle_nodes, {"A", "B", "C"})

    def test_no_cycle_in_acyclic(self):
        """无环图 → 无环路。"""
        nodes = [{"node_id": n} for n in ("A", "B", "C")]
        edges = [
            {"src": "A", "dst": "B", "amount": 100},
            {"src": "B", "dst": "C", "amount": 100},
        ]
        self.engine._build_graph(nodes, edges)
        cycles = self.engine._detect_cycles(max_len=6)
        self.assertEqual(len(cycles), 0)


class TestEngineTraceFunds(unittest.TestCase):
    """_trace_funds：BFS 资金流追踪。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()
        nodes = [{"node_id": n} for n in ("A", "B", "C", "D")]
        edges = [
            {"src": "A", "dst": "B", "amount": 1000, "edge_type": "transfer"},
            {"src": "B", "dst": "C", "amount": 800, "edge_type": "transfer"},
            {"src": "C", "dst": "D", "amount": 600, "edge_type": "transfer"},
        ]
        self.engine._build_graph(nodes, edges)

    def test_trace_from_single_node(self):
        """从单个起点追踪资金流 → 找到路径。"""
        result = self.engine._trace_funds(["A"])
        self.assertEqual(result["start_nodes"], ["A"])
        self.assertGreater(result["total_paths_found"], 0)
        # 路径中应包含 A→B
        paths = result["paths"]
        has_ab = any(p["path"][:2] == ["A", "B"] for p in paths)
        self.assertTrue(has_ab)

    def test_trace_no_start_nodes(self):
        """无起点 → 返回提示。"""
        result = self.engine._trace_funds([])
        self.assertEqual(len(result["paths"]), 0)
        self.assertEqual(result.get("total_paths_found", 0), 0)
        self.assertIn("note", result)

    def test_trace_path_amounts(self):
        """路径含金额汇总。"""
        result = self.engine._trace_funds(["A"])
        for p in result["paths"]:
            self.assertGreaterEqual(p["total_amount"], 0)
            self.assertIsInstance(p["hop_count"], int)


class TestEngineCentrality(unittest.TestCase):
    """_centrality_analysis：中心性分析。"""

    def setUp(self):
        self.engine = KGEngine()
        self.engine.setup()
        nodes = [{"node_id": n} for n in ("A", "B", "C", "D")]
        edges = [
            {"src": "A", "dst": "B", "amount": 100, "edge_type": "transfer"},
            {"src": "A", "dst": "C", "amount": 100, "edge_type": "transfer"},
            {"src": "B", "dst": "D", "amount": 100, "edge_type": "transfer"},
            {"src": "C", "dst": "D", "amount": 100, "edge_type": "transfer"},
        ]
        self.engine._build_graph(nodes, edges)

    def test_centrality_returns_top_nodes(self):
        """中心性分析返回 top_pagerank / top_betweenness / top_degree。"""
        result = self.engine._centrality_analysis()
        self.assertIn("top_pagerank", result)
        self.assertIn("top_betweenness", result)
        self.assertIn("top_degree", result)
        self.assertGreater(len(result["top_pagerank"]), 0)

    def test_pagerank_values_sum_approximately_one(self):
        """PageRank 值之和约等于 1。"""
        result = self.engine._centrality_analysis()
        total = sum(item["score"] for item in result["top_pagerank"])
        # top_pagerank 可能只取前 20，但小图全部返回
        self.assertAlmostEqual(total, 1.0, places=1)

    def test_network_health_stats(self):
        """network_health 含 average_degree / max_degree / isolated_nodes。"""
        result = self.engine._centrality_analysis()
        health = result["network_health"]
        self.assertIn("average_degree", health)
        self.assertIn("max_degree", health)
        self.assertIn("isolated_nodes", health)
        self.assertGreater(health["average_degree"], 0)

    def test_empty_graph_centrality(self):
        """空图 → 返回 error。"""
        eng = KGEngine()
        eng.setup()
        result = eng._centrality_analysis()
        self.assertIn("error", result)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：meta 添加。"""

    def test_postprocess_adds_meta(self):
        """_postprocess 添加 meta（module/family/generated_at）。"""
        eng = KGEngine()
        eng.setup()
        result = eng._postprocess({"patterns_detected": []})
        self.assertIn("meta", result)
        self.assertEqual(result["meta"]["module"], "CO-05")
        self.assertEqual(result["meta"]["family"], "kg_gnn")
        self.assertIn("generated_at", result["meta"])

    def test_postprocess_preserves_existing_module(self):
        """已有 module 字段 → 不覆盖。"""
        eng = KGEngine()
        eng.setup()
        result = eng._postprocess({"module": "existing", "patterns_detected": []})
        self.assertEqual(result["module"], "existing")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def test_unknown_action(self):
        """未知 action → 返回 error。"""
        eng = KGEngine()
        eng.setup()
        result = eng.execute({
            "action": "unknown_action",
            "nodes": [{"node_id": "A"}],
            "edges": [],
        })
        self.assertIn("error", result)

    def test_load_graph_action(self):
        """load_graph action → 返回图谱摘要。"""
        eng = KGEngine()
        eng.setup()
        result = eng.execute({
            "action": "load_graph",
            "nodes": [{"node_id": "A"}, {"node_id": "B"}],
            "edges": [{"src": "A", "dst": "B", "amount": 100}],
        })
        self.assertEqual(result["node_count"], 2)
        self.assertEqual(result["edge_count"], 1)

    def test_full_fixture_run(self):
        """用 fixtures/sample_input.json 全量跑通。"""
        data = _load_sample_input()
        eng = KGEngine()
        eng.setup()
        result = eng.execute(data)
        self.assertIn("patterns_detected", result)
        self.assertIn("meta", result)
        self.assertGreater(result["total_detections"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
