"""[TA-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ta_03 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果（含 results + summary）。
每个测试用 tmp_path 隔离 db，结束前关闭 engine.db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ta_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={"db_path": str(tmp_path / "ta_03_pipe.db"), **overrides})
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 results + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "results" in output
        assert "summary" in output
        assert len(output["results"]) == 4
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，输出含 invoice_level_summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "invoice_level_summary" in output["summary"]
        assert output["summary"]["total_transfer_amount"] == 569.0
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 透传到 engine.config。"""
    pipe = _make_pipeline(tmp_path, tax_rate=0.06)
    try:
        assert pipe.engine.config.get("tax_rate") == 0.06
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """空输入经 Pipeline 后返回零计数（不崩）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"invoices": [], "sales_allocation": {}})
        assert output["results"] == []
        assert output["summary"]["total_transfer_amount"] == 0
    finally:
        _close(pipe)


def test_pipeline_scenario_detection_through_pipeline(tmp_path):
    """场景识别经 Pipeline 仍生效。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        scenarios = {r["scenario"] for r in output["results"]}
        assert "集体福利" in scenarios
        assert "非正常损失" in scenarios
    finally:
        _close(pipe)
