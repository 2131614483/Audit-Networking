"""[IP-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ip_03 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 timeline / equity_snapshots / compliance）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ip_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 timeline + equity_snapshots。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "timeline" in output
    assert "equity_snapshots" in output
    assert "anomalies" in output
    assert "compliance" in output
    assert output["company"] == "示例科技股份有限公司"
    assert len(output["timeline"]) == 4


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    # engine 直跑
    direct = pipe.engine.execute(sample)
    # pass-through 下两者 timeline 长度一致
    assert len(output["timeline"]) == len(direct["timeline"])
    assert output["statistics"]["total_events"] == direct["statistics"]["total_events"]
    assert output["verdict"] == direct["verdict"]


def test_pipeline_preserves_statistics_and_verdict():
    """Pipeline 保留 statistics + verdict（postprocess 产物）。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "statistics" in output
    assert output["statistics"]["total_events"] == 4
    assert output["statistics"]["key_events"] >= 1
    assert "verdict" in output
    assert output["verdict"] == "通过自动化梳理"


def test_pipeline_empty_events_handled():
    """空事件列表经 Pipeline 透传后仍返回空 timeline。"""
    pipe = _make_pipeline()
    output = pipe.run({"events": []})
    assert output["timeline"] == []
    assert output["anomalies"] == []
    assert output["statistics"]["total_events"] == 0


def test_pipeline_detects_anomalies():
    """含异常的输入经 Pipeline 透传后仍能检测异常并标记 verdict。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "events": [{
            "date": "2020-01-01", "event_type": "增资",
            "shareholders": [{"name": "A", "ratio": 50}],
            "has_resolution": False,
        }]
    })
    assert len(output["anomalies"]) > 0
    assert output["verdict"] in ("需重点人工复核", "建议人工复核")
