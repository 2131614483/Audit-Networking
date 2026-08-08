"""[TA-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ta_02 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果（含 matches + summary）。
每个测试用 tmp_path 隔离 db，结束前关闭 engine.db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ta_02.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={"db_path": str(tmp_path / "ta_02_pipe.db"), **overrides})
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 matches + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "matches" in output
        assert "summary" in output
        assert len(output["matches"]) == 3
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，输出含 high_confidence（postprocess 产物）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "high_confidence" in output["summary"]
        assert output["summary"]["invoice_count"] == 3
        for m in output["matches"]:
            assert "status" in m
            assert "overall_confidence" in m
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(tmp_path, match_threshold=0.8)
    try:
        assert pipe.engine.config.get("match_threshold") == 0.8
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """空输入经 Pipeline 后返回 invoice_count=0（不崩）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"invoices": [], "orders": [],
                           "receipts": [], "payments": []})
        assert output["matches"] == []
        assert output["summary"]["invoice_count"] == 0
    finally:
        _close(pipe)


def test_pipeline_full_match_through_pipeline(tmp_path):
    """四单齐全匹配经 Pipeline 仍生效。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        inv001 = next(m for m in output["matches"] if m["invoice_id"] == "INV-001")
        assert inv001["status"] == "四单齐全"
    finally:
        _close(pipe)
