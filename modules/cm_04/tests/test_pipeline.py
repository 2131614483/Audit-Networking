"""[CM-04] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cm_04 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
支持 quantify / roi / simulate / sensitivity / add_risk / efficiency 等 action。
每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cm_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={
        "db_path": str(tmp_path / "cm_04_pipeline.db"),
        **overrides,
    })
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_quantify_end_to_end(tmp_path):
    """用 sample_input.json 端到端跑通 quantify 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["action"] == "quantify"
        assert "breakdown" in output
        assert "totals" in output
        assert "roi_metrics" in output
        assert "engine" in output
    finally:
        _close(pipe)


def test_pipeline_roi_end_to_end(tmp_path):
    """Pipeline 端到端跑通 roi 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "action": "roi",
            "initial_investment": 5000000,
            "annual_cost": 2000000,
            "annual_revenue": 5000000,
            "time_horizon_years": 3,
        })
        assert output["action"] == "roi"
        assert "roi_percent" in output
        assert "npv" in output
        assert "yearly_projection" in output
    finally:
        _close(pipe)


def test_pipeline_simulate_end_to_end(tmp_path):
    """Pipeline 端到端跑通 simulate 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "action": "simulate",
            "num_simulations": 100,
        })
        assert output["action"] == "simulate"
        assert "statistics" in output
        assert output["num_simulations"] == 100
    finally:
        _close(pipe)


def test_pipeline_efficiency_end_to_end(tmp_path):
    """Pipeline 端到端跑通 efficiency 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"action": "efficiency"})
        assert "items" in output
        assert "annual_total" in output
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
        assert output["action"] == direct["action"]
        assert output["totals"]["annual_total_value"] == direct["totals"]["annual_total_value"]
        assert output["roi_metrics"]["npv"] == direct["roi_metrics"]["npv"]
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 透传到 engine.config。"""
    pipe = Pipeline(config={"db_path": str(tmp_path / "cm_04_cfg.db"),
                            "custom_key": "value"})
    pipe.engine.setup()
    try:
        assert pipe.engine.config.get("custom_key") == "value"
    finally:
        _close(pipe)


def test_pipeline_add_risk_persists(tmp_path):
    """Pipeline 跑 add_risk 后风险持久化到 DB。"""
    db_path = tmp_path / "cm_04_addrisk.db"
    pipe = Pipeline(config={"db_path": str(db_path)})
    pipe.engine.setup()
    try:
        pipe.run({
            "action": "add_risk",
            "risk": {"risk_id": "PIPE01", "name": "管道风险",
                     "baseline_prob": 0.06, "mitigated_prob": 0.01,
                     "avg_impact": 2000000, "risk_type": "custom"},
        })
    finally:
        _close(pipe)
    from modules.shared.portable_db import PortableDB
    with PortableDB(db_path) as db:
        rows = db.all("risks")
    ids = {r["risk_id"] for r in rows}
    assert "PIPE01" in ids
