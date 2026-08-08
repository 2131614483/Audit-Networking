"""[FO-03] pipeline 端到端单测：Pipeline.run() 全流程 + _collect 数据归一化 + 自定义层。

unittest 风格（不依赖 pytest），纯 stdlib。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fo_03.pipeline import Pipeline

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
        """输出 status=ok, module=FO-03。"""
        self.assertEqual(self.output["status"], "ok")
        self.assertEqual(self.output["module"], "FO-03")

    def test_detections_count(self):
        """检测结果数 = 输入文档数（5）。"""
        self.assertEqual(
            len(self.output["detections"]), len(self.sample["documents"])
        )

    def test_summary_complete(self):
        """summary 含各项统计与规则标记。"""
        s = self.output["summary"]
        self.assertEqual(s["document_count"], 5)
        self.assertIn("total_signals", s)
        self.assertIn("high_risk_docs", s)
        self.assertIn("avg_risk_score", s)
        self.assertIn("overall_risk_level", s)
        self.assertIn("risk_grade_distribution", s)
        self.assertIn("category_counts", s)
        self.assertIn("rule_flags", s)
        self.assertIn("thresholds", s)

    def test_fraud_doc_high_risk_flag(self):
        """EMAIL001（隐瞒+虚列+挪用）→ high_risk_flag=True。"""
        dets = {d["doc_id"]: d for d in self.output["detections"]}
        self.assertTrue(dets["EMAIL001"]["high_risk_flag"])

    def test_clean_doc_low_grade(self):
        """CLEAN001（无舞弊信号）→ risk_grade=low。"""
        dets = {d["doc_id"]: d for d in self.output["detections"]}
        self.assertEqual(dets["CLEAN001"]["risk_grade"], "low")

    def test_thresholds_in_summary(self):
        """summary 含 thresholds（high=0.6, medium=0.3）。"""
        thr = self.output["summary"]["thresholds"]
        self.assertAlmostEqual(thr["high"], 0.6)
        self.assertAlmostEqual(thr["medium"], 0.3)


class TestPipelineCollect(unittest.TestCase):
    """_collect：文档数据归一化。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_collect_documents_key(self):
        """dict["documents"] 输入 → 归一化文档列表。"""
        collected = self.pipe._collect({
            "documents": [
                {"doc_id": "D1", "content": "测试", "title": "T", "doc_type": "邮件"},
            ],
        })
        self.assertEqual(len(collected["documents"]), 1)
        self.assertEqual(collected["documents"][0]["doc_id"], "D1")
        self.assertEqual(collected["documents"][0]["content"], "测试")

    def test_collect_texts_key(self):
        """dict["texts"] 输入 → 每条文本转为文档。"""
        collected = self.pipe._collect({"texts": ["文本一", "文本二"]})
        self.assertEqual(len(collected["documents"]), 2)
        self.assertEqual(collected["documents"][0]["content"], "文本一")

    def test_collect_list_input(self):
        """裸 list 输入直接作为文档列表。"""
        collected = self.pipe._collect([
            {"doc_id": "L1", "content": "测试"},
            "纯字符串文档",
        ])
        self.assertEqual(len(collected["documents"]), 2)
        self.assertEqual(collected["documents"][1]["content"], "纯字符串文档")

    def test_collect_string_element(self):
        """list 中字符串元素 → 转为 {content: str}。"""
        collected = self.pipe._collect(["纯文本"])
        self.assertEqual(collected["documents"][0]["content"], "纯文本")

    def test_collect_defaults(self):
        """缺失字段有默认值（title→空串, doc_type→文本）。"""
        collected = self.pipe._collect({"documents": [{"content": "x"}]})
        doc = collected["documents"][0]
        self.assertEqual(doc["title"], "")
        self.assertEqual(doc["doc_type"], "文本")


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_sample_input()
        self.output = self.pipe.run(self.sample)

    def test_risk_grade_assigned(self):
        """每个 detection 被赋予 risk_grade（high/medium/low）。"""
        valid = {"high", "medium", "low"}
        for det in self.output["detections"]:
            self.assertIn(det["risk_grade"], valid)

    def test_hedging_flag_for_memo(self):
        """MEMO001（模糊用语≥3次）→ suspicious_hedging=True。"""
        dets = {d["doc_id"]: d for d in self.output["detections"]}
        self.assertTrue(dets["MEMO001"]["suspicious_hedging"])

    def test_investigate_flag(self):
        """MEMO001（模糊用语+财务舞弊）→ investigate=True。"""
        dets = {d["doc_id"]: d for d in self.output["detections"]}
        self.assertTrue(dets["MEMO001"]["investigate"])

    def test_rule_flags_summary(self):
        """summary.rule_flags 含三类计数。"""
        rf = self.output["summary"]["rule_flags"]
        self.assertIn("high_risk_flagged", rf)
        self.assertIn("investigate_flagged", rf)
        self.assertIn("hedging_flagged", rf)
        self.assertGreaterEqual(rf["high_risk_flagged"], 1)

    def test_recommendations_populated(self):
        """被标记的文档有 recommendations。"""
        dets = {d["doc_id"]: d for d in self.output["detections"]}
        self.assertGreater(len(dets["EMAIL001"]["recommendations"]), 0)


class TestPipelinePersistence(unittest.TestCase):
    """PortableDB 持久化。"""

    def setUp(self):
        self.pipe = Pipeline()
        self.sample = _load_sample_input()
        self.output = self.pipe.run(self.sample)

    def test_results_persisted(self):
        """detection_results 表有 5 行。"""
        db = self.pipe.engine.db
        self.assertIn("detection_results", db.tables())
        rows = db.query("detection_results")
        self.assertEqual(len(rows), 5)

    def test_persisted_fields(self):
        """持久化行含 doc_id/risk_score/risk_grade/findings。"""
        db = self.pipe.engine.db
        row = db.get("detection_results", "doc_id = ?", ["EMAIL001"])
        self.assertIsNotNone(row)
        self.assertIn("risk_score", row)
        self.assertIn("risk_grade", row)
        self.assertIn("findings", row)
        self.assertIsInstance(row["findings"], list)


class TestPipelineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.pipe = Pipeline()

    def test_empty_documents(self):
        """空文档 → status ok, 0 文档。"""
        output = self.pipe.run({"documents": []})
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["summary"]["document_count"], 0)

    def test_custom_threshold_config(self):
        """自定义阈值配置生效（降低 high 阈值使中等风险也判为 high）。"""
        pipe = Pipeline({"threshold": {"high": 0.1, "medium": 0.05}})
        output = pipe.run({
            "documents": [
                {"doc_id": "C1", "content": "隐瞒收入"},
            ],
        })
        det = output["detections"][0]
        self.assertEqual(det["risk_grade"], "high")
        self.assertAlmostEqual(output["summary"]["thresholds"]["high"], 0.1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
