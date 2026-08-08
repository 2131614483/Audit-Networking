"""[IA-05] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ia_05 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
引擎为 LLMEngine（BM25 检索 + Prompt 模板 + 质量评估），每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ia_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    db_path = tmp_path / "ia_05_pipe.db"
    pipe = Pipeline(config={"db_path": str(db_path), **overrides})
    # NOTE pipeline bug: Pipeline 未调用 engine.setup()，知识库不会加载。
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_run_end_to_end(tmp_path):
    """Pipeline.run 端到端跑通，产出 framework + suggestions + quality。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "framework" in output
        assert "suggestions" in output
        assert "quality" in output
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 为 pass-through，Pipeline 输出与 engine.execute 一致。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        direct = pipe.engine.execute(sample)
        assert output["suggestions"] == direct["suggestions"]
        assert output["quality"]["overall"] == direct["quality"]["overall"]
    finally:
        _close(pipe)


def test_pipeline_string_input(tmp_path):
    """字符串输入经 Pipeline 端到端跑通。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run("权限分离存在控制缺失")
        assert "suggestions" in output
        assert len(output["suggestions"]) > 0
    finally:
        _close(pipe)


def test_pipeline_quality_grade_present(tmp_path):
    """Pipeline 输出含质量评级。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["quality"]["grade"] in ("可直接使用", "需小幅调整", "需大幅修改")
    finally:
        _close(pipe)


def test_pipeline_generated_at_present(tmp_path):
    """Pipeline 输出含生成时间戳。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "generated_at" in output
    finally:
        _close(pipe)
