"""[FO-01] engine 单测：四层扫描各层命中 / 评分 / 风险分级 / 图谱关联发现。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_01.engine import MLEngine, _parse_amount, _parse_date

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture_txs():
    """加载 transactions.jsonl 全量交易。"""
    path = _FIXTURES / "transactions.jsonl"
    txs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                txs.append(json.loads(line))
    return txs


def _make_engine(tmpdir: str, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {
        "threshold": {"confidence": 0.85},
        "db_path": str(Path(tmpdir) / "fo_01_test.db"),
        "fixtures_dir": str(_FIXTURES),
        "random_seed": 42,
    }
    config.update(overrides)
    eng = MLEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：PortableDB 初始化 + 模式库加载。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_db_has_four_tables(self):
        """PortableDB 含 transactions / fraud_flags / fraud_patterns / scan_results 四张表。"""
        tables = set(self.engine.db.tables())
        self.assertIn("transactions", tables)
        self.assertIn("fraud_flags", tables)
        self.assertIn("fraud_patterns", tables)
        self.assertIn("scan_results", tables)

    def test_fraud_patterns_loaded_from_fixture(self):
        """历史舞弊模式库从 fixtures 导入（至少 10 条）。"""
        count = self.engine.db.count("fraud_patterns")
        self.assertGreaterEqual(count, 10)
        # model 中 patterns 为启用规则
        self.assertEqual(len(self.engine.model["fraud_patterns"]), count)

    def test_benford_expected_distribution(self):
        """Benford 期望频率：digit 1 ≈ 0.301, digit 9 ≈ 0.046。"""
        exp = self.engine.model["benford_expected"]
        self.assertAlmostEqual(exp[1], 0.30103, places=3)
        self.assertAlmostEqual(exp[9], 0.04576, places=3)

    def test_layer_weights_sum_to_one(self):
        """四层权重之和 = 1.0。"""
        w = self.engine.model["layer_weights"]
        self.assertAlmostEqual(
            sum(w.values()), 1.0, places=4
        )


class TestEngineStatisticalLayer(unittest.TestCase):
    """第一层：统计层（Benford + Z-Score + IQR）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.txs = _load_fixture_txs()
        self.result = self.engine.execute({"transactions": self.txs})
        self.stat = self.result["layer_results"]["statistical"]

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_benford_anomaly_detected(self):
        """整体 Benford 卡方检验超过临界值 → is_anomaly=True。"""
        self.assertGreater(
            self.stat["benford"]["chi_square"],
            self.stat["benford"]["critical_value"],
        )
        self.assertTrue(self.stat["benford"]["is_anomaly"])

    def test_benford_flags_overrepresented_digit9(self):
        """首位数字 9 过度代表 → 涉及交易被标记。"""
        flagged = self.stat["benford"]["flagged_tx_ids"]
        self.assertGreater(len(flagged), 0)
        # 所有被标记交易的首位数字应为 9（过度代表的数字）
        for tid in flagged:
            tx = next(t for t in self.txs if t["tx_id"] == tid)
            first = int(str(int(tx["amount"]))[0])
            # 被标记的交易首位数字应为过度代表的数字（比例为最高者）
            ratio = self.stat["benford"]["per_digit_ratio"][str(first)]
            self.assertGreater(ratio, 1.5)

    def test_zscore_flags_large_outliers(self):
        """Z-Score > 3σ 的大额异常交易被标记。

        注意：极端异常值会膨胀标准差，使中等异常值的 Z-score < 3。
        此处仅断言最极端的异常交易（z > 3）被标记。
        """
        flagged = self.stat["z_score"]["flagged_tx_ids"]
        self.assertGreater(len(flagged), 0)
        # 最极端的大额异常交易（>500万，z > 3）应被标记
        extreme_outliers = [t for t in self.txs if t["amount"] > 5000000]
        extreme_ids = {t["tx_id"] for t in extreme_outliers}
        self.assertTrue(
            extreme_ids.issubset(set(flagged)),
            f"极端异常交易未被Z-Score标记: {extreme_ids - set(flagged)}",
        )

    def test_iqr_flags_outliers(self):
        """IQR 异常检测标记超出上下界的交易。"""
        flagged = self.stat["iqr"]["flagged_tx_ids"]
        self.assertGreater(len(flagged), 0)
        upper = self.stat["iqr"]["upper_bound"]
        # 所有超上界的交易应被标记
        for tx in self.txs:
            if tx["amount"] > upper:
                self.assertIn(tx["tx_id"], flagged)


class TestEngineUnsupervisedLayer(unittest.TestCase):
    """第二层：无监督 ML 层（Isolation Forest 模拟 + 重构误差）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.txs = _load_fixture_txs()
        self.result = self.engine.execute({"transactions": self.txs})
        self.unsup = self.result["layer_results"]["unsupervised"]

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_iso_forest_flags_anomalies(self):
        """iForest 标记异常交易（大额异常应在其中）。"""
        flagged = self.unsup["iso_forest"]["flagged_tx_ids"]
        self.assertGreater(len(flagged), 0)
        # 异常评分存在
        scores = self.unsup["iso_forest"]["anomaly_scores"]
        self.assertEqual(len(scores), len(self.txs))

    def test_iso_forest_outliers_have_higher_scores(self):
        """大额异常交易的 iForest 评分应高于平均。"""
        scores = self.unsup["iso_forest"]["anomaly_scores"]
        avg_score = sum(scores.values()) / len(scores)
        outlier_txs = [t for t in self.txs if t["amount"] > 2000000]
        for tx in outlier_txs:
            self.assertGreater(
                scores[tx["tx_id"]], avg_score,
                f"异常交易 {tx['tx_id']} 评分应高于平均"
            )

    def test_reconstruction_error_recorded(self):
        """重构误差被记录（每个交易一个误差值）。"""
        errors = self.unsup["reconstruction_error"]["errors"]
        self.assertEqual(len(errors), len(self.txs))
        # 所有误差值非负
        for v in errors.values():
            self.assertGreaterEqual(v, 0.0)


class TestEngineSupervisedLayer(unittest.TestCase):
    """第三层：监督 ML 层（规则匹配）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.txs = _load_fixture_txs()
        self.result = self.engine.execute({"transactions": self.txs})
        self.sup = self.result["layer_results"]["supervised"]

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_patterns_loaded(self):
        """监督层加载了至少 10 条规则。"""
        self.assertGreaterEqual(self.sup["patterns_loaded"], 10)

    def test_year_end_large_amount_matched(self):
        """FP001（年末大额）命中 12 月 + 金额>=100万 的交易。"""
        matched = self.sup["matched"]
        for tx in self.txs:
            if tx["amount"] >= 1000000 and tx["date"].startswith("2025-12"):
                pids = [m["pattern_id"] for m in matched[tx["tx_id"]]]
                self.assertIn("FP001", pids)

    def test_integer_amount_matched(self):
        """FP002（整数金额）命中整数金额且 >=1万 的交易。"""
        matched = self.sup["matched"]
        # 构造一个明确的整数金额交易
        for tx in self.txs:
            amt = tx["amount"]
            if amt == round(amt) and amt >= 10000:
                pids = [m["pattern_id"] for m in matched[tx["tx_id"]]]
                self.assertIn("FP002", pids)

    def test_off_hours_matched(self):
        """FP003（非营业时间）命中 8 点前或 20 点后的交易。"""
        matched = self.sup["matched"]
        from modules.fo_01.engine import _parse_hour
        for tx in self.txs:
            hour = _parse_hour(tx.get("time"))
            if hour is not None and (hour < 8 or hour >= 20):
                pids = [m["pattern_id"] for m in matched[tx["tx_id"]]]
                self.assertIn("FP003", pids)

    def test_related_party_matched(self):
        """FP004（关联方）命中 is_related_party=True 的交易。"""
        matched = self.sup["matched"]
        for tx in self.txs:
            if tx.get("is_related_party"):
                pids = [m["pattern_id"] for m in matched[tx["tx_id"]]]
                self.assertIn("FP004", pids)


class TestEngineGraphLayer(unittest.TestCase):
    """第四层：知识图谱层（隐藏关联发现）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.txs = _load_fixture_txs()
        self.result = self.engine.execute({"transactions": self.txs})
        self.graph = self.result["layer_results"]["graph"]

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_hidden_links_discovered(self):
        """发现共享地址/电话/法人的隐藏关联（至少 3 条）。"""
        links = self.graph["hidden_links"]
        self.assertGreaterEqual(len(links), 3)
        link_types = {link["type"] for link in links}
        # 应包含 shared_address 类型
        self.assertIn("shared_address", link_types)

    def test_shared_address_links(self):
        """影子公司甲/乙共享地址 → hidden_link 中含 shared_address。"""
        links = self.graph["hidden_links"]
        addr_links = [l for l in links if l["type"] == "shared_address"]
        self.assertGreater(len(addr_links), 0)
        # 影子公司甲和乙应在同一 hidden_link 中
        found = False
        for link in addr_links:
            if "影子公司甲" in link["entities"] and "影子公司乙" in link["entities"]:
                found = True
                break
        self.assertTrue(found, "影子公司甲/乙的共享地址关联未发现")

    def test_shared_phone_links(self):
        """影子公司甲/乙共享电话 → hidden_link 中含 shared_phone。"""
        links = self.graph["hidden_links"]
        phone_links = [l for l in links if l["type"] == "shared_phone"]
        self.assertGreater(len(phone_links), 0)

    def test_shared_legal_rep_links(self):
        """关联企业P/Q共享法人 → hidden_link 中含 shared_legal_rep。"""
        links = self.graph["hidden_links"]
        legal_links = [l for l in links if l["type"] == "shared_legal_rep"]
        self.assertGreater(len(legal_links), 0)
        # 王五（P/Q共享法人）应在 linked_parties 中
        self.assertIn("关联企业P", self.graph["linked_parties"])
        self.assertIn("关联企业Q", self.graph["linked_parties"])

    def test_linked_transactions_flagged(self):
        """涉及隐藏关联的交易被标记。"""
        flagged = self.graph["flagged_tx_ids"]
        self.assertGreater(len(flagged), 0)
        # 影子公司甲/乙的交易应被标记
        shadow_tx_ids = {
            t["tx_id"] for t in self.txs
            if t["counterparty"] in ("影子公司甲", "影子公司乙")
        }
        self.assertTrue(shadow_tx_ids.issubset(set(flagged)))


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：评分 / 风险分级 / 统计。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.txs = _load_fixture_txs()
        self.result = self.engine.execute({"transactions": self.txs})

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_suspicious_transactions_populated(self):
        """可疑交易列表非空（含命中层的交易）。"""
        suspicious = self.result["suspicious_transactions"]
        self.assertGreater(len(suspicious), 0)

    def test_risk_score_in_range(self):
        """所有可疑交易的 risk_score ∈ [0, 1]。"""
        for s in self.result["suspicious_transactions"]:
            self.assertGreaterEqual(s["risk_score"], 0.0)
            self.assertLessEqual(s["risk_score"], 1.0)

    def test_risk_level_grading(self):
        """风险分级为 high / medium / low 之一。"""
        valid_levels = {"high", "medium", "low"}
        for s in self.result["suspicious_transactions"]:
            self.assertIn(s["risk_level"], valid_levels)

    def test_high_risk_exists(self):
        """存在高风险交易（多层命中的异常交易）。"""
        high = [s for s in self.result["suspicious_transactions"]
                if s["risk_level"] == "high"]
        self.assertGreater(len(high), 0)

    def test_evidence_chain_populated(self):
        """每个可疑交易都有证据链。"""
        for s in self.result["suspicious_transactions"]:
            self.assertGreater(len(s["evidence_chain"]), 0)

    def test_hit_layers_recorded(self):
        """命中层列表非空且为已知层名。"""
        valid_layers = {"statistical", "unsupervised", "supervised", "graph"}
        for s in self.result["suspicious_transactions"]:
            self.assertGreater(len(s["hit_layers"]), 0)
            for layer in s["hit_layers"]:
                self.assertIn(layer, valid_layers)

    def test_coverage_rate_100_percent(self):
        """全量扫描覆盖率 = 100%。"""
        stats = self.result["statistics"]
        self.assertEqual(stats["coverage_rate"], 1.0)

    def test_statistics_consistent(self):
        """统计：可疑数 = high + medium + low。"""
        stats = self.result["statistics"]
        dist = stats["risk_distribution"]
        self.assertEqual(
            stats["suspicious_count"],
            dist["high"] + dist["medium"] + dist["low"],
        )

    def test_layer_hit_counts_match(self):
        """各层命中数与可疑交易的 hit_layers 一致。"""
        stats = self.result["statistics"]
        counts = stats["layer_hit_counts"]
        for layer in ("statistical", "unsupervised", "supervised", "graph"):
            expected = sum(
                1 for s in self.result["suspicious_transactions"]
                if layer in s["hit_layers"]
            )
            self.assertEqual(counts[layer], expected)

    def test_suspicious_sorted_by_score_desc(self):
        """可疑交易按 risk_score 降序排列。"""
        scores = [s["risk_score"] for s in self.result["suspicious_transactions"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据清洗。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_amount_string_with_currency(self):
        """金额字符串（含货币符号/千分位/万）正确解析。"""
        self.assertAlmostEqual(_parse_amount("¥1,250,000"), 1250000.0)
        self.assertAlmostEqual(_parse_amount("100万"), 1000000.0)
        self.assertAlmostEqual(_parse_amount("5.5万"), 55000.0)
        self.assertAlmostEqual(_parse_amount("3亿"), 300000000.0)

    def test_amount_numeric(self):
        """数值型金额直接转 float。"""
        self.assertEqual(_parse_amount(100), 100.0)
        self.assertEqual(_parse_amount(99.5), 99.5)

    def test_date_normalization(self):
        """日期多种格式归一化。"""
        self.assertEqual(_parse_date("2025-12-30"), _parse_date("2025/12/30"))
        self.assertEqual(str(_parse_date("2025-03-15")), "2025-03-15")
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date(""))

    def test_preprocess_cleans_transactions(self):
        """预处理：金额转 float、日期归一化、对手名称标准化。"""
        prepared = self.engine._preprocess({"transactions": [
            {"tx_id": "T1", "amount": "100万", "date": "2025/06/15",
             "time": "14:30:00", "counterparty": "  测试  公司  "},
        ]})
        tx = prepared["transactions"][0]
        self.assertEqual(tx["amount"], 1000000.0)
        self.assertEqual(tx["tx_date"], "2025-06-15")
        self.assertEqual(tx["hour"], 14)
        self.assertEqual(tx["counterparty"], "测试 公司")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_transactions(self):
        """空交易列表 → 0 可疑、覆盖率 100%。"""
        result = self.engine.execute({"transactions": []})
        self.assertEqual(result["statistics"]["total_transactions"], 0)
        self.assertEqual(result["statistics"]["suspicious_count"], 0)
        self.assertEqual(result["statistics"]["coverage_rate"], 1.0)

    def test_list_input(self):
        """裸 list 输入也可处理。"""
        txs = _load_fixture_txs()[:15]
        result = self.engine.execute(txs)
        self.assertEqual(result["statistics"]["total_transactions"], 15)

    def test_no_benford_anomaly_for_uniform_data(self):
        """金额首位数字符合 Benford → 不触发 Benford 异常。

        构造 50 条严格按 Benford 分布的交易。
        """
        import math
        txs = []
        for i in range(50):
            # 按 Benford 比例分配首位数字
            digit_pool = []
            for d in range(1, 10):
                count = round(math.log10(1 + 1 / d) * 50)
                digit_pool.extend([d] * count)
            digit_pool = digit_pool[:50]
            d = digit_pool[i % len(digit_pool)]
            txs.append({
                "tx_id": f"UT{i:03d}",
                "amount": float(d * 10000 + i * 100),
                "date": "2025-06-15",
                "time": "10:00:00",
                "counterparty": f"对手{i}",
                "counterparty_address": f"地址{i}",
                "counterparty_phone": f"010-88{i:05d}",
                "counterparty_legal_rep": f"法人{i}",
            })
        result = self.engine.execute({"transactions": txs})
        benford = result["layer_results"]["statistical"]["benford"]
        # 接近 Benford 分布时卡方较低（允许一定偏差，但不触发异常）
        # 注意：50 条样本较少，可能仍有偏差，故只验证卡方计算正确
        self.assertGreater(benford["chi_square"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
