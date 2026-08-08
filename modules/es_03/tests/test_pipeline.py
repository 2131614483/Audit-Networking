"""[ES-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

es_03 的 Pipeline 串联：collect(归一化) → engine.execute → apply_thresholds(分级)
→ apply_custom_rules(违规标记) → format_output(对外报告)。
输出结构与 engine 直跑不同，含 status / module / roi_reports(带 impact_level) / statistics。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.es_03.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    return Pipeline(config=overrides)


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 status/module/roi_reports/statistics。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert output["status"] == "ok"
    assert output["module"] == "ES-03"
    assert len(output["roi_reports"]) == 4
    assert "statistics" in output
    assert output["statistics"]["roi_count"] == 4


def test_pipeline_format_output_adds_impact_fields():
    """format_output 为每个 ROI 添加 impact_score / impact_level。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    for r in output["roi_reports"]:
        assert "impact_score" in r
        assert "impact_level" in r
        assert r["impact_level"] in {"normal", "warning", "critical"}
        assert 0.0 <= r["impact_score"] <= 1.0


def test_pipeline_statistics_has_impact_distribution():
    """statistics.impact_distribution 含 normal/warning/critical 三档计数。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    dist = output["statistics"]["impact_distribution"]
    assert set(dist.keys()) == {"normal", "warning", "critical"}
    assert sum(dist.values()) == 4


def test_pipeline_config_threshold_propagates():
    """Pipeline config.threshold 透传到 engine.config。"""
    pipe = _make_pipeline(threshold={"normal": 0.5, "warning": 0.8})
    assert pipe.engine.config.get("threshold") == {"normal": 0.5, "warning": 0.8}


def test_pipeline_empty_input_handled():
    """空 ROI 列表经 Pipeline 后返回空 roi_reports + 零计数。"""
    pipe = _make_pipeline()
    output = pipe.run({"rois": []})
    assert output["status"] == "ok"
    assert output["roi_reports"] == []
    assert output["statistics"]["roi_count"] == 0


def test_pipeline_collects_rois_from_rois_key():
    """Pipeline._collect 从 dict 的 rois 键提取 ROI 列表。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample["rois"])
    # ROI 数量一致
    assert len(output["roi_reports"]) == len(direct["roi_reports"])
