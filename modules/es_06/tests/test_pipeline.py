"""[ES-06] pipeline 端到端单测：Pipeline.run() 全流程跑通。

es_06 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 methodologies / summary / quality_flags）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.es_06.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    pipe = Pipeline(config=overrides)
    # NOTE: es_06 Pipeline.__init__ 未调用 engine.setup()（engine bug），
    # 此处显式 setup 以测试真实编排逻辑。
    pipe.engine.setup()
    return pipe


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 methodologies + summary。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "methodologies" in output
    assert len(output["methodologies"]) == 3
    assert "summary" in output
    assert output["summary"]["total_methodologies"] == 3
    assert "quality_flags" in output


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert len(output["methodologies"]) == len(direct["methodologies"])
    assert output["summary"]["total_methodologies"] == direct["summary"]["total_methodologies"]


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(threshold={"confidence": 0.9})
    assert pipe.engine.config.get("threshold") == {"confidence": 0.9}


def test_pipeline_empty_input_handled():
    """空输入经 Pipeline 后返回空方法论。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["methodologies"] == []
    assert output["summary"]["total_methodologies"] == 0


def test_pipeline_single_dict_input():
    """单 dict 输入经 Pipeline 也能跑通。"""
    pipe = _make_pipeline()
    output = pipe.run({"company": "A", "industry": "制造业", "audit_goal": "碳排放"})
    assert len(output["methodologies"]) == 1
    assert output["methodologies"][0]["subject"] == "GHG排放审计（制造业）"
