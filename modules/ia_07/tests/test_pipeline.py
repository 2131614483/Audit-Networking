"""[IA-07] pipeline 端到端单测：Pipeline.run() 全流程跑通。

custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute + format_output。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from modules.ia_07.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _ts(days_offset: float) -> str:
    return (datetime.now() + timedelta(days=days_offset)).isoformat()


@pytest.fixture
def make_pipeline(tmp_path):
    """工厂：创建 Pipeline（db 隔离），自动关闭 engine.db。"""
    created = []

    def _factory(**overrides):
        cfg = {"db_path": str(tmp_path / "ia07_pipe.db")}
        cfg.update(overrides)
        p = Pipeline(config=cfg)
        p.engine.setup()
        created.append(p)
        return p

    yield _factory
    for p in created:
        if getattr(p.engine, "db", None):
            p.engine.db.close()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(make_pipeline):
    """sample_input 端到端跑通，输出含 tasks + total。"""
    pipe = make_pipeline()
    output = pipe.run(_sample())
    assert output["total"] == len(_sample())
    assert "tasks" in output
    assert "generated_at" in output


def test_pipeline_single_task(make_pipeline):
    """单任务 dict 经 Pipeline 也能跑通。"""
    pipe = make_pipeline()
    output = pipe.run({
        "task_id": "P1", "created_at": _ts(-10), "deadline": _ts(20),
        "severity": "重要", "issue_type": "流程缺陷",
    })
    assert output["total"] == 1
    assert output["tasks"][0]["task_id"] == "P1"


def test_pipeline_passes_through_custom_stages(make_pipeline):
    """custom 均为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["total"] == direct["total"]
    assert output["tasks"][0]["task_id"] == direct["tasks"][0]["task_id"]


def test_pipeline_config_propagates_db_path(make_pipeline):
    """config 中的 db_path 透传到 engine。"""
    pipe = make_pipeline()
    assert pipe.engine.config["db_path"].endswith("ia07_pipe.db")
