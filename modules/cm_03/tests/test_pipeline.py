"""[CM-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cm_03 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
支持 recommend / generate_program / quality_check 等 action。
每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cm_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={
        "db_path": str(tmp_path / "cm_03_pipeline.db"),
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
def test_pipeline_recommend_end_to_end(tmp_path):
    """用 sample_input.json 端到端跑通 recommend 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["action"] == "recommend"
        assert "recommendations" in output
        assert len(output["recommendations"]) == 3
        assert "engine" in output
    finally:
        _close(pipe)


def test_pipeline_generate_program(tmp_path):
    """Pipeline 端到端跑通 generate_program 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01", "M02"],
        })
        assert output["action"] == "generate_program"
        assert "program" in output
        assert "program_id" in output
        assert "quality_preview" in output
    finally:
        _close(pipe)


def test_pipeline_quality_check(tmp_path):
    """Pipeline 端到端跑通 quality_check 动作。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "action": "quality_check",
            "scenario": "采购付款",
            "program": {
                "program_name": "测试程序",
                "methods_applied": ["实时交易监控"],
                "check_rules": [{"rule": "金额检查"}, {"rule": "频率检查"}],
                "alert_settings": {"green": "<50"},
                "data_sources": ["ERP", "采购系统"],
                "handling_flow": "自动处理+人工复核",
            },
        })
        assert output["action"] == "quality_check"
        assert "dimensions" in output
        assert "total_score" in output
        assert "grade" in output
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
        assert len(output["recommendations"]) == len(direct["recommendations"])
        assert output["top_method"]["method_id"] == direct["top_method"]["method_id"]
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 透传到 engine.config。"""
    pipe = Pipeline(config={"db_path": str(tmp_path / "cm_03_cfg.db"),
                            "custom_key": "value"})
    pipe.engine.setup()
    try:
        assert pipe.engine.config.get("custom_key") == "value"
    finally:
        _close(pipe)


def test_pipeline_persists_program_to_db(tmp_path):
    """Pipeline 跑 generate_program 后程序持久化到 DB。"""
    db_path = tmp_path / "cm_03_persist.db"
    pipe = Pipeline(config={"db_path": str(db_path)})
    pipe.engine.setup()
    try:
        pipe.run({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01"],
        })
    finally:
        _close(pipe)
    from modules.shared.portable_db import PortableDB
    with PortableDB(db_path) as db:
        rows = db.all("programs")
    assert len(rows) >= 1
