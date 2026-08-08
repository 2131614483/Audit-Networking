"""[CO-02] pipeline 端到端单测：Pipeline.run() 全流程 + custom 生效。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_pipeline(**overrides) -> Pipeline:
    config = {"threshold": {"impact_high": 70, "impact_medium": 40,
                            "impact_critical": 90}}
    config.update(overrides)
    return Pipeline(config=config)


_REGULATION = (
    "第一条 本条例所称个人信息，是指以电子方式记录的自然人有关信息。"
    "第二条 企业应当取得个人同意方可处理个人信息。"
    "第三条 数据处理者不得过度收集个人信息。"
    "第四条 企业必须建立数据安全管理制度。"
    "第五条 大型企业违反规定的，处5000万元以下罚款。"
)


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def test_pipeline_run_with_sample_input(self):
        """用 sample_input.json 端到端跑通，输出含核心字段。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-02")
        for key in ("executive_summary", "regulation_analysis",
                    "gap_analysis", "impact_assessment", "remediation_plan"):
            self.assertIn(key, output)

    def test_pipeline_regulation_analysis(self):
        """法规分析含条款数 / 结构 / 处罚条款。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        reg = output["regulation_analysis"]
        self.assertEqual(reg["title"], "个人信息保护实施条例（示例）")
        self.assertEqual(reg["clause_count"], 8)
        self.assertIn("obligation", reg["structure"])
        self.assertGreater(reg["structure"]["obligation"], 0)
        self.assertGreater(len(reg["penalty_clauses"]), 0)

    def test_pipeline_gap_analysis(self):
        """差距分析含义务数 / 差距类型 / 差距率。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        gaps = output["gap_analysis"]
        self.assertGreater(gaps["total_obligations"], 0)
        self.assertIn("gaps_by_type", gaps)
        self.assertIsInstance(gaps["gap_rate"], (int, float))
        self.assertGreaterEqual(gaps["gap_rate"], 0)

    def test_pipeline_impact_assessment(self):
        """影响评估含评分 / 等级 / 成本估算。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        impact = output["impact_assessment"]
        self.assertIsInstance(impact["impact_score"], (int, float))
        self.assertGreaterEqual(impact["impact_score"], 0)
        self.assertLessEqual(impact["impact_score"], 100)
        self.assertIn(impact["overall_level"], ("high", "medium", "low"))
        self.assertIn("cost_estimation", impact)

    def test_pipeline_remediation_plan(self):
        """整改方案非空且每条含优先级。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        plan = output["remediation_plan"]
        self.assertGreater(len(plan), 0)
        for r in plan:
            self.assertIn("priority", r)
            self.assertIn("action_type", r)
            self.assertIn(r["priority"], ("high", "medium", "low"))

    def test_pipeline_executive_summary(self):
        """执行摘要含 module=CO-02 与整体影响等级。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        summary = output["executive_summary"]
        self.assertEqual(summary["module"], "CO-02")
        self.assertEqual(summary["regulation"], "个人信息保护实施条例（示例）")
        self.assertIn(summary["overall_impact_level"], ("high", "medium", "low"))

    def test_pipeline_string_input(self):
        """裸字符串法规文本可端到端跑通。"""
        pipe = _make_pipeline()
        output = pipe.run(_REGULATION)
        self.assertEqual(output["status"], "ok")
        self.assertGreater(output["regulation_analysis"]["clause_count"], 0)


class TestPipelineCustomization(unittest.TestCase):
    """custom_thresholds + custom_rules 生效。"""

    def test_thresholds_applied(self):
        """apply_thresholds 注入 thresholds 元信息与 requires_immediate_action。"""
        pipe = _make_pipeline()
        output = pipe.run(_load_sample_input())
        impact = output["impact_assessment"]
        self.assertIn("thresholds", impact)
        self.assertIn("impact_high", impact["thresholds"])
        self.assertIn("requires_immediate_action", impact)

    def test_custom_rules_critical_gap(self):
        """缺失义务 → severity=critical + critical_gap_count。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "regulation_text": _REGULATION,
            "enterprise": {"size": "large", "industry": "technology",
                           "existing_policies": []},
        })
        gaps = output["gap_analysis"]
        # 空政策 → 存在 missing 且标记为 critical
        self.assertGreater(gaps["critical_gaps"], 0)
        impact = output["impact_assessment"]
        self.assertGreater(impact["critical_gap_count"], 0)
        self.assertIsInstance(output["custom_rule_flags"], list)

    def test_custom_rules_penalty_risk(self):
        """处罚金额超阈值 → high_penalty_risk。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "regulation_text": _REGULATION,
            "enterprise": {"size": "medium", "industry": "all",
                           "existing_policies": []},
        })
        reg = output["regulation_analysis"]
        high_penalty = [p for p in reg["penalty_clauses"]
                        if p.get("high_penalty_risk")]
        self.assertGreater(len(high_penalty), 0)

    def test_custom_rules_level_escalation(self):
        """缺失义务 >= 3 → 整体影响升级为 high。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "regulation_text": _REGULATION,
            "enterprise": {"size": "medium", "industry": "all",
                           "existing_policies": []},
        })
        # _REGULATION 有 3 条义务，全部 missing → 升级
        self.assertEqual(output["impact_assessment"]["overall_level"], "high")
        self.assertTrue(output["impact_assessment"]["level_escalated"])

    def test_pipeline_parse_action(self):
        """parse 模式输出条款列表而非影响评估。"""
        pipe = _make_pipeline()
        output = pipe.run({
            "action": "parse",
            "regulation_text": _REGULATION,
            "regulation_title": "测试法规",
        })
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["module"], "CO-02")
        self.assertIn("clauses", output)
        self.assertNotIn("impact_assessment", output)

    def test_pipeline_config_threshold_override(self):
        """自定义阈值覆盖默认值。"""
        pipe = _make_pipeline(threshold={"impact_high": 999, "impact_medium": 500,
                                         "impact_critical": 999})
        output = pipe.run(_load_sample_input())
        impact = output["impact_assessment"]
        # 阈值极高 → 即使有差距也应判为 low（除非 custom_rules 升级）
        # 这里仅校验阈值被注入
        self.assertEqual(impact["thresholds"]["impact_high"], 999)


if __name__ == "__main__":
    unittest.main(verbosity=2)
