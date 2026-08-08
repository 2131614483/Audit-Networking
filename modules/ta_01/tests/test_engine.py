"""[TA-01] engine 单测：发票字段校验 / 勾稽 / 税率 / 重复报销。

CVEngine 基于 PortableDB 持久化（invoices/audit_results 表），
纯 stdlib 规则引擎。每个测试用 tmp_path 隔离 db，结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ta_01.engine import CVEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> CVEngine:
    eng = CVEngine(config={"db_path": str(tmp_path / "ta_01_engine.db"), **overrides})
    eng.setup()
    return eng


def _close(eng: CVEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_standard_rates_and_rules(tmp_path):
    """setup 后 model 含标准税率 + 审计规则。"""
    eng = _make_engine(tmp_path)
    try:
        assert 0.13 in eng.model["standard_tax_rates"]
        assert 0.06 in eng.model["standard_tax_rates"]
        assert "audit_rules" in eng.model
        assert "tolerance" in eng.model
    finally:
        _close(eng)


def test_db_tables_created(tmp_path):
    """setup 后 db 含 invoices / audit_results 两表。"""
    db_path = tmp_path / "ta_01_tables.db"
    eng = CVEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"invoices", "audit_results"} <= tables
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_parses_invoices(tmp_path):
    """预处理解析发票字段为标准结构。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert len(prepared["invoices"]) == 5
        inv = prepared["invoices"][0]
        assert inv["invoice_id"] == "INV-001"
        assert inv["amount_excl_tax"] == 1000.0
        assert inv["tax_rate"] == 0.13
        assert inv["invoice_date"] is not None
    finally:
        _close(eng)


def test_preprocess_generates_id_if_missing(tmp_path):
    """无 invoice_id 且无 invoice_no 时自动生成 INV- 前缀 id。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"invoices": [{"seller_name": "S"}]})
        assert prepared["invoices"][0]["invoice_id"].startswith("INV-")
    finally:
        _close(eng)


def test_preprocess_invalid_amount_skipped(tmp_path):
    """金额无法解析的发票被跳过。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"invoices": [
            {"invoice_no": "12345678", "amount_excl_tax": "invalid"},
        ]})
        assert len(prepared["invoices"]) == 0
    finally:
        _close(eng)


def test_preprocess_non_dict_raises(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng._preprocess("not a dict")
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 规则：号码格式
# ----------------------------------------------------------------------
def test_invoice_no_format_error(tmp_path):
    """发票号码非 8-20 位数字触发 error。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X1", "invoice_no": "ABC123",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 100, "tax_rate": 0.13,
            "tax_amount": 13, "amount_incl_tax": 113,
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "号码格式" for i in issues)
    finally:
        _close(eng)


def test_invoice_no_empty_triggers_error(tmp_path):
    """发票号码为空触发 error。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X2", "invoice_no": "",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 100, "tax_rate": 0.13,
            "tax_amount": 13, "amount_incl_tax": 113,
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "号码格式" and "为空" in i["msg"] for i in issues)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 规则：税率校验
# ----------------------------------------------------------------------
def test_non_standard_tax_rate_warning(tmp_path):
    """非标准税率触发 warning。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X3", "invoice_no": "12345678",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 1000, "tax_rate": 0.05,
            "tax_amount": 50, "amount_incl_tax": 1050,
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "税率校验" for i in issues)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 规则：勾稽校验
# ----------------------------------------------------------------------
def test_amount_cross_check_error(tmp_path):
    """价税合计 ≠ 不含税+税额 触发 error。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X4", "invoice_no": "12345678",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 1000, "tax_rate": 0.13,
            "tax_amount": 130, "amount_incl_tax": 1500,  # 应为 1130
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "勾稽校验" and i["severity"] == "error" for i in issues)
    finally:
        _close(eng)


def test_tax_amount_mismatch_warning(tmp_path):
    """税额 ≠ 不含税*税率 触发 warning。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X5", "invoice_no": "12345678",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 1000, "tax_rate": 0.13,
            "tax_amount": 200,  # 应为 130
            "amount_incl_tax": 1200,  # 1000+200=1200 勾稽通过，但税额不对
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "勾稽校验" and i["severity"] == "warning" for i in issues)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 规则：日期合理性 / 字段完整性 / 金额校验
# ----------------------------------------------------------------------
def test_invoice_date_after_audit_date(tmp_path):
    """发票日期晚于审计日期触发 error。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "audit_date": "2026-08-01",
            "invoices": [{
                "invoice_id": "X6", "invoice_no": "12345678",
                "seller_name": "S", "buyer_name": "B",
                "amount_excl_tax": 100, "tax_rate": 0.13,
                "tax_amount": 13, "amount_incl_tax": 113,
                "invoice_date": "2026-09-01",
            }],
        })
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "日期合理性" for i in issues)
    finally:
        _close(eng)


def test_missing_seller_buyer_warning(tmp_path):
    """购销方缺失触发 warning。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X7", "invoice_no": "12345678",
            "seller_name": "", "buyer_name": "",
            "amount_excl_tax": 100, "tax_rate": 0.13,
            "tax_amount": 13, "amount_incl_tax": 113,
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "字段完整性" for i in issues)
    finally:
        _close(eng)


def test_zero_amount_error(tmp_path):
    """发票金额为零触发 error。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X8", "invoice_no": "12345678",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 0, "tax_rate": 0,
            "tax_amount": 0, "amount_incl_tax": 0,
            "invoice_date": "2026-07-01",
        }]})
        issues = result["results"][0]["issues"]
        assert any(i["type"] == "金额校验" for i in issues)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 重复报销检测
# ----------------------------------------------------------------------
def test_duplicate_invoice_detected(tmp_path):
    """同金额同供应商近 30 天的发票触发重复报销。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "audit_date": "2026-08-01",
            "invoices": [
                {"invoice_id": "D1", "invoice_no": "11111111",
                 "seller_name": "供应商X", "buyer_name": "B",
                 "amount_excl_tax": 1000, "tax_rate": 0.13,
                 "tax_amount": 130, "amount_incl_tax": 1130,
                 "invoice_date": "2026-07-01"},
                {"invoice_id": "D2", "invoice_no": "22222222",
                 "seller_name": "供应商X", "buyer_name": "B",
                 "amount_excl_tax": 1000, "tax_rate": 0.13,
                 "tax_amount": 130, "amount_incl_tax": 1130,
                 "invoice_date": "2026-07-15"},
            ],
        })
        # D2 应被标记为重复
        d2 = next(r for r in result["results"] if r["invoice_id"] == "D2")
        assert any(i["type"] == "重复报销" for i in d2["issues"])
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_results_and_summary(tmp_path):
    """execute 返回 results + summary（含 issue_type_distribution）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "results" in result
        assert "summary" in result
        assert len(result["results"]) == 5
        assert "issue_type_distribution" in result["summary"]
    finally:
        _close(eng)


def test_audit_status_assignment(tmp_path):
    """audit_status 按问题严重度分配（通过/警告/异常）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        statuses = {r["invoice_id"]: r["audit_status"] for r in result["results"]}
        # INV-003 字段齐全且勾稽正确 → 通过
        assert statuses["INV-003"] == "通过"
        # INV-002 号码格式错 → 异常
        assert statuses["INV-002"] == "异常"
        # INV-004 日期合理性 error → 异常
        assert statuses["INV-004"] == "异常"
        # INV-001 / INV-005 互为重复报销 → 异常
        assert statuses["INV-001"] == "异常"
        assert statuses["INV-005"] == "异常"
    finally:
        _close(eng)


def test_risk_score_capped_at_one(tmp_path):
    """风险评分上限为 1.0。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X9", "invoice_no": "",  # 号码空 +0.3
            "seller_name": "",  # 字段缺失 +0.15
            "buyer_name": "",
            "amount_excl_tax": 0, "tax_rate": 0,  # 金额零 +0.3
            "tax_amount": 0, "amount_incl_tax": 0,
            "invoice_date": "2026-09-01",  # 日期晚（无 audit_date 不触发）
        }]})
        assert result["results"][0]["risk_score"] <= 1.0
    finally:
        _close(eng)


def test_summary_aggregates_counts(tmp_path):
    """summary 聚合通过/警告/异常计数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["total"] == 5
        assert s["passed"] + s["warning"] + s["abnormal"] == s["total"]
        assert s["total_issues"] > 0
        assert "avg_risk_score" in s
        assert len(s["high_risk_invoices"]) <= 10
    finally:
        _close(eng)


def test_summary_high_risk_sorted(tmp_path):
    """high_risk_invoices 按风险分降序。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        high = result["summary"]["high_risk_invoices"]
        scores = [r["risk_score"] for r in high]
        assert scores == sorted(scores, reverse=True)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_invoices(tmp_path):
    """空发票列表返回零计数 summary。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": []})
        assert result["results"] == []
        assert result["summary"]["total"] == 0
    finally:
        _close(eng)


def test_issue_structure(tmp_path):
    """每个 issue 含 type / severity / msg。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{
            "invoice_id": "X10", "invoice_no": "bad",
            "seller_name": "S", "buyer_name": "B",
            "amount_excl_tax": 100, "tax_rate": 0.13,
            "tax_amount": 13, "amount_incl_tax": 113,
            "invoice_date": "2026-07-01",
        }]})
        for issue in result["results"][0]["issues"]:
            assert "type" in issue
            assert "severity" in issue
            assert "msg" in issue
    finally:
        _close(eng)
