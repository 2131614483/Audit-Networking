"""[FI-01] pipeline 端到端单测：Pipeline.run() 全流程跑通。

fi_01 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 assessments / summary）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.fi_01.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    return Pipeline(config={
        "db_path": str(tmp_path / "fi_01_pipeline.db"),
        **overrides,
    })


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 assessments + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "assessments" in output
        assert "summary" in output
        assert output["summary"]["asset_count"] == 4
        assert output["summary"]["total_ead"] > 0
        assert "risk_level" in output["summary"]
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        direct = pipe.engine.execute(sample)
        assert output["summary"]["asset_count"] == direct["summary"]["asset_count"]
        assert output["summary"]["total_ead"] == direct["summary"]["total_ead"]
        assert len(output["assessments"]) == len(direct["assessments"])
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 中的 db_path 透传到 engine。"""
    pipe = _make_pipeline(tmp_path, threshold={"confidence": 0.9})
    try:
        assert pipe.engine.config.get("db_path") == str(tmp_path / "fi_01_pipeline.db")
        assert pipe.engine.config.get("threshold") == {"confidence": 0.9}
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """空 loans 经 Pipeline 透传后仍返回空结果。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"loans": []})
        assert output["assessments"] == []
        assert output["summary"]["asset_count"] == 0
    finally:
        _close(pipe)


def test_pipeline_risk_level_present(tmp_path):
    """端到端后 summary 含 risk_level（后处理产物）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["summary"]["risk_level"] in ("低风险", "中风险", "高风险")
    finally:
        _close(pipe)


def test_pipeline_single_loan(tmp_path):
    """单笔贷款端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"loans": [{
            "asset_id": "S1", "borrower": "单笔", "amount": 100000,
            "remaining_amount": 80000, "industry": "制造业",
            "collateral_type": "现金", "debt_ratio": 0.3,
            "current_ratio": 2.0, "operating_margin": 0.15,
            "cashflow_coverage": 2.0, "payment_history": 24,
        }]})
        assert output["summary"]["asset_count"] == 1
        assert output["assessments"][0]["asset_id"] == "S1"
    finally:
        _close(pipe)
