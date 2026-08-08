"""[CO-03] pipeline 端到端单测：Pipeline.run() 全流程 + custom 生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(**overrides) -> Pipeline:
    config = {"threshold": {"sim_critical": 0.5, "sim_high": 0.3,
                            "sim_medium": 0.15}}
    config.update(overrides)
    return Pipeline(config=config)


_AML_CHANGE = (
    "本次反洗钱法修订强化了客户尽职调查(KYC)要求，新增受益所有权识别义务，"
    "要求金融机构加强可疑交易监控与报告，并提高对高风险客户和PEP的审查标准。"
)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def test_pipeline_update_programs_with_sample_input(self):
        """用 sample_input.json 端到端跑通 update_programs。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-03")
        self.assertEqual(output["change_type"], "minor")
        self.assertGreater(output["programs_updated"], 0)
        self.assertIn("updated_programs", output)
        self.assertIn("version_history", output)
        self.assertIn("change_log", output)

    def test_pipeline_version_history(self):
        """版本历史非空且含 old/new 版本。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        history = output["version_history"]
        self.assertIsInstance(history, list)
        self.assertGreater(len(history), 0)
        for h in history:
            self.assertIn("prog_id", h)
            self.assertIn("old_version", h)
            self.assertIn("new_version", h)

    def test_pipeline_change_log(self):
        """变更日志非空且含变更明细。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        log = output["change_log"]
        self.assertIsInstance(log, list)
        self.assertGreater(len(log), 0)
        for entry in log:
            self.assertIn("prog_id", entry)
            self.assertIn("change_count", entry)
            self.assertIn("changes", entry)

    def test_pipeline_analyze_change(self):
        """analyze_change 输出含受影响程序与优先级分布。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "action": "analyze_change",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
        })
        self.assertEqual(output["status"], "ok")
        self.assertIn("aml", output["affected_domains"])
        self.assertGreater(output["affected_program_count"], 0)
        self.assertIn("priority_distribution", output)
        self.assertIn("coverage_stats", output)

    def test_pipeline_get_status(self):
        """get_status 输出程序库状态。"""
        pipe = _make_pipeline()
        output = pipe.run({"action": "get_status"})
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["total_programs"], 12)
        self.assertIn("by_domain", output)
        self.assertIn("version_distribution", output)

    def test_pipeline_rollback(self):
        """先更新再回滚 → 回滚成功。"""
        pipe = _make_pipeline()
        pipe.run({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
            "affected_prog_ids": ["PROG-AML-001"],
        })
        output = pipe.run({
            "action": "rollback",
            "prog_id": "PROG-AML-001",
            "target_version": "1.0.0",
        })
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["rolled_back_to"], "1.0.0")
        self.assertEqual(output["rollback_status"], "success")

    def test_pipeline_string_input(self):
        """裸字符串法规变更可端到端跑通。"""
        pipe = _make_pipeline()
        output = pipe.run(_AML_CHANGE)
        self.assertEqual(output["status"], "ok")
        self.assertIn("affected_programs", output)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def test_thresholds_update_priority_assigned(self):
        """analyze_change → 每个受影响程序含 update_priority。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "action": "analyze_change",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
        })
        for p in output["affected_programs"]:
            self.assertIn("update_priority", p)
            self.assertIn(p["update_priority"],
                          ("critical", "high", "medium", "low"))
        self.assertIn("thresholds", output)

    def test_custom_rules_aml_mandatory(self):
        """AML 法规变更 → aml 程序标记 mandatory_update=True。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "action": "analyze_change",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
        })
        aml_programs = [p for p in output["affected_programs"]
                        if p["domain"] == "aml"]
        self.assertGreater(len(aml_programs), 0)
        for p in aml_programs:
            self.assertTrue(p["mandatory_update"])
        # custom_rule_flags 含 AML 提示
        flags = output["custom_rule_flags"]
        self.assertTrue(any("AML" in f for f in flags))

    def test_custom_rules_coverage_stats(self):
        """覆盖率统计含 coverage_rate / coverage_alert。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "action": "analyze_change",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
        })
        cov = output["coverage_stats"]
        self.assertIn("coverage_rate", cov)
        self.assertIn("coverage_alert", cov)
        self.assertIsInstance(cov["coverage_alert"], bool)

    def test_custom_rules_no_update_coverage_alert(self):
        """无关法规变更 → update_programs 触发覆盖率告警。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "action": "update_programs",
            "regulation_change": "本法规关于太空探索的规范",
            "regulation_title": "无关法规",
            "change_type": "minor",
        })
        self.assertEqual(output["programs_updated"], 0)
        self.assertTrue(output["coverage_stats"]["coverage_alert"])

    def test_pipeline_config_threshold_override(self):
        """自定义相似度阈值覆盖默认值。"""
        pipe = _make_pipeline(threshold={"sim_critical": 0.99, "sim_high": 0.8,
                                         "sim_medium": 0.5})
        output = pipe.run({
            "action": "analyze_change",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
        })
        self.assertEqual(output["thresholds"]["sim_critical"], 0.99)


if __name__ == "__main__":
    unittest.main(verbosity=2)
