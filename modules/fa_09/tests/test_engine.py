"""[FA-09] engine 单测：五维度评分 / 加权计算 / 等级 / 问题发现 / 后处理。

unittest 风格（不依赖 pytest）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_09.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine():
    eng = LLMEngine()
    eng.setup()
    return eng


def _wp1():
    """高质量银行底稿。"""
    return _load_sample()["workpapers"][0]


def _wp2():
    """低质量应收账款底稿。"""
    return _load_sample()["workpapers"][1]


def _wp3():
    """中等质量存货底稿。"""
    return _load_sample()["workpapers"][2]


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：审计准则编译。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_standards_compiled(self):
        """_load_model 编译 5 条审计准则正则。"""
        self.assertEqual(len(self.engine._standards), 5)
        for name, pat in self.engine._standards:
            self.assertTrue(hasattr(pat, "search"))

    def test_weights_sum_to_one(self):
        """五维权重之和 = 1.0。"""
        self.assertAlmostEqual(sum(LLMEngine.WEIGHTS.values()), 1.0, places=4)

    def test_mandatory_fields_keys(self):
        """MANDATORY_FIELDS 含 bank/ar/inventory 等类型。"""
        for key in ("bank", "ar", "inventory", "revenue"):
            self.assertIn(key, LLMEngine.MANDATORY_FIELDS)

    def test_audit_standards_count(self):
        """AUDIT_STANDARDS 含 5 条准则。"""
        self.assertEqual(len(LLMEngine.AUDIT_STANDARDS), 5)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：底稿归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_dict_input_english_keys(self):
        """英文键 workpapers 正常解析。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        self.assertEqual(len(prepared["workpapers"]), 1)
        self.assertEqual(prepared["workpapers"][0]["wp_id"], "WP001")

    def test_dict_input_chinese_keys(self):
        """中文键 底稿 正常解析。"""
        prepared = self.engine._preprocess({"底稿": [_wp1()]})
        self.assertEqual(len(prepared["workpapers"]), 1)

    def test_list_input(self):
        """裸 list 输入包装为 workpapers。"""
        prepared = self.engine._preprocess([_wp1(), _wp2()])
        self.assertEqual(len(prepared["workpapers"]), 2)

    def test_none_input(self):
        """None 输入返回空 workpapers。"""
        prepared = self.engine._preprocess(None)
        self.assertEqual(prepared["workpapers"], [])

    def test_non_dict_wraps_as_workpapers(self):
        """非 dict 输入包装为 workpapers（非 dict 项被过滤为空列表）。"""
        prepared = self.engine._preprocess("raw_string")
        # engine 将非 dict 项 skip，最终为空列表
        self.assertEqual(prepared["workpapers"], [])

    def test_wp_id_generated_for_missing_id(self):
        """缺失 id/wp_id 时自动生成 md5 哈希 wp_id。"""
        prepared = self.engine._preprocess({"workpapers": [{"type": "bank"}]})
        wp_id = prepared["workpapers"][0]["wp_id"]
        self.assertEqual(len(wp_id), 8)


class TestEngineCompletenessScore(unittest.TestCase):
    """完整性维度评分。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_completeness_high_all_mandatory(self):
        """WP001 全部必填项命中 + 2 证据 → 100。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        wp = prepared["workpapers"][0]
        score = self.engine._completeness_score(wp)
        self.assertAlmostEqual(score, 100.0)

    def test_completeness_low_no_mandatory(self):
        """WP002 无必填项命中 + 0 证据 → 50。"""
        prepared = self.engine._preprocess({"workpapers": [_wp2()]})
        wp = prepared["workpapers"][0]
        score = self.engine._completeness_score(wp)
        self.assertAlmostEqual(score, 50.0)

    def test_completeness_all_mandatory_inventory(self):
        """WP003 全部必填项命中 + 3 证据 → 100。"""
        prepared = self.engine._preprocess({"workpapers": [_wp3()]})
        wp = prepared["workpapers"][0]
        score = self.engine._completeness_score(wp)
        self.assertAlmostEqual(score, 100.0)


class TestEngineAccuracyScore(unittest.TestCase):
    """准确性维度评分。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_accuracy_balanced(self):
        """WP001 借贷平衡 → 80。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        wp = prepared["workpapers"][0]
        score = self.engine._accuracy_score(wp)
        self.assertAlmostEqual(score, 80.0)

    def test_accuracy_unbalanced(self):
        """WP002 借贷不平 → 50。"""
        prepared = self.engine._preprocess({"workpapers": [_wp2()]})
        wp = prepared["workpapers"][0]
        score = self.engine._accuracy_score(wp)
        self.assertAlmostEqual(score, 50.0)


class TestEngineLogicScore(unittest.TestCase):
    """逻辑性维度评分。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_logic_with_conclusion(self):
        """WP001 有结论且程序匹配 → 75。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        wp = prepared["workpapers"][0]
        score = self.engine._logic_score(wp)
        self.assertAlmostEqual(score, 75.0)

    def test_logic_without_conclusion(self):
        """WP002 无结论 + 程序不匹配 → 40。"""
        prepared = self.engine._preprocess({"workpapers": [_wp2()]})
        wp = prepared["workpapers"][0]
        score = self.engine._logic_score(wp)
        self.assertAlmostEqual(score, 40.0)


class TestEngineComplianceScore(unittest.TestCase):
    """合规性维度评分。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_compliance_high_with_standards(self):
        """WP001 命中 4 条准则 → 90。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        wp = prepared["workpapers"][0]
        score = self.engine._compliance_score(wp)
        self.assertAlmostEqual(score, 90.0)

    def test_compliance_low_no_standards(self):
        """WP002 命中 0 条准则 → 50。"""
        prepared = self.engine._preprocess({"workpapers": [_wp2()]})
        wp = prepared["workpapers"][0]
        score = self.engine._compliance_score(wp)
        self.assertAlmostEqual(score, 50.0)

    def test_compliance_partial_standards(self):
        """WP003 命中 2 条准则 → 70。"""
        prepared = self.engine._preprocess({"workpapers": [_wp3()]})
        wp = prepared["workpapers"][0]
        score = self.engine._compliance_score(wp)
        self.assertAlmostEqual(score, 70.0)


class TestEngineQualityScore(unittest.TestCase):
    """表达质量维度评分。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_quality_clean_content(self):
        """WP001 内容规范 → 85。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        wp = prepared["workpapers"][0]
        score = self.engine._quality_score(wp)
        self.assertAlmostEqual(score, 85.0)


class TestEngineOverallScore(unittest.TestCase):
    """加权总分与等级。"""

    def setUp(self):
        self.engine = _make_engine()
        self.result = self.engine.execute({"workpapers": [_wp1(), _wp2(), _wp3()]})

    def test_overall_score_wp1(self):
        """WP001 加权总分 = 86.5。"""
        item = next(i for i in self.result["items"] if i["wp_id"] == "WP001")
        self.assertAlmostEqual(item["overall_score"], 86.5, places=1)

    def test_overall_score_wp2(self):
        """WP002 加权总分 = 51.5。"""
        item = next(i for i in self.result["items"] if i["wp_id"] == "WP002")
        self.assertAlmostEqual(item["overall_score"], 51.5, places=1)

    def test_overall_score_wp3(self):
        """WP003 加权总分 = 82.5。"""
        item = next(i for i in self.result["items"] if i["wp_id"] == "WP003")
        self.assertAlmostEqual(item["overall_score"], 82.5, places=1)

    def test_grade_wp1_is_b(self):
        """WP001 等级 = B。"""
        item = next(i for i in self.result["items"] if i["wp_id"] == "WP001")
        self.assertEqual(item["grade"], "B")

    def test_grade_wp2_is_f(self):
        """WP002 等级 = F。"""
        item = next(i for i in self.result["items"] if i["wp_id"] == "WP002")
        self.assertEqual(item["grade"], "F")

    def test_grade_wp3_is_b(self):
        """WP003 等级 = B。"""
        item = next(i for i in self.result["items"] if i["wp_id"] == "WP003")
        self.assertEqual(item["grade"], "B")

    def test_dimension_scores_all_present(self):
        """每个 item 含 5 个维度评分。"""
        for item in self.result["items"]:
            scores = item["dimension_scores"]
            for dim in ("completeness", "accuracy", "logic", "compliance", "quality"):
                self.assertIn(dim, scores)


class TestEngineIssues(unittest.TestCase):
    """问题发现逻辑。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_wp1_no_issues(self):
        """WP001 全维度 ≥ 75 → 无问题。"""
        prepared = self.engine._preprocess({"workpapers": [_wp1()]})
        wp = prepared["workpapers"][0]
        scores = self.engine._score_dimensions(wp)
        issues = self.engine._find_issues(wp, scores)
        self.assertEqual(len(issues), 0)

    def test_wp2_has_major_issues(self):
        """WP002 有 4 个 major 问题（评分 < 60）。"""
        prepared = self.engine._preprocess({"workpapers": [_wp2()]})
        wp = prepared["workpapers"][0]
        scores = self.engine._score_dimensions(wp)
        issues = self.engine._find_issues(wp, scores)
        self.assertEqual(len(issues), 4)
        for iss in issues:
            self.assertEqual(iss["severity"], "major")

    def test_wp3_has_minor_issue(self):
        """WP003 有 1 个 minor 问题（合规 70 < 75）。"""
        prepared = self.engine._preprocess({"workpapers": [_wp3()]})
        wp = prepared["workpapers"][0]
        scores = self.engine._score_dimensions(wp)
        issues = self.engine._find_issues(wp, scores)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "minor")
        self.assertEqual(issues[0]["dimension"], "compliance")


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：汇总。"""

    def setUp(self):
        self.engine = _make_engine()
        self.result = self.engine.execute({"workpapers": [_wp1(), _wp2(), _wp3()]})

    def test_summary_keys(self):
        """summary 含必要键。"""
        summary = self.result["summary"]
        for key in ("total_workpapers", "average_score", "grade_distribution",
                    "total_issues", "critical_issues_count", "major_issues_count"):
            self.assertIn(key, summary)

    def test_total_workpapers(self):
        """total_workpapers = 3。"""
        self.assertEqual(self.result["summary"]["total_workpapers"], 3)

    def test_average_score(self):
        """average_score = (86.5+51.5+82.5)/3 = 73.5。"""
        self.assertAlmostEqual(self.result["summary"]["average_score"], 73.5, places=1)

    def test_grade_distribution(self):
        """grade_distribution = {B:2, F:1}。"""
        dist = self.result["summary"]["grade_distribution"]
        self.assertEqual(dist.get("B"), 2)
        self.assertEqual(dist.get("F"), 1)

    def test_total_issues(self):
        """total_issues = 5 (WP2:4 + WP3:1)。"""
        self.assertEqual(self.result["summary"]["total_issues"], 5)

    def test_major_issues_count(self):
        """major_issues_count = 4。"""
        self.assertEqual(self.result["summary"]["major_issues_count"], 4)

    def test_critical_issues_empty(self):
        """sample 无 critical 问题（无评分 < 40）。"""
        self.assertEqual(self.result["summary"]["critical_issues_count"], 0)
        self.assertEqual(len(self.result["critical_issues"]), 0)

    def test_improvement_tips_populated(self):
        """improvement_tips 非空。"""
        self.assertGreater(len(self.result["improvement_tips"]), 0)


class TestEngineExecute(unittest.TestCase):
    """execute 全流程集成。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_execute_returns_dict(self):
        """execute 返回 dict 结构。"""
        result = self.engine.execute({"workpapers": [_wp1()]})
        self.assertIsInstance(result, dict)
        self.assertIn("items", result)
        self.assertIn("summary", result)

    def test_execute_sample_has_items(self):
        """sample 含 3 个底稿。"""
        result = self.engine.execute(_load_sample())
        self.assertEqual(len(result["items"]), 3)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_input(self):
        """空输入 → 0 底稿, average_score=0。"""
        result = self.engine.execute({})
        self.assertEqual(result["summary"]["total_workpapers"], 0)
        self.assertAlmostEqual(result["summary"]["average_score"], 0.0)

    def test_single_workpaper(self):
        """单个底稿正常处理。"""
        result = self.engine.execute({"workpapers": [_wp1()]})
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("overall_score", result["items"][0])

    def test_workpaper_no_amounts(self):
        """无 amounts 字段的底稿不报错。"""
        result = self.engine.execute({"workpapers": [{"id": "X1", "type": "bank"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_unknown_wp_type_defaults_to_bank(self):
        """未知 wp_type 使用 bank 的必填项。"""
        prepared = self.engine._preprocess({"workpapers": [{"id": "X1", "type": "unknown"}]})
        wp = prepared["workpapers"][0]
        score = self.engine._completeness_score(wp)
        self.assertGreaterEqual(score, 50.0)

    def test_compliance_rate_calculated(self):
        """compliance_rate 正确计算。"""
        result = self.engine.execute({"workpapers": [_wp1()]})
        item = result["items"][0]
        self.assertAlmostEqual(item["compliance_rate"], 0.8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
