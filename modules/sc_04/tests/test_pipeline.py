"""[SC-04] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

pytest 风格：每个测试用 tmp_path 隔离 PortableDB，pipe fixture 在收尾时关闭
engine.db 句柄，避免 Windows 下 tmp_path 清理触发 PermissionError。
可复现性测试显式创建并关闭两个独立 pipeline。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.sc_04.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _expected() -> dict:
    return json.loads((_FIXTURES / "expected_output.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    config = {
        "threshold": {"critical": 0.85, "high": 0.70, "medium": 0.40},
        "db_path": str(tmp_path / "sc_04_pipeline.db"),
    }
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
    """用 sample_input.json 端到端跑通，输出含标记交易 + 统计 + 建议。"""
    output = pipe.run(_sample())

    assert output["status"] == "ok"
    assert output["module"] == "SC-04"
    for key in ("flagged_transactions", "statistical_details",
                "rule_summary", "recommendations", "statistics"):
        assert key in output


def test_pipeline_statistics_complete(pipe):
    """统计含订单数/异常数/严重程度分布，各级之和 = 订单数。"""
    sample = _sample()
    output = pipe.run(sample)

    stats = output["statistics"]
    assert stats["order_count"] == len(sample["orders"])
    dist = stats["severity_distribution"]
    for lv in ("critical", "high", "medium", "low"):
        assert lv in dist
    assert (dist["critical"] + dist["high"] + dist["medium"] + dist["low"]
            == stats["order_count"])


def test_pipeline_detects_outliers(pipe):
    """sample 含注入离群 → 标记交易非空且含 PO-0012(9500)/PO-0021(900)。"""
    output = pipe.run(_sample())

    flagged = output["flagged_transactions"]
    assert len(flagged) > 0
    ids = {f["order_id"] for f in flagged}
    assert "PO-0012" in ids
    assert "PO-0021" in ids


def test_pipeline_matches_expected_output(pipe):
    """pipeline 输出与 expected_output.json 关键字段一致。"""
    output = pipe.run(_sample())
    expected = _expected()

    assert output["status"] == expected["status"]
    assert output["module"] == expected["module"]
    assert output["statistics"]["order_count"] == expected["statistics"]["order_count"]
    assert output["statistics"]["anomaly_count"] == expected["statistics"]["anomaly_count"]
    assert (output["statistics"]["severity_distribution"]
            == expected["statistics"]["severity_distribution"])
    assert len(output["flagged_transactions"]) == len(expected["flagged_transactions"])


def test_pipeline_custom_rules_applied(pipe):
    """业务规则：价格离群 / 单一来源核查 / 高价采购三类标记生效。"""
    output = pipe.run(_sample())

    by_id = {f["order_id"]: f for f in output["flagged_transactions"]}
    # 规则1：高价离群 PO-0012/PO-0021/PO-0013 被标记 price_outlier
    assert by_id["PO-0012"]["price_outlier"] is True
    assert by_id["PO-0021"]["price_outlier"] is True
    assert by_id["PO-0013"]["price_outlier"] is True
    # 规则2：电缆单一来源 S008 且价格高于均价 → sole_source_investigate
    assert by_id["PO-0027"]["sole_source_investigate"] is True
    # 规则3：价格高于品类中位数基准 15% → overcharge
    assert by_id["PO-0012"]["overcharge"] is True
    assert by_id["PO-0021"]["overcharge"] is True
    rs = output["rule_summary"]
    assert rs["price_outlier"] > 0
    assert rs["sole_source_investigate"] > 0
    assert rs["overcharge"] > 0
    assert len(output["recommendations"]) > 0


# ----------------------------------------------------------------------
# 配置透传
# ----------------------------------------------------------------------
def test_pipeline_config_threshold_propagates(tmp_path):
    """Pipeline config 中的 threshold 透传到 apply_thresholds（统计 thresholds 反映）。"""
    pipe = _make_pipeline(
        tmp_path,
        threshold={"critical": 0.9, "high": 0.75, "medium": 0.5},
    )
    try:
        output = pipe.run(_sample())
    finally:
        pipe.engine.close()

    thresholds = output["statistical_details"]["thresholds"]
    assert thresholds["critical"] == 0.9
    assert thresholds["high"] == 0.75
    assert thresholds["medium"] == 0.5


# ----------------------------------------------------------------------
# PortableDB 持久化
# ----------------------------------------------------------------------
def test_pipeline_persists_to_portable_db(tmp_path):
    """Pipeline 把订单与异常检测结果持久化到 PortableDB。"""
    db_path = tmp_path / "sc_04_pipeline.db"
    pipe = _make_pipeline(tmp_path)
    sample = _sample()
    try:
        pipe.run(sample)
    finally:
        pipe.engine.close()  # 释放 db 句柄后再以只读方式打开校验

    with PortableDB(db_path) as db:
        assert db.count("purchase_orders") == len(sample["orders"])
        rows = db.all("anomaly_results")

    assert len(rows) == len(sample["orders"])
    for r in rows:
        assert isinstance(r["indicators"], dict)
        assert r["anomaly_level"] in ("高", "中", "低")


# ----------------------------------------------------------------------
# 可复现性（IsolationForest 固定种子 42）
# ----------------------------------------------------------------------
def test_pipeline_reproducible_same_input(tmp_path):
    """相同输入 → 两个独立 pipeline 产出相同的异常计数/分布/标记数。"""
    sample = _sample()

    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"
    run1_dir.mkdir()
    run2_dir.mkdir()
    pipe1 = _make_pipeline(run1_dir)
    pipe2 = _make_pipeline(run2_dir)
    try:
        out1 = pipe1.run(sample)
        out2 = pipe2.run(sample)
    finally:
        pipe1.engine.close()
        pipe2.engine.close()

    assert out1["statistics"]["anomaly_count"] == out2["statistics"]["anomaly_count"]
    assert (out1["statistics"]["severity_distribution"]
            == out2["statistics"]["severity_distribution"])
    assert len(out1["flagged_transactions"]) == len(out2["flagged_transactions"])


# ----------------------------------------------------------------------
# 空输入
# ----------------------------------------------------------------------
def test_pipeline_empty_input(pipe):
    """空订单 → status ok、order_count=0、无标记交易。"""
    output = pipe.run({"orders": []})
    assert output["status"] == "ok"
    assert output["statistics"]["order_count"] == 0
    assert output["flagged_transactions"] == []
