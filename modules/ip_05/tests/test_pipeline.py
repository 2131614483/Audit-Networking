"""[IP-05] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ip_05 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 answer / top_cases / confidence）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ip_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 answer + top_cases。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "answer" in output
    assert "top_cases" in output
    assert "intent" in output
    assert len(output["top_cases"]) <= 5


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert len(output["top_cases"]) == len(direct["top_cases"])
    assert output["intent"] == direct["intent"]
    assert output["confidence"] == direct["confidence"]


def test_pipeline_preserves_confidence_and_disclaimer():
    """Pipeline 保留 confidence + disclaimer（postprocess 产物）。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "confidence" in output
    assert 0 <= output["confidence"] <= 1.0
    assert "disclaimer" in output


def test_pipeline_accepts_string_query():
    """Pipeline 接受字符串 query 输入。"""
    pipe = _make_pipeline()
    output = pipe.run("有哪些IPO案例公司")
    assert "找到" in output["answer"]["text"]
    assert output["intent"] == "list"


def test_pipeline_empty_query_handled():
    """空 query 经 Pipeline 透传后不崩。"""
    pipe = _make_pipeline()
    output = pipe.run({"query": ""})
    assert "answer" in output
    assert output["confidence"] >= 0
