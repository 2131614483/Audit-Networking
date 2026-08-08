"""[IP-05] engine 单测：IPO案例知识库与RAG —— 混合检索 + 意图识别 + 问答生成。

LLMEngine 纯 stdlib 实现（无 PortableDB）：BM25 + 序列匹配 + 意图识别。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ip_05.engine import LLMEngine, _tokenize, _bm25

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 分词 / BM25
# ----------------------------------------------------------------------
def test_tokenize_returns_list():
    """分词返回列表。"""
    toks = _tokenize("收入确认政策")
    assert isinstance(toks, list)
    assert len(toks) > 0


def test_tokenize_empty_string():
    """空字符串分词返回空列表。"""
    assert _tokenize("") == []


def test_bm25_zero_for_no_overlap():
    """无重叠词时 BM25 为 0。"""
    score = _bm25(["苹果"], ["香蕉"], {"苹果": 1.0, "香蕉": 1.0}, 2.0)
    assert score == 0.0


def test_bm25_positive_for_overlap():
    """有重叠词时 BM25 为正。"""
    score = _bm25(["收入"], ["收入", "确认"], {"收入": 1.5}, 2.0)
    assert score > 0


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_cases():
    """setup 后 model 含 10 个 IPO 案例。"""
    eng = _make_engine()
    assert len(eng.model["cases"]) == 10
    assert eng._idf  # IDF 已预计算
    assert eng._avg_dl > 0


def test_cases_have_required_fields():
    """每个案例含必要字段。"""
    eng = _make_engine()
    for c in eng.model["cases"]:
        assert "id" in c and "company" in c and "industry" in c
        assert "board" in c and "result" in c and "rounds" in c
        assert "keywords" in c and "key_questions" in c


# ----------------------------------------------------------------------
# 预处理 / 意图识别
# ----------------------------------------------------------------------
def test_preprocess_extracts_query_and_intent():
    """预处理提取 query + tokens + intent。"""
    eng = _make_engine()
    prepared = eng._preprocess(_sample())
    assert prepared["query"] == _sample()["query"]
    assert prepared["query_tokens"]
    assert prepared["intent"] in ("list", "stats", "benchmark", "qa")


def test_preprocess_accepts_string_input():
    """字符串输入自动包装为 {"query": ...}。"""
    eng = _make_engine()
    prepared = eng._preprocess("有哪些IPO案例")
    assert prepared["query"] == "有哪些IPO案例"
    assert prepared["intent"] == "list"


def test_preprocess_non_dict_non_str_raises():
    """非 dict/str 输入抛 ValueError。"""
    eng = _make_engine()
    with pytest.raises(ValueError):
        eng._preprocess(12345)


def test_detect_intent_list():
    """列表意图识别。"""
    eng = _make_engine()
    assert eng._detect_intent("有哪些IPO案例公司") == "list"


def test_detect_intent_stats():
    """统计意图识别。"""
    eng = _make_engine()
    assert eng._detect_intent("通过率平均多少") == "stats"


def test_detect_intent_benchmark():
    """对标意图识别。"""
    eng = _make_engine()
    assert eng._detect_intent("与行业对标比较") == "benchmark"


def test_detect_intent_default_qa():
    """默认意图为 qa。"""
    eng = _make_engine()
    assert eng._detect_intent("收入确认时点") == "qa"


# ----------------------------------------------------------------------
# 检索与问答生成
# ----------------------------------------------------------------------
def test_infer_returns_top_cases_and_answer():
    """infer 返回 top_cases + answer + intent + global_stats。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "answer" in result
    assert "top_cases" in result
    assert "intent" in result
    assert "global_stats" in result
    assert len(result["top_cases"]) <= 5


def test_top_cases_have_scores():
    """top_cases 每项含 case + score。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for tc in result["top_cases"]:
        assert "case" in tc and "score" in tc
        assert isinstance(tc["score"], float)


def test_struct_filter_boosts_matching_industry():
    """行业/板块匹配的结构过滤加权提升相关案例排序。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # 软件和信息技术服务业+科创板案例应在 top 中
    top_ids = [tc["case"]["id"] for tc in result["top_cases"]]
    # IPO-001 和 IPO-005 都是软件和信息技术服务业+科创板
    assert "IPO-001" in top_ids or "IPO-005" in top_ids


def test_answer_text_generated():
    """answer.text 含内容。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["answer"]["text"]
    assert isinstance(result["answer"]["text"], str)


def test_answer_sources_reference_cases():
    """answer.sources 引用案例 id。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    sources = result["answer"]["sources"]
    assert len(sources) == len(result["top_cases"])
    for s in sources:
        assert "id" in s and "company" in s


def test_list_intent_answer_lists_cases():
    """list 意图 → answer.text 含案例列表。"""
    eng = _make_engine()
    result = eng.execute({"query": "有哪些IPO案例公司"})
    assert "找到" in result["answer"]["text"]


def test_stats_intent_answer_has_pass_rate():
    """stats 意图 → answer.text 含通过率。"""
    eng = _make_engine()
    result = eng.execute({"query": "案例库通过率平均多少"})
    assert "通过率" in result["answer"]["text"]


def test_global_stats_aggregates_by_industry_and_board():
    """global_stats 按行业/板块聚合。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    stats = result["global_stats"]
    assert stats["total"] == 10
    assert "by_industry" in stats and "by_board" in stats
    assert "软件和信息技术服务业" in stats["by_industry"]


# ----------------------------------------------------------------------
# 后处理
# ----------------------------------------------------------------------
def test_postprocess_adds_confidence_and_disclaimer():
    """postprocess 添加 confidence + disclaimer。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "confidence" in result
    assert 0 <= result["confidence"] <= 1.0
    assert "disclaimer" in result
    assert "AI" in result["disclaimer"]


def test_empty_query_handled():
    """空 query 不崩。"""
    eng = _make_engine()
    result = eng.execute({"query": ""})
    assert "answer" in result
    assert "top_cases" in result
    assert result["confidence"] >= 0
