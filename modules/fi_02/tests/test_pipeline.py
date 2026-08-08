"""[FI-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

fi_02 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 risk_scores / summary）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.fi_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    return Pipeline(config={
        "db_path": str(tmp_path / "fi_02_pipeline.db"),
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
    """用 sample_input.json 端到端跑通，输出含 risk_scores + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "risk_scores" in output
        assert "summary" in output
        assert output["summary"]["entity_count"] == 5
        assert output["summary"]["guarantee_count"] == 5
        assert "systemic_risk_level" in output["summary"]
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
        assert output["summary"]["entity_count"] == direct["summary"]["entity_count"]
        assert output["summary"]["high_risk_count"] == direct["summary"]["high_risk_count"]
        assert len(output["risk_scores"]) == len(direct["risk_scores"])
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 中的 db_path 透传到 engine。"""
    pipe = _make_pipeline(tmp_path, threshold={"confidence": 0.9})
    try:
        assert pipe.engine.config.get("db_path") == str(tmp_path / "fi_02_pipeline.db")
        assert pipe.engine.config.get("threshold") == {"confidence": 0.9}
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """空实体和担保列表经 Pipeline 透传后仍返回零汇总。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"entities": [], "guarantees": []})
        assert output["summary"]["entity_count"] == 0
        assert output["risk_scores"] == {}
    finally:
        _close(pipe)


def test_pipeline_systemic_risk_level_present(tmp_path):
    """端到端后 summary 含 systemic_risk_level（后处理产物）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["summary"]["systemic_risk_level"] in ("低", "中", "高")
    finally:
        _close(pipe)


def test_pipeline_shock_simulations_present(tmp_path):
    """端到端后含冲击模拟结果。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert len(output["shock_simulations"]) >= 1
    finally:
        _close(pipe)
