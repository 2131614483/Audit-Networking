"""[CM-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cm_02 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 alerts / summary）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cm_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    return Pipeline(config=overrides)


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 alerts + summary。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "alerts" in output
    assert "summary" in output
    assert output["summary"]["total"] == 4


def test_pipeline_returns_severity_scores():
    """Pipeline 输出每个告警带 severity_score / priority / action。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    for a in output["alerts"]:
        assert "severity_score" in a
        assert "priority" in a
        assert "action" in a


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    # engine 直跑
    direct = pipe.engine.execute(sample)
    assert output["summary"]["total"] == direct["summary"]["total"]
    assert output["summary"]["P0"] == direct["summary"]["P0"]
    assert output["summary"]["auto_closed"] == direct["summary"]["auto_closed"]


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = Pipeline(config={"custom_key": "value"})
    assert pipe.engine.config.get("custom_key") == "value"


def test_pipeline_empty_input_handled():
    """空 alerts 经 Pipeline 透传后仍返回零计数 summary。"""
    pipe = _make_pipeline()
    output = pipe.run({"alerts": []})
    assert output["alerts"] == []
    assert output["summary"]["total"] == 0


def test_pipeline_assigns_auto_close_to_p3():
    """Pipeline 端到端：P3 告警被自动归档（auto_close）。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "alerts": [
            {"alert_id": "LOW", "source": "S", "category": "normal",
             "amount": 100, "frequency": 1, "after_hours": False, "repeat_count": 0}
        ]
    })
    a = output["alerts"][0]
    assert a["priority"] == "P3"
    assert a["action"] == "auto_close"
    assert output["summary"]["auto_closed"] == 1
