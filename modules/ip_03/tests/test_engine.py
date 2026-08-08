"""[IP-03] engine 单测：历史沿革梳理 / 时间线 / 股权快照 / 合规检查。

KGEngine 纯 stdlib 实现（无 PortableDB）：时间线排序 + 股权追踪 + 异常检测。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ip_03.engine import KGEngine, _parse_date

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> KGEngine:
    eng = KGEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 日期解析
# ----------------------------------------------------------------------
def test_parse_date_iso():
    """ISO 格式日期解析。"""
    d = _parse_date("2020-06-01")
    assert d is not None
    assert d.year == 2020 and d.month == 6 and d.day == 1


def test_parse_date_chinese():
    """中文日期格式解析。"""
    d = _parse_date("2020年6月1日")
    assert d is not None
    assert d.year == 2020


def test_parse_date_invalid():
    """无效日期返回 None。"""
    assert _parse_date("not a date") is None
    assert _parse_date("") is None
    assert _parse_date(None) is None


def test_parse_date_slash_format():
    """斜杠格式日期解析。"""
    d = _parse_date("2020/06/01")
    assert d is not None
    assert d.month == 6


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_rules():
    """setup 后 model 含 compliance_rules + anomaly_patterns。"""
    eng = _make_engine()
    assert len(eng.model["compliance_rules"]) == 8
    assert len(eng.model["anomaly_patterns"]) == 4
    rule_ids = {r["id"] for r in eng.model["compliance_rules"]}
    assert {"CR-01", "CR-04", "CR-06"} <= rule_ids


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_sorts_events_by_date():
    """预处理按日期排序事件。"""
    eng = _make_engine()
    prepared = eng._preprocess({
        "events": [
            {"date": "2021-01-01", "event_type": "增资"},
            {"date": "2019-01-01", "event_type": "设立"},
        ]
    })
    dates = [e["date_str"] for e in prepared["events"]]
    assert dates == ["2019-01-01", "2021-01-01"]


def test_preprocess_skips_invalid_dates():
    """无效日期的事件被跳过。"""
    eng = _make_engine()
    prepared = eng._preprocess({
        "events": [
            {"date": "2020-01-01", "event_type": "设立"},
            {"date": "bad date", "event_type": "增资"},
            {"date": "", "event_type": "转让"},
        ]
    })
    assert len(prepared["events"]) == 1


def test_preprocess_non_dict_raises():
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine()
    with pytest.raises(ValueError):
        eng._preprocess("not a dict")


# ----------------------------------------------------------------------
# 时间线构建
# ----------------------------------------------------------------------
def test_timeline_built():
    """时间线含所有事件，按序编号。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    timeline = result["timeline"]
    assert len(timeline) == 4
    for i, t in enumerate(timeline):
        assert t["seq"] == i + 1
        assert "date" in t
        assert "event_type" in t


def test_key_node_detection():
    """改制事件标记为关键节点。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    key_nodes = [t for t in result["timeline"] if t["is_key_node"]]
    assert len(key_nodes) >= 1
    assert any("改制" in t["event_type"] for t in key_nodes)


# ----------------------------------------------------------------------
# 股权快照
# ----------------------------------------------------------------------
def test_equity_snapshots_built():
    """每个事件生成一个股权快照。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    snaps = result["equity_snapshots"]
    assert len(snaps) == 4
    for s in snaps:
        assert "shareholders" in s
        assert "total_ratio" in s
        assert "status" in s


def test_equity_snapshot_normal_status():
    """比例合计 100% 的快照状态为正常。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # 所有事件股东比例合计均为 100%
    for snap in result["equity_snapshots"]:
        assert snap["status"] == "正常"
        assert abs(snap["total_ratio"] - 100) < 0.5


def test_equity_snapshot_anomaly_detected():
    """比例合计偏离 100% 时标记为比例异常。"""
    eng = _make_engine()
    result = eng.execute({
        "events": [{
            "date": "2020-01-01", "event_type": "设立",
            "shareholders": [{"name": "A", "ratio": 60}, {"name": "B", "ratio": 30}],
        }]
    })
    snap = result["equity_snapshots"][0]
    assert snap["status"] == "比例异常"
    assert abs(snap["total_ratio"] - 90) < 0.5


# ----------------------------------------------------------------------
# 异常检测
# ----------------------------------------------------------------------
def test_anomaly_missing_resolution():
    """增资缺少决议文件触发异常。"""
    eng = _make_engine()
    result = eng.execute({
        "events": [{
            "date": "2020-01-01", "event_type": "增资",
            "shareholders": [{"name": "A", "ratio": 100}],
            "has_resolution": False,
        }]
    })
    assert any(a["rule_id"] == "AP-03" for a in result["anomalies"])


def test_anomaly_ratio_abnormal():
    """比例异常触发 AP-01。"""
    eng = _make_engine()
    result = eng.execute({
        "events": [{
            "date": "2020-01-01", "event_type": "设立",
            "shareholders": [{"name": "A", "ratio": 50}],
        }]
    })
    assert any(a["rule_id"] == "AP-01" for a in result["anomalies"])


def test_no_anomalies_for_clean_data():
    """合规数据无异常。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # 正常数据：比例100%，有决议，无时间冲突
    assert len(result["anomalies"]) == 0


# ----------------------------------------------------------------------
# 合规检查
# ----------------------------------------------------------------------
def test_compliance_check_returns_report():
    """合规检查返回 8 条规则检查结果。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    comp = result["compliance"]
    assert comp["total"] == 8
    assert "rules_checked" in comp
    assert comp["passed"] + comp["warnings"] + comp["fails"] <= comp["total"]


def test_compliance_capital_increase_without_resolution_fails():
    """增资无决议 → CR-04 fail。"""
    eng = _make_engine()
    result = eng.execute({
        "events": [{
            "date": "2020-01-01", "event_type": "增资",
            "shareholders": [{"name": "A", "ratio": 100}],
            "has_resolution": False,
        }]
    })
    cr04 = next(r for r in result["compliance"]["rules_checked"] if r["rule_id"] == "CR-04")
    assert cr04["status"] == "fail"


def test_compliance_restructuring_info():
    """改制事件 → CR-06 info。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    cr06 = next(r for r in result["compliance"]["rules_checked"] if r["rule_id"] == "CR-06")
    assert cr06["status"] == "info"


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_full_result():
    """execute 返回 timeline + snapshots + anomalies + compliance。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "timeline" in result
    assert "equity_snapshots" in result
    assert "anomalies" in result
    assert "compliance" in result
    assert result["company"] == "示例科技股份有限公司"


def test_postprocess_adds_statistics():
    """postprocess 添加 statistics + verdict。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "statistics" in result
    stats = result["statistics"]
    assert stats["total_events"] == 4
    assert stats["key_events"] >= 1
    assert stats["equity_snapshots"] == 4
    assert "compliance_coverage" in stats
    assert "verdict" in result


def test_verdict_pass_for_clean_data():
    """合规数据 → verdict=通过自动化梳理。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["verdict"] == "通过自动化梳理"


def test_verdict_review_for_anomalies():
    """有异常 → verdict=需重点人工复核 或 建议人工复核。"""
    eng = _make_engine()
    result = eng.execute({
        "events": [{
            "date": "2020-01-01", "event_type": "增资",
            "shareholders": [{"name": "A", "ratio": 50}],
            "has_resolution": False,
        }]
    })
    assert result["verdict"] in ("需重点人工复核", "建议人工复核")


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_events():
    """空事件列表不崩。"""
    eng = _make_engine()
    result = eng.execute({"events": []})
    assert result["timeline"] == []
    assert result["anomalies"] == []
    assert result["statistics"]["total_events"] == 0
