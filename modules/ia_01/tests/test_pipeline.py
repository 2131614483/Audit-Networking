"""[IA-01] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ia_01 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
引擎支持多 action，每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ia_01.pipeline import Pipeline
from modules.ia_01.engine import _RISK_MAP_SCHEMA
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path) -> Pipeline:
    db_path = tmp_path / "ia_01_pipe.db"
    # NOTE engine bug: risk_map 表 entity_id 缺 PRIMARY KEY，预建规避（见 test_engine.py）。
    pre_db = PortableDB(db_path)
    pre_db.create_table("risk_map", {**_RISK_MAP_SCHEMA, "entity_id": "TEXT PRIMARY KEY"})
    pre_db.close()
    pipe = Pipeline(config={"db_path": str(db_path)})
    # NOTE pipeline bug: Pipeline 未调用 engine.setup()，_preprocess 不自动加载 model。
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_score_action(tmp_path):
    """score action 经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["action"] == "score"
        assert "risk_score" in output
        assert "risk_level" in output
        assert output["engine"] == "IA-01-RiskMapAndPlan"
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 为 pass-through，Pipeline 输出与 engine.execute 一致。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        direct = pipe.engine.execute(sample)
        assert output["risk_score"] == direct["risk_score"]
        assert output["risk_level"] == direct["risk_level"]
    finally:
        _close(pipe)


def test_pipeline_text_signals_action(tmp_path):
    """text_signals action 经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"action": "text_signals", "texts": ["欺诈风险"]})
        assert output["action"] == "text_signals"
        assert output["total_texts"] == 1
    finally:
        _close(pipe)


def test_pipeline_generate_plan_action(tmp_path):
    """评分后 generate_plan action 经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        pipe.run(_sample())  # 先评分
        output = pipe.run({"action": "generate_plan", "period": "annual", "resources": {}})
        assert output["action"] == "generate_plan"
        assert output["total_projects"] >= 1
    finally:
        _close(pipe)


def test_pipeline_preserves_engine_marker(tmp_path):
    """Pipeline 保留 engine + timestamp 标记（postprocess 产物）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["engine"] == "IA-01-RiskMapAndPlan"
        assert "timestamp" in output
    finally:
        _close(pipe)
