"""[IA-05] engine 单测：AI 驱动管理建议书 —— BM25 检索 + Prompt 模板 + 质量评估。

LLMEngine 基于 PortableDB 持久化（suggestions/benchmarks 表），
对审计发现做问题分类 + Top-K 检索 + 三轮生成 + 质量评分。每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ia_05.engine import (
    LLMEngine, _bm25_score, _ngram_sim, _QUALITY_WEIGHTS,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> LLMEngine:
    db_path = tmp_path / "ia_05_engine.db"
    eng = LLMEngine(config={"db_path": str(db_path), **overrides})
    eng.setup()
    return eng


def _close(eng: LLMEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_suggestions(tmp_path):
    """setup 后 suggestions 含 3 条种子数据。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.suggestions) == 3
        ids = {s["id"] for s in eng.suggestions}
        assert ids == {"S001", "S002", "S003"}
    finally:
        _close(eng)


def test_model_avgdl_positive(tmp_path):
    """setup 后 avgdl > 0。"""
    eng = _make_engine(tmp_path)
    try:
        assert eng.avgdl > 0
    finally:
        _close(eng)


def test_suggestion_fields(tmp_path):
    """每条 suggestion 含必要字段。"""
    eng = _make_engine(tmp_path)
    try:
        for s in eng.suggestions:
            assert "id" in s and "industry" in s and "issue_type" in s
            assert "keywords" in s and "content" in s and "path" in s
            assert "impact" in s and "adoption_rate" in s
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 分类
# ----------------------------------------------------------------------
def test_classify_issue_types(tmp_path):
    """_classify 按关键词分类问题类型。"""
    eng = _make_engine(tmp_path)
    try:
        assert eng._classify("审批流程存在缺陷") == "流程缺陷"
        assert eng._classify("权限管理缺失") == "控制缺失"
        assert eng._classify("存在合规违规问题") == "合规违规"
        assert eng._classify("效率耗时重复手工") == "效率低下"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_extracts_finding(tmp_path):
    """preprocess 提取 finding 并保留 industry/issue_type/severity。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert prepared["finding"] == _sample()["finding"]
        assert prepared["industry"] == "制造业"
        assert prepared["issue_type"] == "流程缺陷"
        assert prepared["severity"] == "重要"
    finally:
        _close(eng)


def test_preprocess_defaults(tmp_path):
    """未指定 industry/severity 时使用默认值。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"finding": "测试发现"})
        assert prepared["industry"] == "制造业"
        assert prepared["severity"] == "一般"
    finally:
        _close(eng)


def test_preprocess_generates_query_tokens(tmp_path):
    """preprocess 从 finding 提取中文 query_tokens。

    NOTE tokenizer: re.findall(r"[\\u4e00-\\u9fffA-Za-z]+", ...) 将连续中文归为单个 token，
    故 "采购审批流程" → ["采购审批流程"] 而非拆分。此处验证 token 含期望子串。
    """
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"finding": "采购审批流程"})
        assert len(prepared["query_tokens"]) > 0
        assert any("采购" in t for t in prepared["query_tokens"])
    finally:
        _close(eng)


def test_preprocess_retrieves_references(tmp_path):
    """preprocess 检索 Top-K references 并按分数降序。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert len(prepared["references"]) > 0
        assert "score" in prepared["references"][0]
        scores = [r["score"] for r in prepared["references"]]
        assert scores == sorted(scores, reverse=True)
    finally:
        _close(eng)


def test_preprocess_string_input(tmp_path):
    """字符串输入自动转为 finding。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess("权限分离存在问题")
        assert prepared["finding"] == "权限分离存在问题"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 推理
# ----------------------------------------------------------------------
def test_infer_generates_framework(tmp_path):
    """infer 生成 framework（3 步建议方向）。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        result = eng._infer(prepared)
        assert len(result["framework"]) == 3
        assert any("建议方向" in step for step in result["framework"])
    finally:
        _close(eng)


def test_infer_generates_suggestions(tmp_path):
    """infer 生成 suggestions 列表含 content 和 implementation_path。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        result = eng._infer(prepared)
        assert len(result["suggestions"]) > 0
        for s in result["suggestions"]:
            assert "content" in s
            assert "implementation_path" in s
    finally:
        _close(eng)


def test_infer_generates_quantified_impacts(tmp_path):
    """infer 为每条 suggestion 生成量化影响。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        result = eng._infer(prepared)
        assert len(result["quantified_impacts"]) == len(result["suggestions"])
        for imp in result["quantified_impacts"]:
            assert "cost_saving" in imp
            assert "efficiency" in imp
            assert "risk_reduction" in imp
    finally:
        _close(eng)


def test_infer_no_references_generates_auto(tmp_path):
    """无匹配 references 时生成 auto 兜底建议。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"finding": "测试发现", "industry": "未知行业"})
        result = eng._infer(prepared)
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["source"] == "auto"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 后处理 / 质量评估
# ----------------------------------------------------------------------
def test_postprocess_quality_dimensions(tmp_path):
    """postprocess 生成 5 个质量维度。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        dims = result["quality"]["dimensions"]
        assert set(dims.keys()) == set(_QUALITY_WEIGHTS.keys())
        for v in dims.values():
            assert 0 <= v <= 100
    finally:
        _close(eng)


def test_postprocess_overall_score(tmp_path):
    """postprocess 计算 overall 加权总分。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        overall = result["quality"]["overall"]
        assert 0 <= overall <= 100
        dims = result["quality"]["dimensions"]
        weighted = sum(dims[k] * _QUALITY_WEIGHTS[k] for k in _QUALITY_WEIGHTS)
        assert abs(overall - round(weighted, 1)) < 0.5
    finally:
        _close(eng)


def test_postprocess_grade(tmp_path):
    """postprocess 根据 overall 给出 grade。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        overall = result["quality"]["overall"]
        grade = result["quality"]["grade"]
        if overall >= 80:
            assert grade == "可直接使用"
        elif overall >= 60:
            assert grade == "需小幅调整"
        else:
            assert grade == "需大幅修改"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 量化
# ----------------------------------------------------------------------
def test_quantify_by_issue_type(tmp_path):
    """_quantify 按 issue_type 产出不同影响维度。"""
    eng = _make_engine(tmp_path)
    try:
        proc = eng._quantify("审批流程问题", "流程缺陷", {"cost_saving": 100})
        assert proc["cost_saving"] == 150.0
        assert proc["efficiency"] == 0.4

        ctrl = eng._quantify("权限问题", "控制缺失", {"cost_saving": 100})
        assert ctrl["risk_reduction"] == 0.75

        eff = eng._quantify("效率低下", "效率低下", {"cost_saving": 100})
        assert eff["efficiency"] == 0.55
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------
def test_bm25_score():
    """BM25 对匹配 token 返回正分，无匹配返回 0。"""
    query = ["采购", "审批"]
    doc = ["采购", "审批", "流程", "效率"]
    assert _bm25_score(query, doc, 4.0) > 0
    assert _bm25_score(["测试"], doc, 4.0) == 0


def test_ngram_sim():
    """ngram 相似度：相同为 1，不同较低。"""
    assert _ngram_sim("采购审批", "采购审批") == 1.0
    assert _ngram_sim("采购审批", "权限控制") < 0.5


# ----------------------------------------------------------------------
# 端到端
# ----------------------------------------------------------------------
def test_execute_end_to_end(tmp_path):
    """execute 端到端：生成 framework + suggestions + quality。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "framework" in result
        assert "suggestions" in result
        assert "quality" in result
        assert "generated_at" in result
    finally:
        _close(eng)


def test_execute_empty_finding(tmp_path):
    """空 finding 不崩且产出有效质量分。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"finding": ""})
        assert "quality" in result
        assert result["quality"]["overall"] >= 0
    finally:
        _close(eng)


def test_execute_unknown_industry(tmp_path):
    """未知行业生成 auto 兜底建议。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"finding": "测试发现", "industry": "未知行业"})
        assert len(result["suggestions"]) >= 1
        assert result["suggestions"][0]["source"] == "auto"
    finally:
        _close(eng)
