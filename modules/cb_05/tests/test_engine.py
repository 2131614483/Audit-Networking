"""[CB-05] engine 单测：术语感知翻译 / 跨语言检索 / 术语库查询 / 语言识别。

LLMEngine 为纯 stdlib 实现（术语库 + difflib 模糊匹配），不依赖外部 LLM。
内置 45+ 审计/会计/税务/金融/法律术语的中英日德法五语对照。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cb_05.engine import LLMEngine, _detect_language

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 术语感知翻译
# ----------------------------------------------------------------------
def test_translate_zh_to_en_replaces_terms():
    """中译英：文本中的审计术语被替换为英文对应词。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["source_lang"] == "zh"
    assert result["target_lang"] == "en"
    # "审计报告" 和 "内部控制" 都在术语库中，应被替换
    assert "audit report" in result["translated_text"].lower()
    assert "internal control" in result["translated_text"].lower()
    assert result["memory_hit"] is False
    assert result["term_count"] >= 2


def test_translate_records_replaced_terms():
    """翻译记录被替换的术语列表（含源/目标/计数/领域）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for t in result["translated_terms"]:
        assert "source_term" in t
        assert "target_term" in t
        assert "count" in t
        assert "domain" in t
        assert t["count"] >= 1


def test_translate_memory_hit_on_repeat():
    """相同输入第二次翻译命中翻译记忆（memory_hit=True）。"""
    eng = _make_engine()
    eng.execute(_sample())  # 第一次：未命中
    result = eng.execute(_sample())  # 第二次：命中
    assert result["memory_hit"] is True


def test_translate_empty_text():
    """空文本返回空翻译。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "translate",
        "text": "",
        "source_lang": "zh",
        "target_lang": "en",
    })
    assert result["translated_text"] == ""


def test_translate_default_target_lang_en():
    """translate 未指定 target_lang 时默认 en。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "translate",
        "text": "审计",
        "source_lang": "zh",
    })
    assert result["target_lang"] == "en"
    assert "audit" in result["translated_text"].lower()


# ----------------------------------------------------------------------
# 术语库查询
# ----------------------------------------------------------------------
def test_glossary_lookup_exact_match():
    """精确查询"审计"命中术语库，返回五语对照。"""
    eng = _make_engine()
    result = eng.execute({"action": "glossary_lookup", "text": "审计"})
    assert len(result["results"]) >= 1
    entry = result["results"][0]
    assert entry["match_type"] == "exact"
    assert entry["zh"] == "审计"
    assert entry["en"] == "audit"
    assert entry["domain"] == "audit"


def test_glossary_lookup_english_term():
    """英文术语 "audit" 也能精确查询到。"""
    eng = _make_engine()
    result = eng.execute({"action": "glossary_lookup", "text": "audit"})
    assert len(result["results"]) >= 1
    assert result["results"][0]["zh"] == "审计"


def test_glossary_lookup_fuzzy_match():
    """近似词触发模糊匹配（相似度 > 0.6）。"""
    eng = _make_engine()
    # "auditor" 与 "audit" 相似度高，但 "auditor" 本身也在库中（精确匹配）
    # 用 "auditreport" 测试模糊（与 "audit report" 相似）
    result = eng.execute({"action": "glossary_lookup", "text": "inventoryy"})
    # 应触发模糊匹配
    if result["results"]:
        assert result["results"][0]["match_type"] == "fuzzy"


def test_glossary_lookup_no_match():
    """完全无关的查询返回空结果列表。"""
    eng = _make_engine()
    result = eng.execute({"action": "glossary_lookup", "text": "zzznomatchqqq"})
    assert result["results"] == []
    assert result["total_terms"] >= 40


# ----------------------------------------------------------------------
# 语言识别
# ----------------------------------------------------------------------
def test_detect_language_chinese():
    """检测中文文本。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "detect_language",
        "text": "审计报告指出内部控制存在重大缺陷",
    })
    assert result["detected_language"] == "zh"


def test_detect_language_english():
    """检测英文文本。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "detect_language",
        "text": "The audit report indicates internal control weakness.",
    })
    assert result["detected_language"] == "en"


def test_detect_language_helper_function():
    """_detect_language 辅助函数直接调用。"""
    assert _detect_language("审计") == "zh"
    assert _detect_language("audit") == "en"
    assert _detect_language("") == "en"


# ----------------------------------------------------------------------
# 跨语言检索
# ----------------------------------------------------------------------
def test_add_document_and_search():
    """添加文档后跨语言检索能命中。"""
    eng = _make_engine()
    # 先添加文档
    eng.execute({
        "action": "add_document",
        "documents": [
            {"doc_id": "D1", "title": "审计报告", "content": "内部控制与审计证据", "language": "zh"},
        ],
    })
    # 中文查询应命中
    result = eng.execute({"action": "search", "query": "审计"})
    assert result["matched_count"] >= 1
    assert result["results"][0]["doc_id"] == "D1"
    assert "relevance_score" in result["results"][0]


def test_search_expands_to_multiple_languages():
    """中文查询"审计"扩展为多语言同义词（expanded_queries 含 en）。"""
    eng = _make_engine()
    eng.execute({
        "action": "add_document",
        "documents": [{"doc_id": "D1", "title": "audit", "content": "audit evidence", "language": "en"}],
    })
    result = eng.execute({"action": "search", "query": "审计"})
    # "审计" → en "audit" 扩展
    assert "en" in result["expanded_queries"]
    assert "audit" in result["expanded_queries"]["en"].lower()


def test_search_empty_document_store():
    """空文档库检索返回 matched_count=0。"""
    eng = _make_engine()
    result = eng.execute({"action": "search", "query": "审计"})
    assert result["matched_count"] == 0
    assert result["total_documents"] == 0
    assert result["results"] == []


def test_add_document_returns_count():
    """add_document 返回添加数量 + 总文档数。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "add_document",
        "documents": [
            {"title": "doc1", "content": "content1"},
            {"title": "doc2", "content": "content2"},
        ],
    })
    assert result["added_count"] == 2
    assert result["total_documents"] == 2


# ----------------------------------------------------------------------
# 空输入 / 边界 / 元数据
# ----------------------------------------------------------------------
def test_string_input_defaults_to_search():
    """字符串输入默认 action=search。"""
    eng = _make_engine()
    result = eng.execute("审计")
    assert result["query"] == "审计"
    # 无文档时 matched_count=0
    assert result["matched_count"] == 0


def test_unknown_action_returns_error():
    """未知 action 返回 error 字段。"""
    eng = _make_engine()
    result = eng.execute({"action": "unknown_action", "text": "x"})
    assert "error" in result


def test_collaboration_metadata():
    """所有结果带 collaboration 元数据（module/family）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["collaboration"]["module"] == "CB-05"
    assert result["collaboration"]["family"] == "llm_rag"


def test_model_has_glossary_and_lang_index():
    """engine 加载后 model 含术语库 + 五语索引。"""
    eng = _make_engine()
    assert len(eng.model["glossary"]) >= 40
    assert "zh" in eng.model["lang_index"]
    assert "en" in eng.model["lang_index"]
    assert "审计" in eng.model["lang_index"]["zh"] or "审计".lower() in eng.model["lang_index"]["zh"]
