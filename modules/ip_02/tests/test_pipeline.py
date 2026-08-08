"""[IP-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ip_02 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果（含 reply + quality）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ip_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    return Pipeline(config=overrides)


def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 reply + similar_cases。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "reply" in output
    assert "similar_cases" in output
    assert len(output["similar_cases"]) == 3


def test_pipeline_passes_through_custom_stages():
    """custom_* 均为 pass-through，输出含 action_tips + metadata。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "action_tips" in output
    assert "metadata" in output
    assert output["metadata"]["similar_case_count"] == 3


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(custom_key="value")
    assert pipe.engine.config.get("custom_key") == "value"


def test_pipeline_empty_input_handled():
    """空 question 经 Pipeline 后仍返回 reply（不崩）。"""
    pipe = _make_pipeline()
    output = pipe.run({"question": ""})
    assert "reply" in output


def test_pipeline_quality_through_pipeline():
    """质量检查经 Pipeline 仍生效。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "quality" in output
    assert 0.0 <= output["quality"]["overall"] <= 1.0
