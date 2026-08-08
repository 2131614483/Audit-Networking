"""[CB-05] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_05 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cb_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_translate():
    """用 sample_input.json 端到端跑翻译。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "translated_text" in output
    assert "audit report" in output["translated_text"].lower()
    assert output["collaboration"]["module"] == "CB-05"
    assert output["collaboration"]["family"] == "llm_rag"


def test_pipeline_glossary_lookup():
    """Pipeline 透传 glossary_lookup action。"""
    pipe = _make_pipeline()
    output = pipe.run({"action": "glossary_lookup", "text": "审计"})
    assert len(output["results"]) >= 1
    assert output["results"][0]["en"] == "audit"


def test_pipeline_add_document_and_search():
    """Pipeline 支持先 add_document 再 search 的多步流程。"""
    pipe = _make_pipeline()
    pipe.run({
        "action": "add_document",
        "documents": [{"doc_id": "D1", "title": "审计", "content": "audit report"}],
    })
    output = pipe.run({"action": "search", "query": "审计"})
    assert output["matched_count"] >= 1


def test_pipeline_string_input_search():
    """Pipeline 接受字符串输入（默认 search）。"""
    pipe = _make_pipeline()
    output = pipe.run("审计")
    assert output["query"] == "审计"
    assert "collaboration" in output


def test_pipeline_passes_through_custom_stages():
    """custom 阶段为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    pipe.engine.setup()
    direct = pipe.engine.execute(sample)
    assert output["translated_text"] == direct["translated_text"]
    assert output["term_count"] == direct["term_count"]
