"""[IA-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ia_02 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
引擎支持多 action，每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ia_02.pipeline import Pipeline
from modules.ia_02.engine import _ENTITIES_SCHEMA, _EDGES_SCHEMA
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path) -> Pipeline:
    db_path = tmp_path / "ia_02_pipe.db"
    # NOTE engine bug: entities/edges 表缺 PRIMARY KEY，预建规避（见 test_engine.py）。
    pre_db = PortableDB(db_path)
    pre_db.create_table("entities", {**_ENTITIES_SCHEMA, "entity_id": "TEXT PRIMARY KEY"})
    pre_db.create_table("edges", {**_EDGES_SCHEMA, "edge_id": "TEXT PRIMARY KEY"})
    pre_db.close()
    pipe = Pipeline(config={"db_path": str(db_path)})
    # NOTE pipeline bug: Pipeline 未调用 engine.setup()。
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_monitor_action(tmp_path):
    """monitor action 经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["action"] == "monitor"
        assert output["total_events"] == 3
        assert output["engine"] == "IA-02-ContinuousRiskMonitor"
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 为 pass-through，Pipeline 输出与 engine.execute 一致。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        direct = pipe.engine.execute(sample)
        assert output["total_events"] == direct["total_events"]
        assert output["alerts_generated"] == direct["alerts_generated"]
    finally:
        _close(pipe)


def test_pipeline_check_rule_action(tmp_path):
    """check_rule action 经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "action": "check_rule",
            "event": {"entity_id": "X", "amount": 2000000, "value": 2000000},
            "rule_id": "R001"
        })
        assert output["action"] == "check_rule"
        assert output["results"][0]["triggered"] is True
    finally:
        _close(pipe)


def test_pipeline_build_graph_action(tmp_path):
    """build_graph action 经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "action": "build_graph",
            "entities": [{"entity_id": "N1", "name": "节点1", "entity_type": "bu"}],
            "edges": []
        })
        assert output["action"] == "build_graph"
        assert output["entities_added"] == 1
    finally:
        _close(pipe)


def test_pipeline_preserves_engine_marker(tmp_path):
    """Pipeline 保留 engine + timestamp 标记（postprocess 产物）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["engine"] == "IA-02-ContinuousRiskMonitor"
        assert "timestamp" in output
    finally:
        _close(pipe)
