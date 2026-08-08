"""[CB-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_02 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 summary / routing_decision / fields）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cb_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 summary + family/module 标记。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert output["summary"]["module"] == "CB-02"
    assert output["summary"]["family"] == "ml_nlp"
    assert output["summary"]["total_fields"] == 6
    assert output["routing_decision"]["action"] == "mask_then_allow"
    # 身份证字段被脱敏
    id_field = next(f for f in output["fields"] if f["field_name"] == "身份证号")
    assert id_field["action"] == "mask"
    assert "*" in id_field["masked_value"]


def test_pipeline_routing_cn_to_cn_no_mask():
    """Pipeline 透传 CN→CN 路由，字段不脱敏。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "CN",
        "fields": [{"name": "手机号", "value": "13812345678"}],
    })
    assert output["routing_decision"]["action"] == "allow"
    assert output["fields"][0]["action"] == "none"
    assert output["fields"][0]["masked_value"] == "13812345678"


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    # engine 直跑
    pipe.engine.setup()
    direct = pipe.engine.execute(sample)
    # pass-through 下两者 summary 一致
    assert output["summary"]["total_fields"] == direct["summary"]["total_fields"]
    assert output["summary"]["total_detections"] == direct["summary"]["total_detections"]


def test_pipeline_empty_input_handled():
    """空 fields 经 Pipeline 透传后仍返回空字段列表。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [],
    })
    assert output["fields"] == []
    assert output["summary"]["total_fields"] == 0


def test_pipeline_unknown_route_denied():
    """未知法域经 Pipeline 透传后路由为 deny。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "source_jurisdiction": "XX",
        "target_jurisdiction": "YY",
        "fields": [{"name": "x", "value": "1"}],
    })
    assert output["routing_decision"]["action"] == "deny"
