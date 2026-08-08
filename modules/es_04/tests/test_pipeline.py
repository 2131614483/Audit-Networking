"""[ES-04] pipeline 端到端单测：Pipeline.run() 全流程跑通。

es_04 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 overall_risk / all_claim_evaluations / contradictions）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.es_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    pipe = Pipeline(config=overrides)
    # NOTE: es_04 Pipeline.__init__ 未调用 engine.setup()（engine bug），
    # 此处显式 setup 以测试真实编排逻辑。
    pipe.engine.setup()
    return pipe


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 overall_risk + claim 评估。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "overall_risk" in output
    assert "all_claim_evaluations" in output
    assert len(output["all_claim_evaluations"]) == 2
    assert "contradictions" in output
    assert "knowledge_graph_summary" in output


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["overall_risk"]["score"] == direct["overall_risk"]["score"]
    assert len(output["all_claim_evaluations"]) == len(direct["all_claim_evaluations"])
    assert len(output["contradictions"]) == len(direct["contradictions"])


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(threshold={"confidence": 0.9})
    assert pipe.engine.config.get("threshold") == {"confidence": 0.9}


def test_pipeline_empty_input_handled():
    """空声明经 Pipeline 后返回数据不足。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["overall_risk"]["level"] == "数据不足"
    assert output["all_claim_evaluations"] == []


def test_pipeline_detects_contradictions_end_to_end():
    """端到端能检出声明间矛盾。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert len(output["contradictions"]) >= 1
