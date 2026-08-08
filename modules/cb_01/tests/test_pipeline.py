"""[CB-01] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_01 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 summary / family / module 标记）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cb_01.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline(config={"weight_dim": 8})


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 summary + family/module 标记。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert output["family"] == "federation"
    assert output["module"] == "CB-01"
    assert "summary" in output
    assert output["summary"]["node_count"] == 4
    assert output["round"] >= 1


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 中的 weight_dim 透传到 engine。"""
    pipe = Pipeline(config={"weight_dim": 6})
    output = pipe.run({
        "action": "train",
        "node_updates": [{"node_id": "CN-01", "gradients": [0.1] * 6}],
    })
    assert len(output["global_weights"]) == 6


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致（含 summary）。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    # engine 直跑
    direct = pipe.engine.execute(sample)
    # pass-through 下两者 summary 一致
    assert output["summary"]["node_count"] == direct["summary"]["node_count"]
    assert output["summary"]["total_samples"] == direct["summary"]["total_samples"]


def test_pipeline_empty_input_handled():
    """空 node_updates 经 Pipeline 透传后仍返回 no_node_updates。"""
    pipe = _make_pipeline()
    output = pipe.run({"action": "train", "node_updates": []})
    assert output["status"] == "no_node_updates"
