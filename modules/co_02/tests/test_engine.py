"""[CO-02] engine 单测：法规语义解析 / 差距分析 / 影响量化 / 整改建议。

unittest 风格（不依赖 pytest）。CO-02 引擎无 PortableDB，无需 tmp 目录隔离。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_02.engine import (
    LLMEngine,
    _classify_clause,
    _extract_applicable,
    _extract_penalty,
    _split_clauses,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(**overrides) -> LLMEngine:
    config = {"threshold": {"impact_high": 70, "impact_medium": 40}}
    config.update(overrides)
    eng = LLMEngine(config=config)
    eng.setup()
    return eng


# 一段含义务/权利/定义/处罚的多类型法规文本
_SAMPLE_REG = (
    "第一条 本条例所称个人信息，是指以电子方式记录的自然人有关信息。"
    "第二条 处理个人信息应当遵循合法、正当原则。"
    "第三条 企业必须取得个人同意方可处理个人信息。"
    "第四条 数据处理者不得过度收集个人信息。"
    "第五条 个人有权查阅其个人信息。"
    "第六条 大型企业违反规定的，处5000万元以下罚款。"
)


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：词典 / 处罚模式 / 对标案例加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_model_loaded(self):
        """setup 后 self.model 非空且含核心键。"""
        self.assertIsNotNone(self.engine.model)
        for key in ("obligation_keywords", "right_keywords",
                    "penalty_patterns_zh", "applicable_entities",
                    "benchmark_cases"):
            self.assertIn(key, self.engine.model)

    def test_obligation_keywords_bilingual(self):
        """义务关键词含中英文。"""
        ob = self.engine.model["obligation_keywords"]
        self.assertIn("zh", ob)
        self.assertIn("en", ob)
        self.assertIn("应当", ob["zh"])
        self.assertIn("shall", ob["en"])

    def test_benchmark_cases_loaded(self):
        """对标案例至少 3 条。"""
        cases = self.engine.model["benchmark_cases"]
        self.assertGreaterEqual(len(cases), 3)

    def test_applicable_entities_categories(self):
        """适用对象含 enterprise / financial / individual / large_only。"""
        ents = self.engine.model["applicable_entities"]
        for cat in ("enterprise", "financial", "individual", "large_only"):
            self.assertIn(cat, ents)


class TestClauseClassification(unittest.TestCase):
    """条款分类：obligation / right / definition / other。"""

    def test_definition_clause(self):
        """含'是指' → definition。"""
        self.assertEqual(
            _classify_clause("本条例所称数据，是指以电子方式记录的信息"), "definition"
        )

    def test_obligation_clause_zh(self):
        """含'应当/必须/不得' → obligation。"""
        self.assertEqual(_classify_clause("企业应当取得同意"), "obligation")
        self.assertEqual(_classify_clause("企业必须建立制度"), "obligation")
        self.assertEqual(_classify_clause("不得过度收集数据"), "obligation")

    def test_right_clause(self):
        """含'有权/可以' → right。"""
        self.assertEqual(_classify_clause("个人有权查阅其信息"), "right")
        self.assertEqual(_classify_clause("当事人可以申请复议"), "right")

    def test_obligation_takes_priority_over_right(self):
        """同时含义务与权利关键词 → 义务优先（definition 先判，再 obligation）。"""
        # 不含定义词；含'应当'(义务)与'可以'(权利) → obligation
        self.assertEqual(
            _classify_clause("企业可以委托处理但应当履行监督"), "obligation"
        )

    def test_other_clause(self):
        """无关键词 → other。"""
        self.assertEqual(_classify_clause("本法规自2025年1月1日起施行"), "other")

    def test_definition_takes_priority(self):
        """含'是指'优先判定为 definition（即使含义务词）。"""
        self.assertEqual(
            _classify_clause("义务是指当事人应当履行的行为"), "definition"
        )


class TestPenaltyExtraction(unittest.TestCase):
    """处罚条款识别。"""

    def test_extract_penalty_zh_amount(self):
        """中文罚款金额提取。"""
        pen = _extract_penalty("处100万元以下罚款")
        self.assertIn("100", pen)
        self.assertIn("万", pen)

    def test_extract_penalty_large_amount(self):
        """大额罚款提取。"""
        pen = _extract_penalty("处5000万元以下或者上一年度营业额5%的罚款")
        self.assertIn("5000", pen)
        self.assertTrue(len(pen) > 0)

    def test_extract_penalty_empty(self):
        """无处罚文本返回空串。"""
        self.assertEqual(_extract_penalty("企业应当取得同意"), "")

    def test_extract_penalty_en(self):
        """英文罚款金额提取。"""
        pen = _extract_penalty("fine up to 20 million euro")
        self.assertTrue(len(pen) > 0)


class TestApplicableEntities(unittest.TestCase):
    """适用对象识别。"""

    def test_enterprise_detected(self):
        self.assertIn("enterprise", _extract_applicable("企业应当建立合规制度"))

    def test_financial_detected(self):
        self.assertIn("financial", _extract_applicable("银行应履行反洗钱义务"))

    def test_individual_detected(self):
        self.assertIn("individual", _extract_applicable("个人有权查阅其信息"))

    def test_large_only_detected(self):
        self.assertIn("large_only", _extract_applicable("大型企业应当披露报告"))

    def test_default_all(self):
        """无匹配对象 → ['all']。"""
        self.assertEqual(_extract_applicable("应当遵循合法原则"), ["all"])


class TestParseRegulation(unittest.TestCase):
    """_parse_regulation：条款切分与结构化。"""

    def setUp(self):
        self.engine = _make_engine()
        self.clauses = self.engine._parse_regulation(_SAMPLE_REG, "示例法规")

    def test_clauses_count(self):
        """6 个条款被切分（按。分割）。"""
        self.assertEqual(len(self.clauses), 6)

    def test_clause_ids_sequential(self):
        """条款 ID 顺序生成 C-001..C-006。"""
        ids = [c["clause_id"] for c in self.clauses]
        self.assertEqual(ids, ["C-001", "C-002", "C-003", "C-004", "C-005", "C-006"])

    def test_clause_types_distribution(self):
        """条款类型：1 definition / 3 obligation / 1 right / 1 other(含处罚)。"""
        types = [c["type"] for c in self.clauses]
        self.assertEqual(types[0], "definition")
        self.assertEqual(types.count("obligation"), 3)
        self.assertEqual(types.count("right"), 1)

    def test_clause_has_penalty_field(self):
        """每个条款含 penalty 字段（可能为空）。"""
        for c in self.clauses:
            self.assertIn("penalty", c)

    def test_penalty_clause_records_penalty(self):
        """第6条含处罚 → penalty 非空。"""
        penalty_clause = self.clauses[5]
        self.assertTrue(penalty_clause["penalty"])

    def test_clause_has_applicable_entities(self):
        """条款含 applicable_entities 列表。"""
        for c in self.clauses:
            self.assertIsInstance(c["applicable_entities"], list)
            self.assertGreater(len(c["applicable_entities"]), 0)

    def test_empty_text_returns_empty(self):
        """空法规文本 → 空条款列表。"""
        self.assertEqual(self.engine._parse_regulation("", "空"), [])

    def test_split_clauses_filters_short(self):
        """_split_clauses 过滤长度<=5 的片段。"""
        result = _split_clauses("ok。这是一个较长的条款内容。")
        self.assertTrue(all(len(s) > 5 for s in result))


class TestGapAnalysis(unittest.TestCase):
    """差距分析：missing / partial / covered。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_missing_gap_with_empty_policies(self):
        """企业无现有政策 → 所有义务为 missing。"""
        clauses = self.engine._parse_regulation(_SAMPLE_REG, "示例")
        gaps = self.engine._gap_analysis(clauses, {"existing_policies": []})
        self.assertGreater(gaps["total_obligations"], 0)
        self.assertEqual(gaps["gaps_by_type"].get("missing", 0), gaps["total_obligations"])
        self.assertEqual(gaps["gap_rate"], 100.0)

    def test_covered_gap_with_matching_policy(self):
        """现有政策与义务条款高度重叠 → covered。"""
        clause_text = "企业应当取得个人同意方可处理个人信息"
        clauses = [{"clause_id": "C-001", "text": clause_text, "type": "obligation"}]
        enterprise = {"existing_policies": [
            "企业应当取得个人同意方可处理个人信息，建立同意管理流程"
        ]}
        gaps = self.engine._gap_analysis(clauses, enterprise)
        self.assertEqual(gaps["details"][0]["gap_type"], "covered")

    def test_partial_gap_with_low_overlap(self):
        """现有政策与义务关键词重叠低 → partial。"""
        clause_text = "数据处理者不得收集与提供服务无关的个人信息"
        clauses = [{"clause_id": "C-001", "text": clause_text, "type": "obligation"}]
        enterprise = {"existing_policies": ["公司制定了数据访问权限管理办法"]}
        gaps = self.engine._gap_analysis(clauses, enterprise)
        self.assertIn(gaps["details"][0]["gap_type"], ("partial", "missing"))

    def test_gap_details_fields(self):
        """差距详情含必要字段。"""
        clauses = self.engine._parse_regulation(_SAMPLE_REG, "示例")
        gaps = self.engine._gap_analysis(clauses, {"existing_policies": []})
        for g in gaps["details"]:
            self.assertIn("clause_id", g)
            self.assertIn("gap_type", g)
            self.assertIn("confidence", g)
            self.assertIn("semantic_similarity", g)
            self.assertIn("keyword_coverage", g)
            self.assertIn("gap_detail", g)

    def test_gap_rate_calculation(self):
        """gap_rate = (missing+partial)/total*100。"""
        clauses = self.engine._parse_regulation(_SAMPLE_REG, "示例")
        gaps = self.engine._gap_analysis(clauses, {"existing_policies": []})
        by_type = gaps["gaps_by_type"]
        total = gaps["total_obligations"]
        expected_rate = round(
            (by_type.get("missing", 0) + by_type.get("partial", 0))
            / max(total, 1) * 100, 1
        )
        self.assertEqual(gaps["gap_rate"], expected_rate)


class TestImpactQuantification(unittest.TestCase):
    """影响量化：评分 / 等级 / 成本估算。"""

    def setUp(self):
        self.engine = _make_engine()
        self.clauses = self.engine._parse_regulation(_SAMPLE_REG, "示例")
        self.gaps = self.engine._gap_analysis(
            self.clauses, {"existing_policies": []}
        )

    def test_impact_score_in_range(self):
        """影响分 ∈ [0, 100]。"""
        impact = self.engine._quantify_impact(
            self.clauses, self.gaps, {"size": "large", "industry": "technology"}
        )
        self.assertGreaterEqual(impact["impact_score"], 0)
        self.assertLessEqual(impact["impact_score"], 100)

    def test_impact_level_grading(self):
        """等级为 high/medium/low 之一。"""
        impact = self.engine._quantify_impact(
            self.clauses, self.gaps, {"size": "large", "industry": "technology"}
        )
        self.assertIn(impact["overall_level"], ("high", "medium", "low"))

    def test_high_risk_for_large_fintech_with_gaps(self):
        """大型金融/科技企业 + 多缺失 + 处罚条款 → high。"""
        impact = self.engine._quantify_impact(
            self.clauses, self.gaps,
            {"size": "large", "industry": "finance"},
        )
        self.assertEqual(impact["overall_level"], "high")

    def test_cost_estimation_fields(self):
        """成本估算含 effort_months / required_team_size / primary_systems_affected。"""
        impact = self.engine._quantify_impact(
            self.clauses, self.gaps, {"size": "large", "industry": "all"}
        )
        cost = impact["cost_estimation"]
        self.assertIn("effort_months", cost)
        self.assertIn("required_team_size", cost)
        self.assertIn("primary_systems_affected", cost)

    def test_affected_systems_data_related(self):
        """法规含'数据/个人信息' → 受影响系统含'数据管理系统'。"""
        systems = LLMEngine._affected_systems(self.clauses)
        self.assertIn("数据管理系统", systems)

    def test_penalty_clauses_counted(self):
        """含处罚条款 → high_risk_clauses >= 1。"""
        impact = self.engine._quantify_impact(
            self.clauses, self.gaps, {"size": "medium", "industry": "all"}
        )
        self.assertGreaterEqual(impact["high_risk_clauses"], 1)


class TestRecommendations(unittest.TestCase):
    """整改建议生成。"""

    def setUp(self):
        self.engine = _make_engine()
        self.clauses = self.engine._parse_regulation(_SAMPLE_REG, "示例")
        self.gaps = self.engine._gap_analysis(
            self.clauses, {"existing_policies": []}
        )
        self.impact = self.engine._quantify_impact(
            self.clauses, self.gaps, {"size": "large", "industry": "technology"}
        )

    def test_recommendations_non_empty(self):
        """存在缺失义务 → 生成整改建议。"""
        recs = self.engine._generate_recommendations(
            self.gaps, self.impact, {"size": "large"}
        )
        self.assertGreater(len(recs), 0)

    def test_missing_gap_yields_high_priority(self):
        """缺失义务 → high 优先级 create_new_policy（至少一条）。"""
        recs = self.engine._generate_recommendations(
            self.gaps, self.impact, {"size": "large"}
        )
        high_create = [
            r for r in recs
            if r["priority"] == "high" and r["action_type"] == "create_new_policy"
        ]
        self.assertGreater(len(high_create), 0)
        # 所有缺失义务对应的建议均为 high 优先级
        for g in self.gaps["details"]:
            if g["gap_type"] == "missing":
                matched = [r for r in recs
                           if r["clause_id"] == g["clause_id"]
                           and r["priority"] == "high"]
                self.assertGreater(len(matched), 0)

    def test_system_upgrade_recommendation(self):
        """影响评估含受影响系统 → 生成系统升级建议。"""
        recs = self.engine._generate_recommendations(
            self.gaps, self.impact, {"size": "large"}
        )
        sys_recs = [r for r in recs if r["action_type"] == "system_upgrade"]
        self.assertGreater(len(sys_recs), 0)

    def test_recommendations_sorted_by_priority(self):
        """整改建议按优先级排序（high → medium → low）。"""
        recs = self.engine._generate_recommendations(
            self.gaps, self.impact, {"size": "large"}
        )
        order = {"high": 0, "medium": 1, "low": 2}
        priorities = [order[r["priority"]] for r in recs]
        self.assertEqual(priorities, sorted(priorities))


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入标准化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_string_input_normalized(self):
        """裸字符串 → action=assess, regulation_text=字符串。"""
        prepared = self.engine._preprocess("某法规文本内容")
        self.assertEqual(prepared["action"], "assess")
        self.assertEqual(prepared["regulation_text"], "某法规文本内容")
        self.assertEqual(prepared["regulation_title"], "")

    def test_dict_input_preserved(self):
        """dict 输入字段保留。"""
        prepared = self.engine._preprocess({
            "action": "parse",
            "regulation_text": "文本",
            "regulation_title": "标题",
            "enterprise": {"industry": "finance"},
        })
        self.assertEqual(prepared["action"], "parse")
        self.assertEqual(prepared["regulation_title"], "标题")
        self.assertEqual(prepared["enterprise"]["industry"], "finance")

    def test_defaults_filled(self):
        """缺失字段补默认值。"""
        prepared = self.engine._preprocess({})
        self.assertEqual(prepared["action"], "assess")
        self.assertEqual(prepared["regulation_text"], "")
        self.assertEqual(prepared["enterprise"], {})


class TestEngineExecute(unittest.TestCase):
    """execute 全流程（assess / parse 模式）。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_execute_assess_full_output(self):
        """assess 模式输出含核心字段。"""
        result = self.engine.execute({
            "regulation_text": _SAMPLE_REG,
            "regulation_title": "示例法规",
            "enterprise": {"size": "large", "industry": "technology",
                           "existing_policies": []},
        })
        for key in ("regulation_title", "clause_count", "regulation_structure",
                    "key_obligations", "gap_analysis", "impact_assessment",
                    "recommendations", "executive_summary"):
            self.assertIn(key, result)

    def test_execute_parse_mode(self):
        """parse 模式仅返回条款结构。"""
        result = self.engine.execute({
            "action": "parse",
            "regulation_text": _SAMPLE_REG,
            "regulation_title": "示例法规",
        })
        self.assertIn("clauses", result)
        self.assertNotIn("gap_analysis", result)
        self.assertEqual(len(result["clauses"]), 6)

    def test_executive_summary_module(self):
        """执行摘要含 module=CO-02。"""
        result = self.engine.execute({"regulation_text": _SAMPLE_REG})
        self.assertEqual(result["executive_summary"]["module"], "CO-02")

    def test_execute_empty_text(self):
        """空法规文本 → clause_count=0。"""
        result = self.engine.execute({"regulation_text": "", "enterprise": {}})
        self.assertEqual(result["clause_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
