"""[CM-01] engine 单测：CUSUM / 规则引擎 / 滑动窗口 / 告警分级。

StreamingEngine 使用 PortableDB 持久化告警，每个测试用 tmp_path 隔离 db。
纯 stdlib 实现（CUSUM + z-score + 阈值规则）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cm_01.engine import StreamingEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> StreamingEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    eng = StreamingEngine(config={
        "db_path": str(tmp_path / "cm_01_engine.db"),
        **overrides,
    })
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 阈值规则
# ----------------------------------------------------------------------
def test_threshold_rule_triggers_alert(tmp_path):
    """operation_count > 50 触发 R03 告警。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "operation_count", "value": 60, "source": "System"},
            ],
        })
        alerts = result["alerts"]
        assert len(alerts) == 1
        a = alerts[0]
        assert a["rule_id"] == "R03"
        assert a["detector"] == "threshold"
        assert a["value"] == 60.0
        assert a["threshold"] == 50
        assert a["score"] == 25
        assert a["severity"] == "P3"
    finally:
        eng.close()


def test_large_transaction_triggers_multiple_thresholds(tmp_path):
    """超大额交易同时触发 R01(>1M) 和 R02(>5M)。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "transaction_amount", "value": 6000000, "source": "ERP"},
            ],
        })
        rule_ids = {a["rule_id"] for a in result["alerts"]}
        assert "R01" in rule_ids
        assert "R02" in rule_ids
    finally:
        eng.close()


def test_below_threshold_no_alert(tmp_path):
    """低于阈值不触发告警。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "operation_count", "value": 30, "source": "System"},
            ],
        })
        # operation_count=30 < 50，R03 不触发；单值 cusum 不触发
        threshold_alerts = [a for a in result["alerts"] if a["detector"] == "threshold"]
        assert len(threshold_alerts) == 0
    finally:
        eng.close()


# ----------------------------------------------------------------------
# CUSUM 均值漂移检测
# ----------------------------------------------------------------------
def test_cusum_detects_upward_shift(tmp_path):
    """CUSUM 检测均值上升漂移（用 metric_value 让只有 R05 匹配）。

    values=[5,5,5,5,5,6,7,8,9,10]，mean=6.5，后段持续高于均值 → cusum_up 触发。
    """
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "metric_value", "value": v, "source": "test"}
                for v in [5, 5, 5, 5, 5, 6, 7, 8, 9, 10]
            ],
        })
        cusum_alerts = [a for a in result["alerts"] if a["detector"] == "cusum_up"]
        assert len(cusum_alerts) >= 1
        assert cusum_alerts[0]["rule_id"] == "R05"
    finally:
        eng.close()


def test_cusum_no_alert_for_stable_data(tmp_path):
    """稳定数据（无漂移）不触发 CUSUM 告警。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "metric_value", "value": v, "source": "test"}
                for v in [10, 10, 10, 10, 10, 10, 10, 10, 10, 10]
            ],
        })
        cusum_alerts = [a for a in result["alerts"] if "cusum" in a["detector"]]
        assert len(cusum_alerts) == 0
    finally:
        eng.close()


# ----------------------------------------------------------------------
# z-score 异常检测
# ----------------------------------------------------------------------
def test_zscore_detects_outlier(tmp_path):
    """z-score 检测异常值（17 个值中最后 1 个偏离均值 > 3σ）。"""
    eng = _make_engine(tmp_path)
    try:
        # 16 个 100 + 1 个 1000，z = sqrt(16) = 4 > 3
        values = [100] * 16 + [1000]
        result = eng.execute({
            "metrics": [
                {"metric_name": "transaction_amount", "value": v, "source": "ERP"}
                for v in values
            ],
        })
        zscore_alerts = [a for a in result["alerts"] if a["detector"] == "zscore"]
        assert len(zscore_alerts) >= 1
        assert zscore_alerts[0]["rule_id"] == "R04"
        assert zscore_alerts[0]["deviation"] > 3.0
    finally:
        eng.close()


# ----------------------------------------------------------------------
# 趋势下降检测
# ----------------------------------------------------------------------
def test_trend_decline_detected(tmp_path):
    """交易频率下降 50% 以上触发 R06。"""
    eng = _make_engine(tmp_path)
    try:
        # 前 5 个均值 100，后 5 个均值 40，ratio=0.4 < 0.5
        values = [100, 100, 100, 100, 100, 40, 40, 40, 40, 40]
        result = eng.execute({
            "metrics": [
                {"metric_name": "transaction_count", "value": v, "source": "ERP"}
                for v in values
            ],
        })
        trend_alerts = [a for a in result["alerts"] if a["detector"] == "trend_decline"]
        assert len(trend_alerts) >= 1
        assert trend_alerts[0]["rule_id"] == "R06"
    finally:
        eng.close()


# ----------------------------------------------------------------------
# 告警分级 / 排序
# ----------------------------------------------------------------------
def test_alerts_sorted_by_score_desc(tmp_path):
    """告警按 score 降序排列。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        scores = [a["score"] for a in result["alerts"]]
        assert scores == sorted(scores, reverse=True)
    finally:
        eng.close()


def test_severity_grading(tmp_path):
    """告警 severity 按 score 分级（P0/P1/P2/P3）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for a in result["alerts"]:
            assert a["severity"] in ("P0", "P1", "P2", "P3")
            if a["score"] >= 80:
                assert a["severity"] == "P0"
            elif a["score"] >= 60:
                assert a["severity"] == "P1"
            elif a["score"] >= 40:
                assert a["severity"] == "P2"
            else:
                assert a["severity"] == "P3"
    finally:
        eng.close()


# ----------------------------------------------------------------------
# 滑动窗口统计
# ----------------------------------------------------------------------
def test_window_stats_computed(tmp_path):
    """每个 metric 的窗口统计含 mean/std/min/max/count。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "operation_count", "value": 10, "source": "S"},
                {"metric_name": "operation_count", "value": 20, "source": "S"},
                {"metric_name": "operation_count", "value": 30, "source": "S"},
            ],
        })
        stats = result["metrics"]["operation_count"]["stats"]
        assert stats["count"] == 3
        assert stats["mean"] == 20.0
        assert stats["min"] == 10.0
        assert stats["max"] == 30.0
        assert stats["std"] > 0
    finally:
        eng.close()


def test_window_size_limits_data(tmp_path):
    """window_size 限制窗口内数据条数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "metrics": [
                {"metric_name": "metric_value", "value": v, "source": "S"}
                for v in range(20)
            ],
            "window_size": 5,
        })
        assert result["metrics"]["metric_value"]["stats"]["count"] == 5
    finally:
        eng.close()


# ----------------------------------------------------------------------
# 汇总统计 / 持久化
# ----------------------------------------------------------------------
def test_summary_statistics(tmp_path):
    """summary 含告警总数、分级分布、P0/P1 计数、平均分。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["total_alerts"] == len(result["alerts"])
        assert "by_severity" in s
        assert set(s["by_severity"].keys()) == {"P0", "P1", "P2", "P3"}
        assert s["p0_p1_count"] == s["by_severity"]["P0"] + s["by_severity"]["P1"]
        assert s["avg_score"] >= 0
    finally:
        eng.close()


def test_alerts_persisted_to_db(tmp_path):
    """告警持久化到 PortableDB alerts 表。"""
    db_path = tmp_path / "cm_01_persist.db"
    eng = StreamingEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        eng.execute(_sample())
    finally:
        eng.close()
    # 用新连接读取，验证落盘
    with PortableDB(db_path) as db:
        rows = db.all("alerts")
    assert len(rows) >= 1
    for r in rows:
        assert "alert_id" in r
        assert "severity" in r
        assert "rule_id" in r
        assert isinstance(r["details"], dict)


def test_db_has_metrics_and_alerts_tables(tmp_path):
    """engine 初始化后 db 含 metrics + alerts 表。"""
    db_path = tmp_path / "cm_01_tables.db"
    eng = StreamingEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert "metrics" in tables
        assert "alerts" in tables
    finally:
        eng.close()


# ----------------------------------------------------------------------
# 空输入 / 边界
# ----------------------------------------------------------------------
def test_empty_metrics(tmp_path):
    """空 metrics 列表返回无告警。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"metrics": []})
        assert result["alerts"] == []
        assert result["summary"]["total_alerts"] == 0
    finally:
        eng.close()


def test_non_dict_input_raises(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute(["not", "a", "dict"])
    finally:
        eng.close()


def test_model_has_rules(tmp_path):
    """engine 加载后 model 含 7 条规则 + CUSUM 参数。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.model["rules"]) == 7
        assert eng.model["cusum_params"]["k"] == 0.5
        assert eng.model["cusum_params"]["h"] == 5.0
        assert eng.model["window_size"] == 100
    finally:
        eng.close()
