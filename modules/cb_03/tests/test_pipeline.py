"""[CB-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_03 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cb_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_search():
    """用 sample_input.json 端到端跑 search，输出含 summary + family/module 标记。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert output["summary"]["module"] == "CB-03"
    assert output["summary"]["family"] == "llm_rag"
    assert len(output["regulations"]) >= 1
    assert output["regulations"][0]["reg_id"] == "GDPR-001"


def test_pipeline_qa_action():
    """Pipeline 透传 qa action，返回结构化回答。"""
    pipe = _make_pipeline()
    output = pipe.run({"query": "GDPR 数据跨境", "action": "qa"})
    assert "answer" in output
    assert "sources" in output
    assert output["sources"]


def test_pipeline_compare_action():
    """Pipeline 透传 compare action，返回法规比对结果。"""
    pipe = _make_pipeline()
    output = pipe.run({"action": "compare", "compare_with": "GDPR-001"})
    assert output["regulation_a"]["reg_id"] == "GDPR-001"
    assert "comparison_summary" in output


def test_pipeline_empty_query_handled():
    """空 query 经 Pipeline 透传后返回空法规列表。"""
    pipe = _make_pipeline()
    output = pipe.run({"query": "", "action": "search"})
    assert output["regulations"] == []


def test_pipeline_passes_through_custom_stages():
    """custom 阶段为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    pipe.engine.setup()
    direct = pipe.engine.execute(sample)
    assert output["summary"]["total_results"] == direct["summary"]["total_results"]
    assert output["regulations"][0]["reg_id"] == direct["regulations"][0]["reg_id"]
