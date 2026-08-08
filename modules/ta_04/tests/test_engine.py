"""[TA-04] engine 单测：转让定价文档生成 / PLI分析 / 功能风险 / 合规检查。

LLMEngine 基于 PortableDB 持久化（comparable_companies/tp_documents 表），
纯 stdlib 模板填充 + 可比分析。每个测试用 tmp_path 隔离 db，结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ta_04.engine import LLMEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> LLMEngine:
    eng = LLMEngine(config={"db_path": str(tmp_path / "ta_04_engine.db"), **overrides})
    eng.setup()
    return eng


def _close(eng: LLMEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_templates_and_metrics(tmp_path):
    """setup 后 model 含 doc_templates / pli_metrics / func_risk_dims。"""
    eng = _make_engine(tmp_path)
    try:
        assert "doc_templates" in eng.model
        assert "pli_metrics" in eng.model
        assert "func_risk_dims" in eng.model
        assert len(eng.model["pli_metrics"]) == 3
        assert "intro" in eng.model["doc_templates"]
    finally:
        _close(eng)


def test_db_tables_created(tmp_path):
    """setup 后 db 含 comparable_companies / tp_documents 两表。"""
    db_path = tmp_path / "ta_04_tables.db"
    eng = LLMEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"comparable_companies", "tp_documents"} <= tables
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_parses_enterprise_and_comparables(tmp_path):
    """预处理解析 enterprise + comparables + doc_type。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert prepared["enterprise"]["name"] == "示例科技有限公司"
        assert len(prepared["comparables"]) == 5
        assert prepared["doc_type"] == "同期资料"
        c = prepared["comparables"][0]
        assert c["company_id"] == "COMP-001"
        assert c["operating_margin"] == 0.05
    finally:
        _close(eng)


def test_preprocess_generates_id_if_missing(tmp_path):
    """无 company_id 时自动生成。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"comparables": [{"company_name": "X"}]})
        assert prepared["comparables"][0]["company_id"].startswith("COMP-")
    finally:
        _close(eng)


def test_preprocess_non_dict_raises(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng._preprocess("not a dict")
    finally:
        _close(eng)


def test_preprocess_skips_invalid_comparables(tmp_path):
    """数值字段无法解析的 comparables 被跳过。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"comparables": [
            {"company_name": "OK", "operating_margin": "bad"},
            {"company_name": "OK2", "roa": "not_a_number"},
        ]})
        assert len(prepared["comparables"]) == 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# PLI 分析
# ----------------------------------------------------------------------
def test_pli_analysis_computed(tmp_path):
    """PLI 分析计算 mean/median/q1/q3/iqr_range。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        pli = result["pli_analysis"]
        assert "operating_margin" in pli
        om = pli["operating_margin"]
        assert om["count"] == 5
        assert om["mean"] == 0.1
        assert om["median"] == 0.1
        assert om["q1"] == 0.08
        assert om["q3"] == 0.12
        assert om["iqr_range"] == [0.08, 0.12]
    finally:
        _close(eng)


def test_pli_insufficient_comparables_skipped(tmp_path):
    """不足 3 家可比公司时 PLI 不计算。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"enterprise": {"name": "X"}, "comparables": [
            {"operating_margin": 0.1}, {"operating_margin": 0.2}
        ]})
        assert len(result["pli_analysis"]) == 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 功能风险分析
# ----------------------------------------------------------------------
def test_func_risk_analysis_levels(tmp_path):
    """功能风险分析按覆盖率分级（高/中/低）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        fr = result["func_risk_profile"]
        # functions: 4/6=0.67 → 高
        assert fr["functions_performed"]["level"] == "高"
        assert fr["functions_performed"]["coverage"] == "4/6"
        # risks: 2/5=0.4 → 中
        assert fr["risks_assumed"]["level"] == "中"
        # assets: 3/4=0.75 → 高
        assert fr["assets_used"]["level"] == "高"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 四分位区间检查
# ----------------------------------------------------------------------
def test_interquartile_check_in_range(tmp_path):
    """企业 PLI 值在四分位区间内 → 不需调整。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        check = result["interquartile_check"]["operating_margin"]
        assert check["enterprise_value"] == 0.10
        assert check["in_interquartile_range"] is True
        assert check["adjustment_needed"] is False
    finally:
        _close(eng)


def test_interquartile_check_out_of_range(tmp_path):
    """企业 PLI 值超出四分位区间 → 需调整。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "enterprise": {"name": "X", "pli_values": {"operating_margin": 0.50}},
            "comparables": [
                {"operating_margin": 0.05}, {"operating_margin": 0.08},
                {"operating_margin": 0.10}, {"operating_margin": 0.12},
                {"operating_margin": 0.15},
            ],
        })
        check = result["interquartile_check"]["operating_margin"]
        assert check["in_interquartile_range"] is False
        assert check["adjustment_needed"] is True
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 合规检查
# ----------------------------------------------------------------------
def test_compliance_full_score(tmp_path):
    """5 家可比 + 3 PLI + 企业名 → 合规满分。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        comp = result["compliance"]
        assert comp["score"] == 100.0
        assert comp["status"] == "合规"
        assert all(c["passed"] for c in comp["checks"])
    finally:
        _close(eng)


def test_compliance_low_comparables_penalty(tmp_path):
    """可比公司 < 5 且 PLI < 2 → 扣 20+15=35 分。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"enterprise": {"name": "X"}, "comparables": [
            {"operating_margin": 0.1}, {"operating_margin": 0.2},
            {"operating_margin": 0.3}
        ]})
        comp = result["compliance"]
        # 3 comparables < 5 → -20；仅 1 PLI < 2 → -15；企业名 OK → 100-20-15=65
        assert comp["score"] == 65.0
        check = next(c for c in comp["checks"] if c["item"] == "可比公司数量")
        assert check["passed"] is False
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_doc_sections(tmp_path):
    """execute 返回 doc_sections（含 5 个章节）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "doc_sections" in result
        sections = result["doc_sections"]
        assert "intro" in sections
        assert "func_risk" in sections
        assert "comparability" in sections
        assert "method" in sections
        assert "adjustment" in sections
        assert "示例科技有限公司" in sections["intro"]
    finally:
        _close(eng)


def test_summary_aggregates(tmp_path):
    """summary 聚合 compliance_score / comparable_count / pli_count。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["compliance_score"] == 100.0
        assert s["comparable_count"] == 5
        assert s["pli_count"] == 3
        assert s["adjustment_needed"] == 0
        assert s["compliance_status"] == "合规"
    finally:
        _close(eng)


def test_postprocess_adds_failed_checks(tmp_path):
    """postprocess 在 summary 中添加 failed_checks。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"enterprise": {}, "comparables": []})
        assert "failed_checks" in result["summary"]
        assert len(result["summary"]["failed_checks"]) > 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_input(tmp_path):
    """空输入返回零计数 summary（不崩）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"enterprise": {}, "comparables": []})
        assert result["summary"]["comparable_count"] == 0
        assert result["summary"]["pli_count"] == 0
    finally:
        _close(eng)
