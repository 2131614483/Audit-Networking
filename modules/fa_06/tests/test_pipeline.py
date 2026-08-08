"""[FA-06] pipeline 端到端单测：Pipeline.run() 全流程 + _collect 数据对齐 + 自定义层。

unittest 风格（不依赖 pytest），纯 stdlib。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_06.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_sample_input()
        self.output = self.pipe.run(self.sample)

    def test_run_status_ok(self):
        """输出 status=ok, module=FA-06。"""
        self.assertEqual(self.output["status"], "ok")
        self.assertEqual(self.output["module"], "FA-06")

    def test_difference_items_count(self):
        """差异明细项数 = 输入记录数（8）。"""
        self.assertEqual(
            len(self.output["difference_items"]), len(self.sample["items"])
        )

    def test_summary_complete(self):
        """summary 含各项分布与规则标记。"""
        s = self.output["summary"]
        self.assertEqual(s["total_items"], 8)
        self.assertIn("category_distribution", s)
        self.assertIn("severity_distribution", s)
        self.assertIn("materiality_distribution", s)
        self.assertIn("rule_flags", s)
        self.assertIn("thresholds", s)

    def test_fraud_items_in_high_risk(self):
        """舞弊风险项（CF003/CF008）出现在 high_risk_ids。"""
        ids = self.output["summary"]["high_risk_ids"]
        self.assertIn("CF003", ids)
        self.assertIn("CF008", ids)


class TestPipelineCollect(unittest.TestCase):
    """_collect：函证回函与账面数据对齐。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_merges_ledger(self):
        """ledger 账面数据按 item_id 合并进回函记录。"""
        collected = self.pipe._collect({
            "materiality": 50000,
            "confirmations": [
                {"item_id": "L1", "subject": "银行存款",
                 "reply_amount": 1200, "reply_text": "在途资金"},
            ],
            "ledger": {
                "L1": {"book_amount": 1000, "book_text": "账面余额"},
            },
        })
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0]["book_amount"], 1000)
        self.assertEqual(collected[0]["book_text"], "账面余额")
        self.assertEqual(collected[0]["materiality"], 50000)

    def test_collect_materiality_backfill(self):
        """记录未指定 materiality 时回填全局值。"""
        collected = self.pipe._collect({
            "materiality": 80000,
            "items": [
                {"item_id": "M1", "subject": "应收账款",
                 "book_amount": 100, "reply_amount": 90},
            ],
        })
        self.assertEqual(collected[0]["materiality"], 80000)

    def test_collect_list_input(self):
        """裸 list 输入直接作为记录列表。"""
        collected = self.pipe._collect([
            {"item_id": "X1", "subject": "银行存款",
             "book_amount": 100, "reply_amount": 100, "materiality": 10},
        ])
        self.assertEqual(len(collected), 1)
        self.assertEqual(collected[0]["item_id"], "X1")

    def test_collect_auto_item_id(self):
        """缺失 item_id 时自动生成 CF0001。"""
        collected = self.pipe._collect({
            "items": [{"subject": "其他", "book_amount": 1, "reply_amount": 1}],
        })
        self.assertEqual(collected[0]["item_id"], "CF0001")


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_sample_input()
        self.output = self.pipe.run(self.sample)

    def test_thresholds_materiality_grade(self):
        """每项被赋予 materiality_grade（material/immaterial/de_minimis）。"""
        valid = {"material", "immaterial", "de_minimis"}
        for it in self.output["difference_items"]:
            self.assertIn(it["materiality_grade"], valid)

    def test_thresholds_de_minimis_for_matching(self):
        """无差异项（CF007）分级为 de_minimis。"""
        items = {it["item_id"]: it for it in self.output["difference_items"]}
        self.assertEqual(items["CF007"]["materiality_grade"], "de_minimis")

    def test_rule_material_flag(self):
        """差异占账面 >10%（CF003 20%）→ is_material=True。"""
        items = {it["item_id"]: it for it in self.output["difference_items"]}
        self.assertTrue(items["CF003"]["is_material"])

    def test_rule_systemic_flag(self):
        """同科目多发差异（CF001/CF002 银行存款-工商银行）→ systemic_issue=True。"""
        items = {it["item_id"]: it for it in self.output["difference_items"]}
        self.assertTrue(items["CF001"]["systemic_issue"])
        self.assertTrue(items["CF002"]["systemic_issue"])

    def test_rule_aged_flag(self):
        """时间性差异 + 高危/大额（CF002）→ aged_item=True。"""
        items = {it["item_id"]: it for it in self.output["difference_items"]}
        self.assertTrue(items["CF002"]["aged_item"])

    def test_rule_flags_summary(self):
        """summary.rule_flags 含三类计数。"""
        rf = self.output["summary"]["rule_flags"]
        self.assertIn("material_flagged", rf)
        self.assertIn("systemic_flagged", rf)
        self.assertIn("aged_flagged", rf)
        self.assertGreater(rf["material_flagged"], 0)
        self.assertGreater(rf["systemic_flagged"], 0)


class TestPipelineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_empty_items(self):
        """空 items → status ok, 0 项。"""
        output = self.pipe.run({"items": [], "materiality": 50000})
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["summary"]["total_items"], 0)

    def test_custom_threshold_config(self):
        """自定义阈值配置生效（降低 material_amount 使小差异也判为 material）。"""
        pipe = Pipeline({
            "threshold": {"material_amount": 1000, "material_pct": 0.001},
        })
        output = pipe.run([
            {"item_id": "C1", "subject": "其他", "book_amount": 100000,
             "reply_amount": 100500, "book_text": "a", "reply_text": "b",
             "materiality": 50000},
        ])
        items = {it["item_id"]: it for it in output["difference_items"]}
        self.assertEqual(items["C1"]["materiality_grade"], "material")


if __name__ == "__main__":
    unittest.main(verbosity=2)
