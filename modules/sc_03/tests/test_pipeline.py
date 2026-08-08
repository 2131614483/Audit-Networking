"""[SC-03] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

pytest 风格：每个测试用 tmp_path 隔离 PortableDB，pipe fixture 在收尾时关闭
engine.db 句柄，避免 Windows 下 tmp_path 清理触发 PermissionError。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.sc_03.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _expected() -> dict:
    return json.loads((_FIXTURES / "expected_output.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    config = {"db_path": str(tmp_path / "sc_03_pipeline.db")}
    config.update(overrides)
    return Pipeline(config=config)


@pytest.fixture
def pipe(tmp_path):
    """构造隔离 db 的 pipeline，收尾关闭 engine.db 句柄。"""
    p = _make_pipeline(tmp_path)
    yield p
    p.engine.close()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(pipe):
    """用 sample_input.json 端到端跑通，输出含 suppliers/recommendations/statistics。"""
    output = pipe.run(_sample())

    assert output["status"] == "ok"
    assert output["module"] == "SC-03"
    for key in ("suppliers", "recommendations", "statistics"):
        assert key in output


def test_pipeline_supplier_count_and_sorting(pipe):
    """输出供应商数与输入一致，且按 overall_risk_score 降序。"""
    sample = _sample()
    output = pipe.run(sample)

    assert len(output["suppliers"]) == len(sample["suppliers"])
    assert output["statistics"]["supplier_count"] == len(sample["suppliers"])
    scores = [s["overall_risk_score"] for s in output["suppliers"]]
    assert scores == sorted(scores, reverse=True)


def test_pipeline_statistics_complete(pipe):
    """统计字段完整，alerts_by_level 与 risk_tier_distribution 各级之和 = 供应商数。"""
    sample = _sample()
    output = pipe.run(sample)

    stats = output["statistics"]
    assert stats["supplier_count"] == len(sample["suppliers"])
    for key in ("avg_risk_score", "alerts_by_level", "risk_tier_distribution",
                "rule_summary", "thresholds"):
        assert key in stats
    for lv in ("紧急", "高", "中", "低"):
        assert lv in stats["alerts_by_level"]
    for tier in ("critical", "high", "medium", "low", "info"):
        assert tier in stats["risk_tier_distribution"]

    n = stats["supplier_count"]
    assert sum(stats["alerts_by_level"].values()) == n
    assert sum(stats["risk_tier_distribution"].values()) == n


def test_pipeline_matches_expected_output(pipe):
    """端到端输出与 expected_output.json 关键字段一致。"""
    sample = _sample()
    output = pipe.run(sample)
    expected = _expected()

    assert output["status"] == expected["status"]
    assert output["module"] == expected["module"]
    assert len(output["suppliers"]) == len(expected["suppliers"])
    # 供应商顺序与 expected 一致（按 risk 降序）
    for got, exp in zip(output["suppliers"], expected["suppliers"]):
        assert got["supplier_id"] == exp["supplier_id"]
        assert got["alert_level"] == exp["alert_level"]
        assert got["risk_tier"] == exp["risk_tier"]
    assert output["statistics"]["supplier_count"] == expected["statistics"]["supplier_count"]
    assert output["statistics"]["alerts_by_level"] == expected["statistics"]["alerts_by_level"]
    assert (output["statistics"]["risk_tier_distribution"]
            == expected["statistics"]["risk_tier_distribution"])


def test_pipeline_custom_rules_critical_alert_for_sup_b(pipe):
    """SUP-B 多指标异常 → 触发 critical_alert 关键告警，升级到「紧急」。"""
    output = pipe.run(_sample())

    sup_b = next(s for s in output["suppliers"] if s["supplier_id"] == "SUP-B")
    assert sup_b["critical_alert"] is True
    assert sup_b["needs_immediate_review"] is True
    assert sup_b["trend_escalated"] is True
    assert sup_b["alert_level"] == "紧急"
    assert len(sup_b["rule_adjustments"]) == 3


def test_pipeline_custom_rules_summary(pipe):
    """rule_summary 统计非空，sample 至少 1 个即时复核 / 关键告警 / 趋势升级。"""
    output = pipe.run(_sample())

    rs = output["statistics"]["rule_summary"]
    for key in ("trend_escalated", "immediate_review", "critical_alert_triggered"):
        assert key in rs
    assert rs["immediate_review"] >= 1
    assert rs["critical_alert_triggered"] >= 1
    assert rs["trend_escalated"] >= 1
    assert len(output["recommendations"]) > 0


# ----------------------------------------------------------------------
# 配置透传
# ----------------------------------------------------------------------
def test_pipeline_config_threshold_propagates(tmp_path):
    """Pipeline config 中的 threshold 透传到 apply_thresholds（统计 thresholds 反映）。"""
    pipe = _make_pipeline(
        tmp_path,
        threshold={"critical": 0.9, "high": 0.7, "medium": 0.5, "low": 0.3},
    )
    try:
        output = pipe.run(_sample())
    finally:
        pipe.engine.close()

    thresholds = output["statistics"]["thresholds"]
    assert thresholds["critical"] == 0.9
    assert thresholds["high"] == 0.7
    assert thresholds["medium"] == 0.5
    assert thresholds["low"] == 0.3


# ----------------------------------------------------------------------
# PortableDB 持久化
# ----------------------------------------------------------------------
def test_pipeline_persists_to_portable_db(tmp_path):
    """Pipeline 把指标时序与预警记录持久化到 PortableDB。"""
    db_path = tmp_path / "sc_03_pipeline.db"
    pipe = _make_pipeline(tmp_path)
    sample = _sample()
    try:
        output = pipe.run(sample)
    finally:
        pipe.engine.close()  # 释放 db 句柄后再以只读方式打开校验

    expected_metrics = sum(
        sum(len(v) for v in s.get("metrics", {}).values())
        for s in sample["suppliers"]
    )
    with PortableDB(db_path) as db:
        assert db.count("supplier_metrics") == expected_metrics
        total_alerts = sum(len(s.get("alerts", [])) for s in output["suppliers"])
        no_alert_sups = sum(1 for s in output["suppliers"] if not s.get("alerts"))
        assert db.count("risk_alerts") == total_alerts + no_alert_sups
        rows = db.all("risk_alerts")

    assert len(rows) > 0
    for r in rows:
        assert "alert_level" in r
        assert "alert_score" in r
        assert "details" in r


def test_pipeline_idempotent_rerun(pipe):
    """重复 run 不会累积数据（每次清空重写）。"""
    sample = _sample()
    pipe.run(sample)
    pipe.run(sample)

    db_path = Path(pipe.engine.config["db_path"])
    expected_metrics = sum(
        sum(len(v) for v in s.get("metrics", {}).values())
        for s in sample["suppliers"]
    )
    with PortableDB(db_path) as db:
        assert db.count("supplier_metrics") == expected_metrics


# ----------------------------------------------------------------------
# 空输入
# ----------------------------------------------------------------------
def test_pipeline_empty_input(pipe):
    """空输入 → status ok、supplier_count=0。"""
    output = pipe.run({"suppliers": []})
    assert output["status"] == "ok"
    assert output["statistics"]["supplier_count"] == 0
    assert output["suppliers"] == []
