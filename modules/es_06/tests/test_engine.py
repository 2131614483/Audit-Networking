"""[ES-06] engine 单测：AI-ESG 审计方法论自动生成（模板匹配 / 程序生成 / 证据清单 / 底稿）。

LLMEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * 模板库：按行业（制造业/金融业/其他）× 审计主题（GHG/能源/气候风险/通用ESG）
  * 程序生成：基础程序 + 额外要求扩展，每程序附 output / responsible_role
  * 底稿模板：分组结构 + 字段 + 公式建议
  * 质量自检：证据/程序非空校验 + 质量清单
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.es_06.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 方法论生成 / 模板匹配
# ----------------------------------------------------------------------
def test_manufacturing_carbon_matches_ghg_template():
    """制造业 + 碳排放目标 → GHG 排放审计模板。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A公司", "industry": "制造业", "audit_goal": "碳排放"}])
    m = result["methodologies"][0]
    assert m["subject"] == "GHG排放审计（制造业）"
    assert m["industry"] == "制造业"
    assert m["company"] == "A公司"


def test_finance_climate_matches_risk_template():
    """金融业 + 气候风险目标 → 气候风险审计模板。"""
    eng = _make_engine()
    result = eng.execute([{"company": "B银行", "industry": "金融业", "audit_goal": "气候风险"}])
    assert result["methodologies"][0]["subject"] == "气候相关财务风险审计（金融业）"


def test_unknown_industry_falls_back_to_general():
    """未知行业 → 回退到通用 ESG 审计模板。"""
    eng = _make_engine()
    result = eng.execute([{"company": "C公司", "industry": "农业", "audit_goal": "全面ESG"}])
    m = result["methodologies"][0]
    assert m["subject"] == "ESG通用审计程序"
    assert m["industry"] == "农业"


def test_methodology_structure():
    """方法论含 methodology_id / subject / audit_scope / audit_procedures / evidence_checklist 等关键字段。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for m in result["methodologies"]:
        assert "methodology_id" in m
        assert "subject" in m
        assert "company" in m
        assert "industry" in m
        assert "audit_scope" in m
        assert "audit_procedures" in m
        assert "evidence_checklist" in m
        assert "workpaper_template" in m
        assert "risk_register" in m
        assert "time_plan" in m
        assert "quality_checklist" in m
        assert "applicable_standards" in m


# ----------------------------------------------------------------------
# 程序 / 证据 / 底稿
# ----------------------------------------------------------------------
def test_procedures_have_output_and_role():
    """每个审计程序附 output 与 responsible_role。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    for p in result["methodologies"][0]["audit_procedures"]:
        assert "output" in p
        assert "responsible_role" in p
        assert p["responsible_role"] == "ESG审计组"


def test_extra_requirements_add_procedures():
    """extra_requirements 追加额外审计程序。"""
    eng = _make_engine()
    base = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    base_count = len(base["methodologies"][0]["audit_procedures"])
    extended = eng.execute([{
        "company": "A", "industry": "制造业", "audit_goal": "碳排放",
        "extra_requirements": ["供应链碳核查", "范围三排放估算"],
    }])
    ext_count = len(extended["methodologies"][0]["audit_procedures"])
    assert ext_count == base_count + 2


def test_scope_includes_standards():
    """audit_scope 包含适用标准。"""
    eng = _make_engine()
    result = eng.execute([{
        "company": "A", "industry": "制造业", "audit_goal": "碳排放",
        "standards": ["ISSB IFRS S2", "GRI 305"],
    }])
    scope = result["methodologies"][0]["audit_scope"]
    assert "ISSB IFRS S2" in scope
    assert "GRI 305" in scope


def test_workpaper_template_has_structure_and_fields():
    """workpaper_template 含 structure / fields / embedded_formulas。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    wp = result["methodologies"][0]["workpaper_template"]
    assert "structure" in wp
    assert "fields" in wp
    assert "embedded_formulas" in wp
    assert len(wp["fields"]) > 0
    assert len(wp["structure"]) > 0


def test_formula_suggestions_for_ghg_subject():
    """GHG 主题的方法论含 Scope1/Scope2 公式建议。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    formulas = result["methodologies"][0]["workpaper_template"]["embedded_formulas"]
    names = [f["name"] for f in formulas]
    assert any("Scope1" in n for n in names)
    assert any("Scope2" in n for n in names)


def test_evidence_checklist_categorized():
    """evidence_checklist 按类别（必需/推荐/验证）组织。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    ev = result["methodologies"][0]["evidence_checklist"]
    categories = {e["category"] for e in ev}
    assert "必需" in categories
    for e in ev:
        assert "items" in e
        assert len(e["items"]) > 0


# ----------------------------------------------------------------------
# 时间安排 / 风险 / 质量清单
# ----------------------------------------------------------------------
def test_time_plan_has_dates():
    """time_plan 每阶段含 start_date / end_date / days。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    for phase in result["methodologies"][0]["time_plan"]:
        assert "phase" in phase
        assert "days" in phase
        assert "start_date" in phase
        assert "end_date" in phase


def test_risk_register_has_mitigation():
    """risk_register 每项含 risk 与 mitigation。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    for r in result["methodologies"][0]["risk_register"]:
        assert "risk" in r
        assert "mitigation" in r


def test_quality_checklist_non_empty():
    """quality_checklist 非空，含检查项与方法。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    qc = result["methodologies"][0]["quality_checklist"]
    assert len(qc) > 0
    for c in qc:
        assert "check" in c
        assert "method" in c


# ----------------------------------------------------------------------
# 汇总 / 边界
# ----------------------------------------------------------------------
def test_summary_structure():
    """summary 含 total_methodologies / industries_covered / subjects_covered / avg_procedures。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["total_methodologies"] == 3
    assert len(s["industries_covered"]) == 3
    assert len(s["subjects_covered"]) == 3
    assert s["avg_procedures"] > 0
    assert s["avg_evidence_items"] > 0


def test_quality_flags_empty_for_valid_input():
    """合法模板生成的无证据/程序为空的质量告警。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["quality_flags"] == []


def test_empty_input_returns_empty_methodologies():
    """空输入返回空方法论列表。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["methodologies"] == []
    assert result["summary"]["total_methodologies"] == 0
    assert result["quality_flags"] == []


def test_list_input_multiple_methodologies():
    """list 输入多对象 → 多方法论。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert len(result["methodologies"]) == 3


def test_single_dict_input_wrapped():
    """单 dict 输入自动包装为列表。"""
    eng = _make_engine()
    result = eng.execute({"company": "A", "industry": "制造业", "audit_goal": "碳排放"})
    assert len(result["methodologies"]) == 1


def test_default_standards_when_not_specified():
    """未指定 standards 时默认 ISSB IFRS S1/S2。"""
    eng = _make_engine()
    result = eng.execute([{"company": "A", "industry": "制造业", "audit_goal": "碳排放"}])
    stds = result["methodologies"][0]["applicable_standards"]
    assert "ISSB IFRS S1" in stds
    assert "ISSB IFRS S2" in stds


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_setup_loads_templates_and_goal_map():
    """setup() 后加载行业模板库 + 目标映射。"""
    eng = _make_engine()
    assert "制造业" in eng.industry_templates
    assert "金融业" in eng.industry_templates
    assert "碳排放" in eng.goal_map
    assert eng.goal_map["碳排放"] == "GHG排放审计"
