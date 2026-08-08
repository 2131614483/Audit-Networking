"""[CO-06] pipeline 端到端单测：Pipeline.run() 全流程 + custom 生效。

unittest 风格（不依赖 pytest）。CO-06 engine 无 PortableDB，无需 tmp 目录隔离。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_06.pipeline import Pipeline
from modules.co_06.custom.custom_thresholds import apply_thresholds
from modules.co_06.custom.custom_rules import apply_custom_rules
from modules.co_06.custom.custom_formatter import format_output

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(**overrides) -> Pipeline:
    config = {
        "reporting_org": "测试报告机构",
        "reporter": "测试分析师",
        "contact": "13800000000",
    }
    config.update(overrides)
    return Pipeline(config=config)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def test_pipeline_run_with_sample(self):
        """用 sample_input.json 端到端跑通，输出含 SAR 报告结构。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-06")
        self.assertIn("report_id", output)
        self.assertIn("narrative_5w1h", output)
        self.assertIn("evidence_chain", output)

    def test_pipeline_regulator_info(self):
        """输出含监管机构信息。"""
        output = _make_pipeline().run(_load_sample())
        self.assertEqual(output["regulator"]["name"], "中国人民银行")
        self.assertEqual(output["regulator"]["template"], "可疑交易报告（中国央行）")
        self.assertEqual(output["regulator"]["submission_deadline"], "2025-06-20T08:00:00+00:00")

    def test_pipeline_risk_and_priority(self):
        """输出含风险等级与 SAR 优先级。"""
        output = _make_pipeline().run(_load_sample())
        self.assertEqual(output["risk"]["level"], "high")
        self.assertIn(output["risk"]["sar_priority"], ("critical", "high", "medium", "low"))
        self.assertTrue(output["risk"]["sar_priority_label"])

    def test_pipeline_transaction_details(self):
        """输出含交易明细字段。"""
        output = _make_pipeline().run(_load_sample())
        details = output["transaction_details"]
        self.assertIn("tx_amount", details)
        self.assertEqual(details["tx_amount"], 321300.0)
        self.assertIn("tx_currency", details)

    def test_pipeline_regulatory_fields(self):
        """输出含监管必填字段填充情况。"""
        output = _make_pipeline().run(_load_sample())
        reg = output["regulatory_fields"]
        self.assertGreater(reg["template_fields_count"], 0)
        self.assertGreaterEqual(reg["mandatory_fill_rate"], 0.0)
        self.assertIn("mandatory_fields", reg)


class TestPipelineCollect(unittest.TestCase):
    """_collect：多形态输入归一化。"""

    def test_collect_standard_alert(self):
        """标准结构（含 alert 键）原样透传。"""
        pipe = _make_pipeline()
        sample = _load_sample()
        collected = pipe._collect(sample)
        self.assertIn("alert", collected)
        self.assertEqual(collected["template_id"], "CN-PBOC")

    def test_collect_raw_alert(self):
        """裸告警（平铺字段）包装为 alert。"""
        pipe = _make_pipeline()
        raw = {"alert_id": "A1", "transactions": [], "risk_score": 30,
               "template_id": "UK-NCA"}
        collected = pipe._collect(raw)
        self.assertIn("alert", collected)
        self.assertEqual(collected["alert"]["alert_id"], "A1")
        self.assertEqual(collected["template_id"], "UK-NCA")

    def test_collect_split_input(self):
        """拆分输入（transactions + customer）组装为告警。"""
        pipe = _make_pipeline()
        split = {"transactions": [{"tx_id": "T1", "amount": 100}],
                 "customer": {"name": "测试"}}
        collected = pipe._collect(split)
        self.assertIn("alert", collected)
        self.assertEqual(collected["alert"]["customer"]["name"], "测试")

    def test_collect_string_input(self):
        """字符串输入转 raw_text。"""
        pipe = _make_pipeline()
        collected = pipe._collect("plain text")
        self.assertIn("raw_text", collected["alert"])


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def test_thresholds_assign_sar_priority(self):
        """apply_thresholds 设置 sar_priority。"""
        result = {"risk_score": 95, "risk_level": "high",
                  "submission_deadline": "2025-06-20T08:00:00+00:00"}
        out = apply_thresholds(result, {})
        self.assertEqual(out["sar_priority"], "critical")
        self.assertIn("applied_thresholds", out)

    def test_thresholds_low_score(self):
        """低分 → low 优先级。"""
        out = apply_thresholds({"risk_score": 20, "risk_level": "low"}, {})
        self.assertEqual(out["sar_priority"], "low")

    def test_custom_rules_large_amount_mandatory_filing(self):
        """交易总额 > 100万 → mandatory_filing=True。"""
        result = {
            "summary": {"tx_amount_total": 1500000, "related_accounts_count": 0,
                        "related_parties_count": 0},
            "suspicious_patterns": [],
            "conclusion": {"reasons": []},
            "attachments_suggested": [],
            "sar_priority": "medium",
        }
        out = apply_custom_rules(result, {})
        self.assertTrue(out["mandatory_filing"])
        self.assertTrue(any(f["rule"] == "large_amount_mandatory_filing" for f in out["rule_flags"]))

    def test_custom_rules_cross_border_escalation(self):
        """跨境模式 → cross_border_escalation=True 且优先级升级。"""
        result = {
            "summary": {"tx_amount_total": 50000, "related_accounts_count": 0,
                        "related_parties_count": 0},
            "suspicious_patterns": [{"code": "MONEY_LAUNDRY"}],
            "conclusion": {"reasons": []},
            "attachments_suggested": [],
            "sar_priority": "medium",
        }
        out = apply_custom_rules(result, {})
        self.assertTrue(out["cross_border_escalation"])
        self.assertEqual(out["sar_priority"], "high")

    def test_custom_rules_network_analysis(self):
        """关联方>=3 → network_analysis_required=True。"""
        result = {
            "summary": {"tx_amount_total": 50000, "related_accounts_count": 2,
                        "related_parties_count": 4},
            "suspicious_patterns": [],
            "conclusion": {"reasons": []},
            "attachments_suggested": [],
            "sar_priority": "low",
        }
        out = apply_custom_rules(result, {})
        self.assertTrue(out["network_analysis_required"])

    def test_pipeline_cross_border_flag_in_output(self):
        """端到端：样本含跨境模式 → 输出 cross_border_escalation=True。"""
        output = _make_pipeline().run(_load_sample())
        self.assertTrue(output["risk"]["cross_border_escalation"])
        self.assertTrue(output["risk"]["network_analysis_required"])

    def test_pipeline_evidence_chain_nonempty(self):
        """端到端：证据链非空。"""
        output = _make_pipeline().run(_load_sample())
        self.assertGreater(len(output["evidence_chain"]), 0)

    def test_pipeline_rule_flags_recorded(self):
        """端到端：rule_flags 记录触发的业务规则。"""
        output = _make_pipeline().run(_load_sample())
        rules = {f["rule"] for f in output["rule_flags"]}
        self.assertIn("cross_border_escalation", rules)
        self.assertIn("network_analysis_required", rules)


class TestPipelineFormatter(unittest.TestCase):
    """format_output：格式化输出结构。"""

    def test_format_output_invalid(self):
        """非法输入 → error 状态。"""
        out = format_output("not a dict")
        self.assertEqual(out["status"], "error")

    def test_format_output_structure(self):
        """格式化输出含全部顶层键。"""
        result = {
            "report_id": "SAR-1", "alert_id": "A1",
            "template": {"regulator": "央行", "name": "STR", "format": "HTML"},
            "submission_deadline": "2025-06-20",
            "risk_level": "high", "risk_score": 90,
            "sar_priority": "critical", "sar_priority_label": "紧急",
            "sar_priority_action": "24h",
            "narrative_5w1h": "叙事", "suspicious_patterns": [{"code": "X"}],
            "conclusion": {"verdict": "提交", "confidence": 0.9, "reasons": [], "suggested_actions": []},
            "template_fields": {"tx_amount": {"value": 100, "is_mandatory": True}},
            "report_quality": {"total_score": 85, "grade": "良好", "breakdown": {},
                               "mandatory_fill_rate": 90, "auto_fill_rate": 80},
            "output_note": "复核", "rule_flags": [], "attachments_suggested": [],
            "summary": {"tx_count": 1},
        }
        out = format_output(result)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["module"], "CO-06")
        self.assertEqual(out["risk"]["sar_priority"], "critical")
        self.assertIn("tx_amount", out["transaction_details"])
        self.assertIn("tx_amount", out["regulatory_fields"]["mandatory_fields"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
