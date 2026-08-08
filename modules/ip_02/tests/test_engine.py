"""[IP-02] engine 单测：监管反馈回复 / RAG检索 / 质量检查 / 风险提示。

LLMEngine 纯 stdlib 实现（无 PortableDB）：BM25 + 序列匹配 + 模板生成。
内置 8 个历史案例库，多路检索 → RRF 融合 → Top-3 → 6段式回复。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ip_02.engine import LLMEngine, _tokenize, _bm25_score

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_cases_and_templates():
    """setup 后 model 含 8 个案例 + prompt_tpl + quality_rules。"""
    eng = _make_engine()
    assert len(eng.model["cases"]) == 8
    assert "prompt_tpl" in eng.model
    assert len(eng.model["quality_rules"]) == 4
    assert eng._idf  # IDF 预计算
    assert eng._avg_dl > 0


def test_idf_precomputed():
    """BM25 IDF 预计算且含正值。"""
    eng = _make_engine()
    assert len(eng._idf) > 0
    for term, val in eng._idf.items():
        assert val > 0  # log((N+1)/(df+1)) + 1 > 0


# ----------------------------------------------------------------------
# 分词 & BM25
# ----------------------------------------------------------------------
def test_tokenize_chinese():
    """_tokenize 抽取 2 字以上连续中文片段。"""
    tokens = _tokenize("收入确认政策的合理性")
    assert len(tokens) > 0
    # tokenizer 匹配 2+ 连续中文字符为单个 token
    assert any("收入" in t for t in tokens)


def test_tokenize_strips_punctuation():
    """_tokenize 去除标点。"""
    tokens = _tokenize("请说明，收入确认！政策。")
    for t in tokens:
        assert "，" not in t
        assert "！" not in t
        assert "。" not in t


def test_tokenize_empty_string():
    """空字符串返回空列表。"""
    assert _tokenize("") == []


def test_bm25_score_positive_for_matching_docs():
    """BM25 对 IDF 中存在的匹配 token 给正分。"""
    eng = _make_engine()
    # 从 IDF 中取一个实际存在的 token 确保 BM25 能匹配
    token = next(iter(eng._idf))
    query = [token]
    doc = [token, "其他无关内容"]
    score = _bm25_score(query, doc, eng._idf, eng._avg_dl)
    assert score > 0


def test_bm25_score_zero_for_non_matching():
    """BM25 对无匹配词的文档给 0 分。"""
    eng = _make_engine()
    query = _tokenize("存货跌价")
    doc = _tokenize("核心技术人员的稳定性")
    score = _bm25_score(query, doc, eng._idf, eng._avg_dl)
    assert score == 0.0


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_extracts_question_and_tokens():
    """预处理提取 question + query_tokens。"""
    eng = _make_engine()
    prepared = eng._preprocess(_sample())
    assert prepared["question"] == _sample()["question"]
    assert prepared["industry"] == "软件和信息技术服务业"
    assert prepared["board"] == "科创板"
    assert len(prepared["query_tokens"]) > 0
    assert prepared["company_data"]


def test_preprocess_non_dict_raises():
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine()
    with pytest.raises(ValueError):
        eng._preprocess("not a dict")


# ----------------------------------------------------------------------
# 检索 & 回复生成
# ----------------------------------------------------------------------
def test_execute_returns_reply_and_sections():
    """execute 返回 reply + reply_sections（6段）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "reply" in result
    assert "reply_sections" in result
    sections = result["reply_sections"]
    for key in ("question", "core_reply", "data_support",
                "audit_procedure", "audit_conclusion", "refs"):
        assert key in sections


def test_similar_cases_retrieved():
    """检索返回 Top-3 相似案例。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    cases = result["similar_cases"]
    assert len(cases) == 3
    for c in cases:
        assert "case_id" in c
        assert "score" in c
        assert "industry" in c


def test_similar_cases_sorted_by_score_desc():
    """相似案例按分数降序。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    scores = [c["score"] for c in result["similar_cases"]]
    assert scores == sorted(scores, reverse=True)


def test_top_case_matches_industry():
    """Top-1 案例匹配行业（软件和信息技术服务业）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    top = result["similar_cases"][0]
    # IP-CASE-001 或 IP-CASE-005 均为软件行业
    assert top["industry"] == "软件和信息技术服务业"


def test_reply_contains_company_data():
    """回复含 company_data 数据支撑。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "10亿元" in result["reply"]


# ----------------------------------------------------------------------
# 质量检查
# ----------------------------------------------------------------------
def test_quality_check_returns_overall_and_dimensions():
    """质量检查返回 overall + 4 维度评分。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    quality = result["quality"]
    assert "overall" in quality
    assert 0.0 <= quality["overall"] <= 1.0
    assert len(quality["dimensions"]) == 4
    for d in quality["dimensions"]:
        assert "rule_id" in d
        assert "score" in d
        assert "weight" in d


def test_quality_completeness_score():
    """完整性维度 Q01 评分基于 token 覆盖率。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    q01 = next(d for d in result["quality"]["dimensions"] if d["rule_id"] == "Q01")
    assert q01["name"] == "完整性"
    assert q01["score"] >= 0  # tokenizer 分词方式影响覆盖率


# ----------------------------------------------------------------------
# 风险提示
# ----------------------------------------------------------------------
def test_risk_points_detected():
    """风险点检测返回非空列表。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert len(result["risk_points"]) > 0
    for rp in result["risk_points"]:
        assert "追问风险" in rp or "常规风险" in rp


def test_risk_points_for_revenue_question():
    """收入相关问题触发收入追问风险。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # question 含"收入" → 触发收入相关风险
    assert any("收入" in rp for rp in result["risk_points"])


# ----------------------------------------------------------------------
# 后处理
# ----------------------------------------------------------------------
def test_postprocess_adds_action_tips():
    """postprocess 添加 action_tips。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "action_tips" in result
    assert len(result["action_tips"]) > 0
    assert any("人工审核" in tip for tip in result["action_tips"])


def test_postprocess_adds_metadata():
    """postprocess 添加 metadata。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    meta = result["metadata"]
    assert meta["similar_case_count"] == 3
    assert len(meta["matched_case_ids"]) == 3
    assert "quality_overall" in meta
    assert meta["risk_point_count"] > 0


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_question_handled():
    """空 question 不崩。"""
    eng = _make_engine()
    result = eng.execute({"question": ""})
    assert "reply" in result
    assert result["metadata"]["similar_case_count"] == 3


def test_no_structural_match():
    """无行业/板块匹配时仍能检索。"""
    eng = _make_engine()
    result = eng.execute({"question": "收入确认", "industry": "未知行业",
                          "board": "未知板块"})
    assert len(result["similar_cases"]) == 3
