"""[CM-01] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_01 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
每个测试用 tmp_path 隔离 db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cm_01.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path) -> Pipeline:
    """构造隔离 db 的 pipeline。"""
    return Pipeline(config={"db_path": str(tmp_path / "cm_01_pipeline.db")})


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 alerts + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "alerts" in output
        assert "summary" in output
        assert output["summary"]["total_alerts"] == len(output["alerts"])
        # sample 含 3 个超阈值指标，至少触发 3 个告警
        assert output["summary"]["total_alerts"] >= 3
    finally:
        pipe.engine.close()


def test_pipeline_threshold_alert(tmp_path):
    """Pipeline 透传后 threshold 规则正常触发。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "metrics": [{"metric_name": "operation_count", "value": 60, "source": "S"}],
        })
        threshold_alerts = [a for a in output["alerts"] if a["detector"] == "threshold"]
        assert len(threshold_alerts) == 1
        assert threshold_alerts[0]["rule_id"] == "R03"
    finally:
        pipe.engine.close()


def test_pipeline_empty_metrics(tmp_path):
    """空 metrics 经 Pipeline 透传后无告警。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"metrics": []})
        assert output["alerts"] == []
        assert output["summary"]["total_alerts"] == 0
    finally:
        pipe.engine.close()


def test_pipeline_persists_alerts_to_db(tmp_path):
    """Pipeline 把告警持久化到 PortableDB alerts 表。"""
    db_path = tmp_path / "cm_01_pipeline.db"
    pipe = Pipeline(config={"db_path": str(db_path)})
    try:
        pipe.run(_sample())
    finally:
        pipe.engine.close()
    with PortableDB(db_path) as db:
        rows = db.all("alerts")
    assert len(rows) >= 1


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom 阶段为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        pipe.engine.setup()
        direct = pipe.engine.execute(sample)
        assert output["summary"]["total_alerts"] == direct["summary"]["total_alerts"]
        assert len(output["alerts"]) == len(direct["alerts"])
    finally:
        pipe.engine.close()
