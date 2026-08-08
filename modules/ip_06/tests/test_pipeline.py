"""[IP-06] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ip_06 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 solutions / roadmap / statistics）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ip_06.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 solutions + roadmap。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "solutions" in output
    assert "roadmap" in output
    assert len(output["solutions"]) == 3


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert len(output["solutions"]) == len(direct["solutions"])
    assert len(output["roadmap"]) == len(direct["roadmap"])


def test_pipeline_preserves_statistics_and_top_actions():
    """Pipeline 保留 statistics + top_actions（postprocess 产物）。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "statistics" in output
    assert output["statistics"]["total_issues"] == 3
    assert "top_actions" in output
    assert len(output["top_actions"]) <= 3


def test_pipeline_priority_sorted():
    """Pipeline 输出的方案按优先级排序。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    scores = [s["priority_score"] for s in output["solutions"]]
    assert scores == sorted(scores, reverse=True)
    ranks = [s["priority_rank"] for s in output["solutions"]]
    assert ranks == list(range(1, len(ranks) + 1))


def test_pipeline_empty_issues_handled():
    """空 issues 经 Pipeline 透传后不崩。"""
    pipe = _make_pipeline()
    output = pipe.run({"issues": []})
    assert output["solutions"] == []
    assert output["statistics"]["total_issues"] == 0
