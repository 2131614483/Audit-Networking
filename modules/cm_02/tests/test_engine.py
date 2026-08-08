"""[CM-02] engine 单测：多规则评分 / 分级路由 / 自动处置。

RPAEngine 为纯 stdlib 规则引擎（无 PortableDB 依赖）：
  * 规则匹配：金额阈值 / 频次阈值 / 非工作时段 / 重复告警 / 高风险类别
  * 严重度评分：多规则加权 → 0-100 分（上限 100）
  * 分级路由：P0(>=80, auto_block) / P1(>=60, escalate) / P2(>=40, monitor) / P3(<40, auto_close)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cm_02.engine import RPAEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> RPAEngine:
    eng = RPAEngine(config=overrides)
    eng.setup()
    return eng


def _alert(**fields) -> dict:
    """构造单个告警，补默认字段。"""
    base = {"alert_id": "T1", "source": "test", "category": "normal",
            "amount": 0, "frequency": 0, "after_hours": False, "repeat_count": 0}
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 单规则匹配
# ----------------------------------------------------------------------
def test_large_amount_triggers_r001():
    """amount > 1,000,000 触发 R001（30 分）。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(amount=1_500_000)]})
    a = result["alerts"][0]
    assert a["severity_score"] == 30
    rule_ids = {r["rule_id"] for r in a["matched_rules"]}
    assert "R001" in rule_ids


def test_super_large_amount_triggers_r001_and_r002():
    """amount > 5,000,000 同时触发 R001(30) + R002(50) = 80 分。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(amount=6_000_000)]})
    a = result["alerts"][0]
    rule_ids = {r["rule_id"] for r in a["matched_rules"]}
    assert "R001" in rule_ids
    assert "R002" in rule_ids
    assert a["severity_score"] == 80


def test_high_frequency_triggers_r003():
    """frequency > 10 触发 R003（25 分）。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(frequency=15)]})
    a = result["alerts"][0]
    rule_ids = {r["rule_id"] for r in a["matched_rules"]}
    assert "R003" in rule_ids
    assert a["severity_score"] == 25


def test_after_hours_triggers_r004():
    """after_hours == True 触发 R004（15 分）。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(after_hours=True)]})
    a = result["alerts"][0]
    rule_ids = {r["rule_id"] for r in a["matched_rules"]}
    assert "R004" in rule_ids
    assert a["severity_score"] == 15


def test_repeat_count_triggers_r005():
    """repeat_count > 3 触发 R005（20 分）。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(repeat_count=5)]})
    a = result["alerts"][0]
    rule_ids = {r["rule_id"] for r in a["matched_rules"]}
    assert "R005" in rule_ids
    assert a["severity_score"] == 20


def test_high_risk_category_triggers_r006():
    """category in [fraud, aml, sanction] 触发 R006（35 分）。"""
    eng = _make_engine()
    for cat in ("fraud", "aml", "sanction"):
        result = eng.execute({"alerts": [_alert(category=cat)]})
        a = result["alerts"][0]
        rule_ids = {r["rule_id"] for r in a["matched_rules"]}
        assert "R006" in rule_ids
        assert a["severity_score"] == 35


def test_normal_category_no_r006():
    """非高风险类别不触发 R006。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(category="payment")]})
    a = result["alerts"][0]
    rule_ids = {r["rule_id"] for r in a["matched_rules"]}
    assert "R006" not in rule_ids


# ----------------------------------------------------------------------
# 多规则加权 / 评分上限
# ----------------------------------------------------------------------
def test_multi_rule_score_accumulates():
    """多条规则命中时分数累加。"""
    eng = _make_engine()
    # amount>1M(30) + frequency>10(25) = 55
    result = eng.execute({"alerts": [_alert(amount=1_200_000, frequency=12)]})
    a = result["alerts"][0]
    assert a["severity_score"] == 55
    assert len(a["matched_rules"]) == 2


def test_score_capped_at_100():
    """所有规则全命中（175 分）被截断为 100。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [
        _alert(amount=6_000_000, frequency=15, after_hours=True,
               repeat_count=5, category="fraud")
    ]})
    a = result["alerts"][0]
    assert a["severity_score"] == 100
    assert len(a["matched_rules"]) == 6


def test_no_rule_hit_scores_zero():
    """无规则命中时分数为 0。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(amount=500_000, frequency=2)]})
    a = result["alerts"][0]
    assert a["severity_score"] == 0
    assert a["matched_rules"] == []


# ----------------------------------------------------------------------
# 分级路由 / 处置动作
# ----------------------------------------------------------------------
def test_priority_and_action_assignment():
    """按分数分配 priority / action_desc / action。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    by_id = {a["alert_id"]: a for a in result["alerts"]}
    # A001=100 → P0 / auto_block
    assert by_id["A001"]["priority"] == "P0"
    assert by_id["A001"]["action"] == "auto_block"
    assert by_id["A001"]["action_desc"] == "立即处置"
    # A003=65 → P1 / escalate
    assert by_id["A003"]["priority"] == "P1"
    assert by_id["A003"]["action"] == "escalate"
    # A004=50 → P2 / monitor
    assert by_id["A004"]["priority"] == "P2"
    assert by_id["A004"]["action"] == "monitor"
    # A002=0 → P3 / auto_close
    assert by_id["A002"]["priority"] == "P3"
    assert by_id["A002"]["action"] == "auto_close"


def test_results_sorted_by_score_desc():
    """结果按 severity_score 降序排列。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    scores = [a["severity_score"] for a in result["alerts"]]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 100  # A001 排首位


# ----------------------------------------------------------------------
# 汇总统计
# ----------------------------------------------------------------------
def test_summary_statistics():
    """summary 含总数、各分级计数、auto_closed。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["total"] == 4
    assert s["P0"] == 1
    assert s["P1"] == 1
    assert s["P2"] == 1
    assert s["P3"] == 1
    assert s["auto_closed"] == 1  # 仅 P3 自动归档


def test_summary_counts_consistent():
    """summary 各分级计数之和 = total。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["P0"] + s["P1"] + s["P2"] + s["P3"] == s["total"]


# ----------------------------------------------------------------------
# 结果结构
# ----------------------------------------------------------------------
def test_matched_rules_structure():
    """matched_rules 每项含 rule_id / name / score。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(amount=6_000_000)]})
    for r in result["alerts"][0]["matched_rules"]:
        assert "rule_id" in r
        assert "name" in r
        assert "score" in r


def test_raw_data_excludes_alert_id_and_source():
    """raw_data 保留除 alert_id / source 外的字段。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [_alert(amount=1_500_000, category="fraud")]})
    raw = result["alerts"][0]["raw_data"]
    assert "alert_id" not in raw
    assert "source" not in raw
    assert raw["amount"] == 1_500_000
    assert raw["category"] == "fraud"


def test_result_carries_source_and_category():
    """结果带 source / category 字段。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [
        _alert(source="ERP", category="aml", amount=2_000_000)
    ]})
    a = result["alerts"][0]
    assert a["source"] == "ERP"
    assert a["category"] == "aml"


# ----------------------------------------------------------------------
# 输入形态 / 边界
# ----------------------------------------------------------------------
def test_list_input_accepted():
    """直接传 list 输入也能处理。"""
    eng = _make_engine()
    result = eng.execute([_alert(amount=1_500_000)])
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["severity_score"] == 30


def test_empty_alerts():
    """空 alerts 返回空结果 + 零计数 summary。"""
    eng = _make_engine()
    result = eng.execute({"alerts": []})
    assert result["alerts"] == []
    assert result["summary"]["total"] == 0
    assert result["summary"]["auto_closed"] == 0


def test_non_dict_non_list_input_returns_empty():
    """非 dict / list 输入返回空结果（不崩）。"""
    eng = _make_engine()
    result = eng.execute("invalid input")
    assert result["alerts"] == []
    assert result["summary"]["total"] == 0


def test_alert_missing_fields_ignored():
    """缺少字段的告警不命中规则（score=0），不报错。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [{"alert_id": "X1"}]})
    a = result["alerts"][0]
    assert a["severity_score"] == 0
    assert a["matched_rules"] == []


def test_alert_without_id_defaults_unknown():
    """无 alert_id 的告警默认 "?"。"""
    eng = _make_engine()
    result = eng.execute({"alerts": [{"amount": 1_500_000}]})
    assert result["alerts"][0]["alert_id"] == "?"


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_has_rules_and_levels():
    """engine 加载后 model 含 6 条规则 + 4 个分级。"""
    eng = _make_engine()
    assert len(eng.model["rules"]) == 6
    assert len(eng.model["levels"]) == 4
    rule_ids = {r["id"] for r in eng.model["rules"]}
    assert rule_ids == {"R001", "R002", "R003", "R004", "R005", "R006"}


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 也能懒加载模型。"""
    eng = RPAEngine()
    result = eng.execute({"alerts": [_alert(amount=1_500_000)]})
    assert eng.model is not None
    assert len(result["alerts"]) == 1
