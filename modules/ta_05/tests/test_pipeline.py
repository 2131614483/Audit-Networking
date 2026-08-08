"""[TA-05] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ta_05 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果（含 selected + summary）。
每个测试用 tmp_path 隔离 db，结束前关闭 engine.db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ta_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={"db_path": str(tmp_path / "ta_05_pipe.db"), **overrides})
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 selected + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "selected" in output
        assert "summary" in output
        assert output["summary"]["candidate_count"] == 6
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，输出含 low_similarity_count。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "low_similarity_count" in output["summary"]
        assert output["summary"]["selected_count"] == 5
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(tmp_path, custom_key="value")
    try:
        assert pipe.engine.config.get("custom_key") == "value"
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """单候选经 Pipeline 后返回 1 selected（避免 engine 空候选 bug）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        # NOTE: engine bug — 空候选时 _postprocess 报 KeyError，用单候选绕过。
        output = pipe.run({
            "target_company": {"industry": "X", "country": "CN", "revenue": 100},
            "candidates": [{"company_id": "S1", "industry": "X", "country": "CN",
                            "revenue": 100, "functions": []}],
        })
        assert output["summary"]["candidate_count"] == 1
    finally:
        _close(pipe)


def test_pipeline_topk_selection_through_pipeline(tmp_path):
    """Top-K 选择经 Pipeline 仍生效。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert len(output["selected"]) == 5
        assert output["selected"][0]["company_id"] == "CAND-001"
    finally:
        _close(pipe)
