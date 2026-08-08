"""[ES-05] engine 单测：ESG 审计知识库 RAG 问答（意图识别 / 检索 / 重排 / 生成 / 置信度）。

LLMEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * 知识库：ISSB / CSRD / GRI / SASB / TCFD + 方法论 + 审计案例
  * 检索：倒排索引 + BM25 + 语义相似度 → RRF 融合重排
  * 意图：comparison / procedure / definition / case / standard / general
  * 生成：基于模板填充 + 证据链 + 反幻觉校验
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.es_05.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 问答结果结构
# ----------------------------------------------------------------------
def test_answer_returned_for_relevant_query():
    """查询 Scope1 排放返回非空 answer + 证据列表。"""
    eng = _make_engine()
    result = eng.execute([{"query": "什么是Scope1直接排放", "top_k": 3}])
    ans = result["answers"][0]
    assert ans["answer"]
    assert len(ans["evidence"]) >= 1
    assert ans["intent"] == "definition"


def test_answer_structure():
    """每个答案含 query / intent / answer / evidence / confidence / confidence_label。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["answers"]:
        assert "query" in a
        assert "intent" in a
        assert "answer" in a
        assert "evidence" in a
        assert "confidence" in a
        assert "confidence_label" in a
        assert "kb_version" in a


def test_evidence_structure():
    """evidence 每项含 kb_id / title / standard / relevance_score。"""
    eng = _make_engine()
    result = eng.execute([{"query": "Scope1排放", "top_k": 3}])
    for ev in result["answers"][0]["evidence"]:
        assert "kb_id" in ev
        assert "title" in ev
        assert "standard" in ev
        assert "relevance_score" in ev
        assert 0.0 <= ev["relevance_score"] <= 1.0


def test_confidence_in_range():
    """confidence ∈ [0,1]。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["answers"]:
        assert 0.0 <= a["confidence"] <= 1.0


# ----------------------------------------------------------------------
# 意图识别
# ----------------------------------------------------------------------
def test_intent_definition():
    """含「什么是」→ definition。"""
    eng = _make_engine()
    result = eng.execute([{"query": "什么是双重重要性"}])
    assert result["answers"][0]["intent"] == "definition"


def test_intent_procedure():
    """含「步骤/程序」→ procedure。"""
    eng = _make_engine()
    result = eng.execute([{"query": "GHG排放审计程序步骤"}])
    assert result["answers"][0]["intent"] == "procedure"


def test_intent_comparison():
    """含「区别」→ comparison。"""
    eng = _make_engine()
    result = eng.execute([{"query": "Scope1和Scope2的区别"}])
    assert result["answers"][0]["intent"] == "comparison"


def test_intent_general_when_no_keyword():
    """无意图关键词 → general。"""
    eng = _make_engine()
    result = eng.execute([{"query": "碳排放"}])
    assert result["answers"][0]["intent"] == "general"


# ----------------------------------------------------------------------
# 检索 / 过滤 / top_k
# ----------------------------------------------------------------------
def test_top_k_limits_evidence_count():
    """top_k 限制返回的证据条数。"""
    eng = _make_engine()
    result = eng.execute([{"query": "排放", "top_k": 1}])
    assert len(result["answers"][0]["evidence"]) <= 1


def test_standard_filter_narrows_results():
    """filter.standard 限定只返回该标准的证据。"""
    eng = _make_engine()
    result = eng.execute([{"query": "Scope1排放", "top_k": 5, "filters": {"standard": "ISSB IFRS S2"}}])
    for ev in result["answers"][0]["evidence"]:
        assert ev["standard"] == "ISSB IFRS S2"


def test_evidence_sorted_by_relevance_desc():
    """证据按 relevance_score 降序排列。"""
    eng = _make_engine()
    result = eng.execute([{"query": "排放", "top_k": 5}])
    scores = [ev["relevance_score"] for ev in result["answers"][0]["evidence"]]
    assert scores == sorted(scores, reverse=True)


# ----------------------------------------------------------------------
# 兜底 / 空检索
# ----------------------------------------------------------------------
def test_fallback_for_no_match():
    """无匹配的查询返回兜底答案 + 空证据 + 低置信度。"""
    eng = _make_engine()
    result = eng.execute([{"query": "zzzqqqxxx无匹配关键词"}])
    a = result["answers"][0]
    assert a["evidence"] == []
    assert a["confidence"] <= 0.5
    assert "暂未检索到" in a["answer"] or "抱歉" in a["answer"]


# ----------------------------------------------------------------------
# 输入形态 / 边界
# ----------------------------------------------------------------------
def test_string_query_wrapped():
    """字符串查询自动包装为 {query: ...}。"""
    eng = _make_engine()
    result = eng.execute(["什么是Scope1排放"])
    assert len(result["answers"]) == 1
    assert result["answers"][0]["query"] == "什么是Scope1排放"


def test_list_input_multiple_queries():
    """list 输入多查询 → 多答案。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert len(result["answers"]) == 3


def test_empty_input_returns_empty_answers():
    """空查询列表返回空答案。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["answers"] == []
    assert result["kb_size"] == len(eng.kb)


# ----------------------------------------------------------------------
# 后处理 / 汇总
# ----------------------------------------------------------------------
def test_postprocess_structure():
    """后处理输出含 answers / intent_distribution / needs_human_review / kb_size。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "answers" in result
    assert "intent_distribution" in result
    assert "needs_human_review" in result
    assert "kb_size" in result
    assert result["kb_size"] == len(eng.kb)


def test_intent_distribution_aggregates():
    """intent_distribution 按意图计数。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    dist = result["intent_distribution"]
    assert sum(dist.values()) == 3
    assert "definition" in dist or "procedure" in dist


def test_needs_human_review_filters_low_confidence():
    """needs_human_review 仅含 confidence < 0.5 的答案。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["needs_human_review"]:
        assert a["confidence"] < 0.5


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_setup_loads_kb_and_index():
    """setup() 后加载知识库 + 倒排索引 + 同义词 + idf。"""
    eng = _make_engine()
    assert len(eng.kb) == 12
    assert eng.inverted_index
    assert eng.synonyms
    assert eng.idf
    assert eng.kb_id


def test_kb_version_stable():
    """相同知识库 → 相同 kb_version（md5 前缀）。"""
    e1 = _make_engine()
    e2 = _make_engine()
    assert e1.kb_id == e2.kb_id
