"""[ES-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

es_02 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 activities / summary）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.es_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    return Pipeline(config=overrides)


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 activities + summary。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "activities" in output
    assert "summary" in output
    assert output["summary"]["activity_count"] == 8
    assert output["summary"]["total_emission_kg"] > 0


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["summary"]["activity_count"] == direct["summary"]["activity_count"]
    assert output["summary"]["total_emission_kg"] == direct["summary"]["total_emission_kg"]
    assert len(output["activities"]) == len(direct["activities"])


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(threshold={"confidence": 0.9})
    assert pipe.engine.config.get("threshold") == {"confidence": 0.9}


def test_pipeline_empty_input_handled():
    """空 activities 经 Pipeline 透传后仍返回空结果。"""
    pipe = _make_pipeline()
    output = pipe.run({"activities": []})
    assert output["activities"] == []
    assert output["summary"]["activity_count"] == 0


def test_pipeline_scope_totals_consistent():
    """端到端后 summary 各 Scope 吨数之和 = 总吨数。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    s = output["summary"]
    scope_sum = s["scope_1_tons"] + s["scope_2_tons"] + s["scope_3_tons"]
    assert abs(scope_sum - s["total_emission_tons"]) < 1e-6
