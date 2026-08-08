"""[CB-03] engine 单测：倒排索引检索 / 多语言查询 / 合规问答 / 法规比对。

LLMEngine 为纯 stdlib 实现（倒排索引 + Jaccard + difflib），不依赖外部 LLM。
种子知识库含 GDPR/PIPL/CSL/CCPA/AMLD5/IFRS15 六部法规。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cb_03.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 倒排索引检索
# ----------------------------------------------------------------------
def test_search_returns_relevant_regulations():
    """搜索 GDPR 相关关键词，返回结果中 GDPR-001 排首位。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["summary"]["module"] == "CB-03"
    assert result["summary"]["family"] == "llm_rag"
    assert len(result["regulations"]) >= 1
    # GDPR-001 应该是 top-1（"gdpr" 精确命中 keywords_en）
    assert result["regulations"][0]["reg_id"] == "GDPR-001"
    assert result["regulations"][0]["score"] > 0
    assert "match_count" in result["regulations"][0]
    assert "jaccard" in result["regulations"][0]


def test_search_results_sorted_by_score_desc():
    """检索结果按 score 降序排列。"""
    eng = _make_engine()
    result = eng.execute({"query": "数据保护 个人信息", "action": "search"})
    scores = [r["score"] for r in result["regulations"]]
    assert scores == sorted(scores, reverse=True)


def test_search_top_k_limits_results():
    """top_k 限制返回结果数量。"""
    eng = _make_engine()
    result = eng.execute({"query": "数据", "action": "search", "top_k": 2})
    assert len(result["regulations"]) <= 2


def test_search_filters_by_jurisdiction():
    """按法域过滤：仅返回 EU 法规。"""
    eng = _make_engine()
    result = eng.execute({
        "query": "数据保护",
        "action": "search",
        "jurisdiction": "EU",
    })
    for r in result["regulations"]:
        assert r["jurisdiction"] == "EU"


def test_search_filters_by_category():
    """按分类过滤：仅返回 data_protection 分类。"""
    eng = _make_engine()
    result = eng.execute({
        "query": "数据",
        "action": "search",
        "category": "data_protection",
    })
    for r in result["regulations"]:
        assert r["category"] == "data_protection"


def test_search_no_match_returns_empty():
    """查询无匹配关键词时返回空法规列表 + 提示。"""
    eng = _make_engine()
    result = eng.execute({"query": "zzznomatchqqq", "action": "search"})
    assert result["regulations"] == []
    assert "note" in result


# ----------------------------------------------------------------------
# 多语言 / 同义词扩展
# ----------------------------------------------------------------------
def test_english_query_matches_keywords_en():
    """英文 query 能命中 keywords_en 索引（如 'GDPR'）。"""
    eng = _make_engine()
    result = eng.execute({"query": "GDPR privacy", "action": "search"})
    ids = {r["reg_id"] for r in result["regulations"]}
    assert "GDPR-001" in ids


def test_chinese_english_mixed_query():
    """中英混合 query 能检索到相关法规。"""
    eng = _make_engine()
    result = eng.execute({"query": "个人信息保护 PIPL", "action": "search"})
    ids = {r["reg_id"] for r in result["regulations"]}
    assert "PIPL-001" in ids


def test_string_input_treated_as_query():
    """字符串输入被当作 query（action 默认 search）。"""
    eng = _make_engine()
    result = eng.execute("反洗钱 AML")
    ids = {r["reg_id"] for r in result["regulations"]}
    assert "AMLD5-001" in ids


# ----------------------------------------------------------------------
# 合规问答（QA）
# ----------------------------------------------------------------------
def test_qa_returns_structured_answer():
    """qa 模式返回结构化回答 + 来源 + 置信度。"""
    eng = _make_engine()
    result = eng.execute({"query": "GDPR 数据跨境传输", "action": "qa"})
    assert "answer" in result
    assert len(result["answer"]) > 0
    assert "structured_requirements" in result
    assert len(result["structured_requirements"]) >= 1
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["sources"]


def test_qa_sources_include_score():
    """qa 的 sources 列表含 reg_id/title/score。"""
    eng = _make_engine()
    result = eng.execute({"query": "个人信息保护法", "action": "qa"})
    for src in result["sources"]:
        assert "reg_id" in src
        assert "title" in src
        assert "score" in src


def test_qa_no_match_returns_low_confidence():
    """qa 无匹配时返回 confidence=0 + 提示。"""
    eng = _make_engine()
    result = eng.execute({"query": "zzznomatchqqq", "action": "qa"})
    assert result["confidence"] == 0.0
    assert result["sources"] == []


# ----------------------------------------------------------------------
# 法规比对（compare）
# ----------------------------------------------------------------------
def test_compare_two_regulations_by_id():
    """compare 模式：指定 compare_with，自动找同分类法规对比。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "compare",
        "compare_with": "GDPR-001",
    })
    assert result["regulation_a"]["reg_id"] == "GDPR-001"
    assert "regulation_b" in result
    assert result["regulation_b"]["reg_id"] != "GDPR-001"
    # GDPR-001 是 data_protection，对比对象也应是同分类
    assert 0.0 <= result["keyword_similarity"] <= 1.0
    assert isinstance(result["common_keywords"], list)
    assert isinstance(result["unique_to_a"], list)
    assert isinstance(result["unique_to_b"], list)
    assert "comparison_summary" in result
    assert len(result["requirement_diff"]) >= 0


def test_compare_unknown_id_returns_message():
    """compare 未知法规 ID 时返回提示信息。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "compare",
        "compare_with": "NOT-EXIST",
    })
    assert "comparison" in result
    assert "未找到" in result["comparison"]


# ----------------------------------------------------------------------
# 空输入 / 边界
# ----------------------------------------------------------------------
def test_empty_query_returns_no_match():
    """空 query 返回未找到匹配。"""
    eng = _make_engine()
    result = eng.execute({"query": "", "action": "search"})
    assert result["regulations"] == []


def test_non_dict_non_string_input_coerced():
    """非 dict/str 输入被转为 query 字符串（不崩）。"""
    eng = _make_engine()
    result = eng.execute(12345)
    # 不抛异常即通过
    assert "regulations" in result


# ----------------------------------------------------------------------
# 汇总统计
# ----------------------------------------------------------------------
def test_summary_by_jurisdiction_and_category():
    """summary 含 by_jurisdiction / by_category 分布统计。"""
    eng = _make_engine()
    result = eng.execute({"query": "数据", "action": "search", "top_k": 10})
    s = result["summary"]
    assert s["total_results"] == len(result["regulations"])
    assert "by_jurisdiction" in s
    assert "by_category" in s


def test_model_has_seed_regulations():
    """engine 加载后 model 含 6 部种子法规 + 倒排索引。"""
    eng = _make_engine()
    assert len(eng.model["regulations"]) == 6
    assert len(eng.model["inverted_index"]) > 0
    assert "GDPR-001" in eng.model["reg_keywords"]
    # 法域字典
    assert "EU" in eng.model["jurisdictions"]
    assert "CN" in eng.model["jurisdictions"]
