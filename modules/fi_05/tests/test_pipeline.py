"""[FI-05] pipeline 端到端单测：Pipeline.run() 全流程跑通。

fi_05 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 changes / summary）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.fi_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    return Pipeline(config={
        "db_path": str(tmp_path / "fi_05_pipeline.db"),
        **overrides,
    })


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 changes + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "changes" in output
        assert "summary" in output
        assert output["summary"]["regulation_count"] == 2
        assert "urgency" in output["summary"]
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
        assert output["summary"]["regulation_count"] == direct["summary"]["regulation_count"]
        assert len(output["changes"]) == len(direct["changes"])
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 中的 db_path 透传到 engine。"""
    pipe = _make_pipeline(tmp_path, threshold={"confidence": 0.9})
    try:
        assert pipe.engine.config.get("db_path") == str(tmp_path / "fi_05_pipeline.db")
        assert pipe.engine.config.get("threshold") == {"confidence": 0.9}
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """空法规列表经 Pipeline 透传后仍返回零汇总。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"new_regulations": [], "current_regulations": []})
        assert output["changes"] == []
        assert output["summary"]["regulation_count"] == 0
    finally:
        _close(pipe)


def test_pipeline_urgency_present(tmp_path):
    """端到端后 summary 含 urgency（后处理产物）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert output["summary"]["urgency"] in ("紧急", "尽快", "正常")
    finally:
        _close(pipe)


def test_pipeline_new_regulation_detected(tmp_path):
    """端到端后新增法规被正确检测。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "new_regulations": [{
                "reg_id": "NEW1", "title": "全新法规",
                "content": "一、会计政策：企业应当采用合理的会计政策。",
            }],
            "current_regulations": [],
        })
        assert output["changes"][0]["change_type"] == "新增法规"
    finally:
        _close(pipe)
