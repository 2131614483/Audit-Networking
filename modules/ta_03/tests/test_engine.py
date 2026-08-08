"""[TA-03] engine 单测：进项税额转出 / 场景识别 / 分摊计算。

LLMEngine 基于 PortableDB 持久化（input_invoices/transfer_results 表），
纯 stdlib 税法规则引擎。每个测试用 tmp_path 隔离 db，结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ta_03.engine import LLMEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> LLMEngine:
    eng = LLMEngine(config={"db_path": str(tmp_path / "ta_03_engine.db"), **overrides})
    eng.setup()
    return eng


def _close(eng: LLMEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_scenarios(tmp_path):
    """setup 后 model 含 6 个转出场景。"""
    eng = _make_engine(tmp_path)
    try:
        scenarios = eng.model["transfer_scenarios"]
        assert "collective_welfare" in scenarios
        assert "personal_consumption" in scenarios
        assert "tax_exempted" in scenarios
        assert "abnormal_loss" in scenarios
        assert len(scenarios) == 6
    finally:
        _close(eng)


def test_db_tables_created(tmp_path):
    """setup 后 db 含 input_invoices / transfer_results 两表。"""
    db_path = tmp_path / "ta_03_tables.db"
    eng = LLMEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"input_invoices", "transfer_results"} <= tables
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_parses_invoices(tmp_path):
    """预处理解析发票字段 + sales_allocation。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert len(prepared["invoices"]) == 5
        assert prepared["sales_allocation"]["total_sales"] == 100000
        inv = prepared["invoices"][0]
        assert inv["invoice_id"] == "INV-001"
        assert inv["amount_excl_tax"] == 1000.0
        assert inv["tax_amount"] == 60.0
    finally:
        _close(eng)


def test_preprocess_generates_id_if_missing(tmp_path):
    """无 invoice_id 时自动生成。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"invoices": [{"purchase_content": "X"}]})
        assert prepared["invoices"][0]["invoice_id"].startswith("INV-")
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


def test_preprocess_skips_invalid_amounts(tmp_path):
    """金额无法解析的发票被跳过。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"invoices": [
            {"invoice_id": "X", "amount_excl_tax": "bad"},
        ]})
        assert len(prepared["invoices"]) == 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 场景识别
# ----------------------------------------------------------------------
def test_collective_welfare_full_transfer(tmp_path):
    """集体福利 → 全额转出（ratio=1.0）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        r = next(x for x in result["results"] if x["invoice_id"] == "INV-001")
        assert r["scenario"] == "集体福利"
        assert r["transfer_ratio"] == 1.0
        assert r["transfer_amount"] == 60.0  # 60 * 1.0
    finally:
        _close(eng)


def test_personal_consumption_full_transfer(tmp_path):
    """个人消费 → 全额转出。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        r = next(x for x in result["results"] if x["invoice_id"] == "INV-002")
        assert r["scenario"] == "个人消费"
        assert r["transfer_ratio"] == 1.0
        assert r["transfer_amount"] == 65.0
    finally:
        _close(eng)


def test_tax_exempted_allocation_transfer(tmp_path):
    """免税项目 → 按销售额分摊转出。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        r = next(x for x in result["results"] if x["invoice_id"] == "INV-003")
        assert r["scenario"] == "免税项目"
        # ratio = (20000 + 10000) / 100000 = 0.3
        assert r["transfer_ratio"] == 0.3
        assert r["transfer_amount"] == 54.0  # 180 * 0.3
        assert "按销售额分摊" in r["calculation_method"]
    finally:
        _close(eng)


def test_abnormal_loss_full_transfer(tmp_path):
    """非正常损失 → 全额转出。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        r = next(x for x in result["results"] if x["invoice_id"] == "INV-004")
        assert r["scenario"] == "非正常损失"
        assert r["transfer_ratio"] == 1.0
        assert r["transfer_amount"] == 390.0
    finally:
        _close(eng)


def test_no_match_skipped(tmp_path):
    """无关键词匹配的发票被跳过。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        ids = {r["invoice_id"] for r in result["results"]}
        assert "INV-005" not in ids  # 办公用品 → 无匹配
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_results_and_summary(tmp_path):
    """execute 返回 results + summary（含 scenario_distribution / invoice_level_summary）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "results" in result
        assert "summary" in result
        assert len(result["results"]) == 4  # INV-005 被跳过
        assert "scenario_distribution" in result["summary"]
        assert "invoice_level_summary" in result["summary"]
    finally:
        _close(eng)


def test_summary_total_transfer(tmp_path):
    """summary 聚合转出总额。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        # 60 + 65 + 54 + 390 = 569
        assert s["total_transfer_amount"] == 569.0
        assert s["matched_invoice_count"] == 4
    finally:
        _close(eng)


def test_scenario_distribution(tmp_path):
    """scenario_distribution 统计各场景次数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        dist = result["summary"]["scenario_distribution"]
        assert dist["集体福利"] == 1
        assert dist["个人消费"] == 1
        assert dist["免税项目"] == 1
        assert dist["非正常损失"] == 1
    finally:
        _close(eng)


def test_high_value_items_sorted(tmp_path):
    """high_value_items 按转出金额降序。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        amounts = [r["transfer_amount"] for r in result["summary"]["high_value_items"]]
        assert amounts == sorted(amounts, reverse=True)
        assert len(amounts) <= 10
    finally:
        _close(eng)


def test_invoice_level_summary_aggregates(tmp_path):
    """invoice_level_summary 按发票聚合转出金额。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        inv_summary = result["summary"]["invoice_level_summary"]
        assert len(inv_summary) <= 10
        transfers = [i["total_transfer"] for i in inv_summary]
        assert transfers == sorted(transfers, reverse=True)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_invoices(tmp_path):
    """空发票列表返回零计数 summary。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [], "sales_allocation": {}})
        assert result["results"] == []
        assert result["summary"]["total_transfer_amount"] == 0
    finally:
        _close(eng)


def test_allocation_zero_total_sales(tmp_path):
    """total_sales=0 时分摊比例为 0。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "sales_allocation": {"total_sales": 0, "tax_exempted_sales": 100},
            "invoices": [{"invoice_id": "X", "purchase_content": "免税",
                          "amount_excl_tax": 1000, "tax_rate": 0.13,
                          "tax_amount": 130}],
        })
        r = result["results"][0]
        assert r["transfer_ratio"] == 0.0
        assert r["transfer_amount"] == 0.0
    finally:
        _close(eng)
