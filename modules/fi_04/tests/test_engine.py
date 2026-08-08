"""[FI-04] engine 单测：监管报表智能核对 / 科目映射 / 钩稽校验 / 合规评分。

LLMEngine 为纯 stdlib 实现（difflib 语义匹配 + 规则引擎），无外部依赖。
报表科目用中文别名，引擎经语义匹配归一化为标准字段后做表内/表间钩稽校验。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.fi_04.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


@pytest.fixture
def make_engine(tmp_path):
    """工厂 fixture：每个测试用 tmp_path 隔离 db，结束后 close。"""
    created = []

    def _factory(**overrides):
        eng = LLMEngine(config={"db_path": tmp_path / "fi_04.db", **overrides})
        eng.setup()
        created.append(eng)
        return eng

    yield _factory
    for e in created:
        e.close()


# ----------------------------------------------------------------------
# 科目映射
# ----------------------------------------------------------------------
def test_semantic_alias_mapping(make_engine):
    """中文科目名经语义匹配映射到标准字段。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [
            {
                "report_id": "R1",
                "items": {
                    "资产总计": 1000000,
                    "负债合计": 600000,
                    "所有者权益合计": 400000,
                    "货币资金": 200000,
                },
            }
        ]
    })
    norm = result["reports"][0]["normalized"]
    assert norm["total_assets"] == 1000000
    assert norm["total_liabilities"] == 600000
    assert norm["total_equity"] == 400000
    assert norm["cash"] == 200000


def test_auto_report_id_when_missing(make_engine):
    """无 report_id 时自动生成 RPT-XXXXXX。"""
    eng = make_engine()
    result = eng.execute({"reports": [{"items": {"资产总计": 100}}]})
    rid = result["reports"][0]["report_id"]
    assert rid.startswith("RPT-")


# ----------------------------------------------------------------------
# 钩稽校验
# ----------------------------------------------------------------------
def test_balanced_report_passes_balance_check(make_engine):
    """平衡的资产负债表（资产=负债+权益）不触发 R001 违规。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 150000, "存货": 100000, "净利润": 200000
            },
            "receivables_prev_year": 120000, "inventory_prev_year": 90000,
            "pl_net_profit": 200000, "cf_net": 180000
        }]
    })
    rule_ids = {v["rule_id"] for v in result["violations"]}
    assert "R001" not in rule_ids


def test_current_assets_below_cash_violation(make_engine):
    """流动资产 < 货币资金触发 R002 error。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 800000, "负债合计": 500000, "所有者权益合计": 300000,
                "流动资产合计": 200000, "流动负债合计": 400000, "货币资金": 300000,
                "应收账款": 100, "存货": 100, "净利润": 100000
            },
            "receivables_prev_year": 100, "inventory_prev_year": 100,
            "pl_net_profit": 100000, "cf_net": 100000
        }]
    })
    r002 = [v for v in result["violations"] if v["rule_id"] == "R002"]
    assert len(r002) == 1
    assert r002[0]["level"] == "error"


def test_high_receivables_growth_violation(make_engine):
    """应收账款同比增长 >30% 触发 R003 warning。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 200000, "存货": 100000, "净利润": 200000
            },
            "receivables_prev_year": 100000, "inventory_prev_year": 90000,
            "pl_net_profit": 200000, "cf_net": 180000
        }]
    })
    r003 = [v for v in result["violations"] if v["rule_id"] == "R003"]
    assert len(r003) == 1
    assert r003[0]["level"] == "warning"


def test_high_inventory_growth_violation(make_engine):
    """存货同比增长 >20% 触发 R004 warning。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 100000, "存货": 150000, "净利润": 200000
            },
            "receivables_prev_year": 90000, "inventory_prev_year": 100000,
            "pl_net_profit": 200000, "cf_net": 180000
        }]
    })
    r004 = [v for v in result["violations"] if v["rule_id"] == "R004"]
    assert len(r004) == 1
    assert r004[0]["level"] == "warning"


def test_low_current_ratio_violation(make_engine):
    """流动比率 < 1 触发 R005 info。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 800000, "负债合计": 500000, "所有者权益合计": 300000,
                "流动资产合计": 200000, "流动负债合计": 400000, "货币资金": 100000,
                "应收账款": 100, "存货": 100, "净利润": 100000
            },
            "receivables_prev_year": 100, "inventory_prev_year": 100,
            "pl_net_profit": 100000, "cf_net": 100000
        }]
    })
    r005 = [v for v in result["violations"] if v["rule_id"] == "R005"]
    assert len(r005) == 1
    assert r005[0]["level"] == "info"


def test_net_profit_mismatch_violation(make_engine):
    """净利润与利润表净利润不一致触发 R006 error。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 100000, "存货": 100000, "净利润": 200000
            },
            "receivables_prev_year": 90000, "inventory_prev_year": 90000,
            "pl_net_profit": 150000,
            "cf_net": 180000
        }]
    })
    r006 = [v for v in result["violations"] if v["rule_id"] == "R006"]
    assert len(r006) == 1
    assert r006[0]["level"] == "error"


def test_cashflow_divergence_violation(make_engine):
    """现金流净额与净利润差异过大触发 R007 warning。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 100000, "存货": 100000, "净利润": 200000
            },
            "receivables_prev_year": 90000, "inventory_prev_year": 90000,
            "pl_net_profit": 200000,
            "cf_net": 50000,
        }]
    })
    r007 = [v for v in result["violations"] if v["rule_id"] == "R007"]
    assert len(r007) == 1
    assert r007[0]["level"] == "warning"


# ----------------------------------------------------------------------
# 合规评分 / 状态
# ----------------------------------------------------------------------
def test_compliance_score_and_status(make_engine):
    """端到端用 sample：违规统计与合规评分正确（score=44.44 高风险）。"""
    eng = make_engine()
    result = eng.execute(_sample())
    summary = result["summary"]
    assert summary["report_count"] == 2
    assert summary["total_violations"] == 5
    assert summary["error_count"] == 1
    assert summary["warning_count"] == 3
    assert summary["info_count"] == 1
    assert summary["compliance_score"] == 44.44
    assert summary["compliance_status"] == "高风险"


def test_clean_report_full_compliance(make_engine):
    """全合规报表 → score=100，status=通过。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 120000, "存货": 100000, "净利润": 200000
            },
            "receivables_prev_year": 100000, "inventory_prev_year": 90000,
            "pl_net_profit": 200000, "cf_net": 180000
        }]
    })
    assert result["summary"]["total_violations"] == 0
    assert result["summary"]["compliance_score"] == 100.0
    assert result["summary"]["compliance_status"] == "通过"


def test_violations_carry_report_context(make_engine):
    """违规项携带 report_id / report_type / period 上下文。"""
    eng = make_engine()
    result = eng.execute({
        "reports": [{
            "report_id": "RPT-X1",
            "report_type": "资产负债表",
            "period": "2024-Q4",
            "items": {
                "资产总计": 800000, "负债合计": 500000, "所有者权益合计": 300000,
                "流动资产合计": 200000, "流动负债合计": 400000, "货币资金": 300000,
                "应收账款": 100, "存货": 100, "净利润": 100000
            },
            "receivables_prev_year": 100, "inventory_prev_year": 100,
            "pl_net_profit": 100000, "cf_net": 100000
        }]
    })
    assert len(result["violations"]) > 0
    for v in result["violations"]:
        assert v["report_id"] == "RPT-X1"
        assert v["report_type"] == "资产负债表"
        assert v["period"] == "2024-Q4"


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_reports(make_engine):
    """空 reports 列表 → 0 违规，0 报表，满分。"""
    eng = make_engine()
    result = eng.execute({"reports": []})
    assert result["summary"]["report_count"] == 0
    assert result["summary"]["total_violations"] == 0
    assert result["summary"]["compliance_score"] == 100.0


def test_non_dict_input_raises(make_engine):
    """非 dict 输入抛 ValueError。"""
    eng = make_engine()
    with pytest.raises(ValueError):
        eng.execute("not a dict")
