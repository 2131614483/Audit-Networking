"""[CB-06] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_06 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cb_06.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_generate_orders():
    """用 sample_input.json 端到端生成审计指令。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert output["total_orders"] == 3
    assert output["collaboration"]["module"] == "CB-06"
    assert output["collaboration"]["family"] == "llm_rag"


def test_pipeline_track_progress():
    """Pipeline 串联 generate + track_progress 多步流程。"""
    pipe = _make_pipeline()
    pipe.run(_sample())  # 生成任务
    output = pipe.run({"action": "track_progress"})
    assert output["total_tasks"] == 3


def test_pipeline_kb_query():
    """Pipeline 透传 kb_query action。"""
    pipe = _make_pipeline()
    output = pipe.run({"action": "kb_query", "kb_query": "函证回收率"})
    assert output["total"] >= 4


def test_pipeline_string_input_kb_query():
    """Pipeline 接受字符串输入（默认 kb_query）。"""
    pipe = _make_pipeline()
    output = pipe.run("函证")
    assert "results" in output


def test_pipeline_passes_through_custom_stages():
    """custom 阶段为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    pipe.engine.setup()
    direct = pipe.engine.execute(sample)
    assert output["total_orders"] == direct["total_orders"]
    assert len(output["orders"]) == len(direct["orders"])
