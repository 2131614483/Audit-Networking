"""[TA-04] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ta_04 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果（含 doc_sections + summary）。
每个测试用 tmp_path 隔离 db，结束前关闭 engine.db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ta_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={"db_path": str(tmp_path / "ta_04_pipe.db"), **overrides})
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 doc_sections + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "doc_sections" in output
        assert "summary" in output
        assert output["summary"]["comparable_count"] == 5
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，输出含 compliance_status / failed_checks。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["summary"]["compliance_status"] == "合规"
        assert "failed_checks" in output["summary"]
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
    """空输入经 Pipeline 后返回零计数（不崩）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"enterprise": {}, "comparables": []})
        assert output["summary"]["comparable_count"] == 0
    finally:
        _close(pipe)


def test_pipeline_doc_generation_through_pipeline(tmp_path):
    """文档生成经 Pipeline 仍生效（intro 含企业名）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "示例科技有限公司" in output["doc_sections"]["intro"]
    finally:
        _close(pipe)
