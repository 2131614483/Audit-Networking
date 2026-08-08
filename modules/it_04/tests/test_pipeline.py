"""[IT-04] pipeline 端到端单测：Pipeline.run() 全流程跑通。

it_04 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.it_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    pipe = Pipeline(config=overrides)
    pipe.engine.setup()
    return pipe


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 summary + alerts。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "summary" in output
    assert "alerts" in output
    assert output["summary"]["monitored_metrics"] == 3
    assert len(output["alerts"]) > 0


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["summary"]["monitored_metrics"] == direct["summary"]["monitored_metrics"]
    assert output["summary"]["total_anomalies"] == direct["summary"]["total_anomalies"]
    assert len(output["alerts"]) == len(direct["alerts"])


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = Pipeline(config={"custom_key": "value"})
    pipe.engine.setup()
    assert pipe.engine.config.get("custom_key") == "value"


def test_pipeline_dict_input_accepted():
    """Pipeline 接受 dict 输入（单指标）。"""
    pipe = _make_pipeline()
    output = pipe.run({"metric": "x", "values": [1, 2, 3, 4, 5, 6]})
    assert output["summary"]["monitored_metrics"] == 1


def test_pipeline_empty_input_handled():
    """空 list 输入经 Pipeline 后仍返回零计数结构（不崩）。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["summary"]["monitored_metrics"] == 0
    assert output["alerts"] == []
