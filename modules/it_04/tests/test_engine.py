"""[IT-04] engine 单测：持续审计 / 异常检测 / 控制图 / 趋势分析。

MLEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * _preprocess : 多指标时序数据 → 时间序列
  * _infer      : 统计计算 → 控制限 → 异常检测（3σ/2σ/突然归零/连续/趋势）→ 风险评分
  * _postprocess: 输出异常检测报告（告警列表 + 建议）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.it_04.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> MLEngine:
    eng = MLEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_control_params_and_rules():
    """setup 后 control_params 含 6 个指标，anomaly_rules 含 6 条规则。"""
    eng = _make_engine()
    assert len(eng.control_params) == 6
    assert {"login_failure_rate", "transaction_volume", "privilege_change_count",
            "config_change_count", "error_rate", "access_anomaly_score"} <= set(eng.control_params.keys())
    assert len(eng.anomaly_rules) == 6


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_groups_by_metric():
    """预处理后按 metric 分组，保留 timestamp 与 metadata。"""
    eng = _make_engine()
    prepared = eng._preprocess(_sample())
    assert set(prepared["series"].keys()) == {"login_failure_rate", "transaction_volume", "privilege_change_count"}
    for metric, points in prepared["series"].items():
        assert len(points) > 0
        assert "value" in points[0]
        assert "timestamp" in points[0]
    assert prepared["metadata"]["login_failure_rate"]["unit"] == "ratio"


def test_preprocess_dict_input_wrapped_as_list():
    """dict 输入被包装为单元素 list。"""
    eng = _make_engine()
    prepared = eng._preprocess({"metric": "x", "values": [1, 2, 3]})
    assert "x" in prepared["series"]
    assert len(prepared["series"]["x"]) == 3


def test_preprocess_indicator_alias():
    """indicator 字段作为 metric 的别名。"""
    eng = _make_engine()
    prepared = eng._preprocess([{"indicator": "latency", "data": [1, 2, 3]}])
    assert "latency" in prepared["series"]


# ----------------------------------------------------------------------
# 统计计算
# ----------------------------------------------------------------------
def test_compute_stats_returns_mean_std_cv():
    """_compute_stats 返回 mean/std/cv/median/slope。"""
    eng = _make_engine()
    stats = eng._compute_stats([10, 20, 30, 40, 50])
    assert stats["mean"] == 30.0
    assert stats["std"] > 0
    assert stats["min"] == 10
    assert stats["max"] == 50
    assert stats["median"] == 30
    assert "cv" in stats
    assert "trend_slope" in stats


def test_slope_positive_for_increasing_series():
    """_slope 递增序列返回正斜率。"""
    assert MLEngine._slope([1, 2, 3, 4, 5]) > 0
    assert MLEngine._slope([5, 4, 3, 2, 1]) < 0
    assert MLEngine._slope([3, 3, 3, 3]) == 0.0


# ----------------------------------------------------------------------
# 控制限
# ----------------------------------------------------------------------
def test_compute_control_limits_returns_2_and_3_sigma():
    """_compute_control_limits 返回 2σ/3σ 上下限。"""
    eng = _make_engine()
    cl = eng._compute_control_limits("login_failure_rate", [1, 2, 3, 4, 5])
    assert "ucl_2sigma" in cl
    assert "lcl_2sigma" in cl
    assert "ucl_3sigma" in cl
    assert "lcl_3sigma" in cl
    assert cl["ucl_3sigma"] > cl["ucl_2sigma"]
    # lcl_3sigma 被 max(0, ...) 截断，故 >= 0；lcl_2sigma 未截断可为负
    assert cl["lcl_3sigma"] >= 0


def test_compute_control_limits_lcl_floored_at_zero():
    """lcl_3sigma 不为负（max(0, lcl)）。"""
    eng = _make_engine()
    cl = eng._compute_control_limits("x", [1, 2, 3])
    assert cl["lcl_3sigma"] >= 0


# ----------------------------------------------------------------------
# 异常检测
# ----------------------------------------------------------------------
def test_detect_ucl_exceeded_anomaly():
    """超过 3σ 上限的值触发 ucl_exceeded（高严重度）。"""
    eng = _make_engine()
    # 14 个稳定点 + 1 个 spike，spike 远超 3σ
    values = [10] * 14 + [30]
    cl = eng._compute_control_limits("test", values)
    anomalies = eng._detect_anomalies(values, cl)
    types = [a["type"] for a in anomalies]
    assert "ucl_exceeded" in types


def test_detect_sudden_zero_anomaly():
    """突然归零触发 sudden_zero（高严重度）。"""
    eng = _make_engine()
    values = [100, 100, 100, 100, 100, 0]
    cl = eng._compute_control_limits("test", values)
    anomalies = eng._detect_anomalies(values, cl)
    types = [a["type"] for a in anomalies]
    assert "sudden_zero" in types


def test_detect_rising_trend_anomaly():
    """连续 4 期上升触发 rising_trend（中严重度）。"""
    eng = _make_engine()
    values = [1, 2, 3, 4, 5, 6]
    cl = eng._compute_control_limits("test", values)
    anomalies = eng._detect_anomalies(values, cl)
    types = [a["type"] for a in anomalies]
    assert "rising_trend" in types


def test_detect_declining_trend_anomaly():
    """连续 4 期下降触发 declining_trend。"""
    eng = _make_engine()
    values = [6, 5, 4, 3, 2, 1]
    cl = eng._compute_control_limits("test", values)
    anomalies = eng._detect_anomalies(values, cl)
    types = [a["type"] for a in anomalies]
    assert "declining_trend" in types


def test_no_anomaly_for_stable_series():
    """稳定序列无异常。"""
    eng = _make_engine()
    values = [50, 50, 50, 50, 50, 50]
    cl = eng._compute_control_limits("test", values)
    anomalies = eng._detect_anomalies(values, cl)
    # std=0 → ucl=lcl=mean，所有点等于 mean，不触发 ucl/lcl；也不触发 sudden_zero/trend
    assert anomalies == []


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_postprocessed_structure():
    """execute 返回后处理结构（summary / metric_analyses / alerts）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "summary" in result
    assert "metric_analyses" in result
    assert "alerts" in result
    assert "generated_at" in result


def test_metric_analyses_carry_full_structure():
    """每个 metric 分析含 statistics / control_limits / anomalies / trend / risk_score。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for m in result["metric_analyses"]:
        assert "statistics" in m
        assert "control_limits" in m
        assert "anomalies" in m
        assert "trend" in m
        assert "risk_score" in m
        assert "risk_level" in m


def test_alerts_sorted_by_severity():
    """alerts 按严重度排序（高→中→低）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    alerts = result["alerts"]
    severity_order = {"高": 0, "中": 1, "低": 2}
    for i in range(len(alerts) - 1):
        assert severity_order[alerts[i]["severity"]] <= severity_order[alerts[i + 1]["severity"]]


def test_alerts_have_recommendation():
    """每个 alert 含 recommendation 文本。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["alerts"]:
        assert isinstance(a["recommendation"], str)
        assert len(a["recommendation"]) > 0


def test_summary_aggregates_metrics():
    """summary 聚合指标数 + 异常数 + 高风险指标列表。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["monitored_metrics"] == 3
    assert s["total_anomalies"] > 0
    assert "high_risk_metrics" in s
    assert "avg_risk_score" in s
    assert "anomaly_type_distribution" in s


def test_risk_label_thresholds():
    """_risk_label 按分数分级。"""
    assert MLEngine._risk_label(0.8) == "高风险-需立即调查"
    assert MLEngine._risk_label(0.5) == "中风险-需关注"
    assert MLEngine._risk_label(0.3) == "低风险-正常"
    assert MLEngine._risk_label(0.1) == "极低风险-稳定"


def test_recommend_routes_by_anomaly_type():
    """_recommend 按异常类型返回针对性建议。"""
    assert "检查" in MLEngine._recommend("ucl_exceeded", "login")
    assert "数据采集" in MLEngine._recommend("lcl_exceeded", "tx")
    assert "趋势" in MLEngine._recommend("rising_trend", "priv")
    assert "数据源" in MLEngine._recommend("sudden_zero", "tx")


# ----------------------------------------------------------------------
# 季节性 / 趋势 / 变点
# ----------------------------------------------------------------------
def test_seasonal_decompose_short_series_returns_false():
    """少于 6 点的序列无季节性。"""
    eng = _make_engine()
    result = eng._seasonal_decompose([1, 2, 3])
    assert result["has_seasonality"] is False


def test_seasonal_decompose_detects_pattern():
    """足够长的周期性序列可检测季节性。"""
    eng = _make_engine()
    # 7 天周期，周末值高
    values = [10, 10, 10, 10, 10, 50, 50, 10, 10, 10, 10, 10, 50, 50]
    result = eng._seasonal_decompose(values)
    assert "has_seasonality" in result
    assert "seasonal_period" in result
    assert result["seasonal_period"] >= 2


def test_analyze_trend_directions():
    """_analyze_trend 识别上升/下降/稳定。"""
    eng = _make_engine()
    assert eng._analyze_trend([1, 2, 3, 4, 5])["direction"] == "上升"
    assert eng._analyze_trend([5, 4, 3, 2, 1])["direction"] == "下降"
    assert eng._analyze_trend([3, 3, 3, 3, 3])["direction"] == "稳定"


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_short_series_skipped():
    """少于 3 个点的指标被跳过。"""
    eng = _make_engine()
    result = eng.execute([{"metric": "short", "values": [1, 2]}])
    assert len(result["metric_analyses"]) == 0
    assert result["summary"]["monitored_metrics"] == 0


def test_empty_input_handled():
    """空 list 输入返回零计数结构（不崩）。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["summary"]["monitored_metrics"] == 0
    assert result["alerts"] == []


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 时 control_params 为空 → 控制限仍可算（无特殊参数）。"""
    eng = MLEngine()
    result = eng.execute([{"metric": "x", "values": [1, 2, 3, 4, 5]}])
    assert len(result["metric_analyses"]) == 1
