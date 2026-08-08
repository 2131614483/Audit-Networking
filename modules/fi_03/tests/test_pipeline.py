"""[FI-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

fi_03 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 applicants / summary）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.fi_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    return Pipeline(config=overrides)


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 applicants + summary。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "applicants" in output
    assert "summary" in output
    assert output["summary"]["total"] == 4
    assert output["summary"]["approved"] == 2


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["summary"]["total"] == direct["summary"]["total"]
    assert output["summary"]["approved"] == direct["summary"]["approved"]
    assert len(output["applicants"]) == len(direct["applicants"])


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(threshold={"confidence": 0.9})
    assert pipe.engine.config.get("threshold") == {"confidence": 0.9}


def test_pipeline_empty_input_handled():
    """空 applicants 经 Pipeline 透传后仍返回空结果。"""
    pipe = _make_pipeline()
    output = pipe.run({"applicants": []})
    assert output["applicants"] == []
    assert output["summary"]["total"] == 0


def test_pipeline_results_sorted():
    """端到端后结果仍按违约概率降序排列。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    probs = [a["default_probability"] for a in output["applicants"]]
    assert probs == sorted(probs, reverse=True)


def test_pipeline_single_applicant():
    """单个申请人端到端跑通。"""
    pipe = _make_pipeline()
    output = pipe.run({"applicants": [{
        "applicant_id": "S1", "name": "单测", "credit_score": 800,
        "dti_ratio": 0.2, "ltv_ratio": 0.6, "employment_years": 15,
        "default_history": 0, "loan_amount": 200000,
    }]})
    assert output["summary"]["total"] == 1
    assert output["applicants"][0]["rating"] == "A"
