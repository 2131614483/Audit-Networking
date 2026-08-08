"""[IA-08] pipeline 端到端单测：Pipeline.run() 全流程跑通。

custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute + format_output。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ia_08.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    p = Pipeline(config=overrides)
    p.engine.setup()
    return p


_PASS_EVIDENCE = {
    "approval_pass_rate": 1.0, "sla_hit_rate": 1.0,
    "bypass_count": 0, "log_complete_rate": 1.0,
}


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """sample_input 端到端跑通，输出含 items + overall。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "items" in output
    assert "overall" in output
    assert output["overall"]["total"] == len(_sample())


def test_pipeline_single_item():
    """单项 dict 输入也能跑通。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "task_id": "P1", "remediation_type": "流程控制",
        "evidence": _PASS_EVIDENCE,
    })
    assert output["overall"]["total"] == 1
    assert output["items"][0]["verdict"] == "通过"


def test_pipeline_passes_through_custom_stages():
    """custom 均为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["overall"]["total"] == direct["overall"]["total"]
    assert output["overall"]["avg_score"] == direct["overall"]["avg_score"]


def test_pipeline_config_thresholds():
    """config 中的 pass_threshold 透传到 engine。"""
    pipe = _make_pipeline(pass_threshold=0.95)
    assert pipe.engine.thresholds["pass"] == 0.95
