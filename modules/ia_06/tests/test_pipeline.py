"""[IA-06] pipeline 端到端单测：Pipeline.run() 全流程跑通。

custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute + format_output。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ia_06.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


@pytest.fixture
def make_pipeline(tmp_path):
    """工厂：创建 Pipeline（db 隔离），自动关闭 engine.db。"""
    created = []

    def _factory(**overrides):
        cfg = {"db_path": str(tmp_path / "ia06_pipe.db"), "seed": 42}
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
    """sample_input 端到端跑通，输出含五维价值 + summary_text。"""
    pipe = make_pipeline()
    output = pipe.run(_sample())
    assert output["n_findings"] == 3
    assert "summary_text" in output
    assert "breakdown" in output
    assert output["total_cost"] == 480.0


def test_pipeline_config_propagates_seed(make_pipeline):
    """Pipeline config 中的 seed 透传到 engine（相同 seed → 相同 monte_carlo）。
    p2 在 p1.run 之后创建，确保 setup() 重置 random.seed。"""
    p1 = make_pipeline(seed=42)
    o1 = p1.run(_sample())
    p2 = make_pipeline(seed=42)  # setup 重置 random.seed(42)
    o2 = p2.run(_sample())
    assert o1["monte_carlo"] == o2["monte_carlo"]


def test_pipeline_passes_through_custom_stages(make_pipeline):
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["total_point"] == direct["total_point"]
    assert output["n_findings"] == direct["n_findings"]


def test_pipeline_empty_findings_handled(make_pipeline):
    """空 findings 经 Pipeline 透传后正常返回 total_point=0。"""
    pipe = make_pipeline()
    output = pipe.run({"findings": [], "total_cost": 100})
    assert output["total_point"] == 0
    assert output["n_findings"] == 0
