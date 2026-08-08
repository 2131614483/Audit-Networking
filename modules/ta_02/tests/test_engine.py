"""[TA-02] engine 单测：发票四单自动匹配 / 多维相似度 / 匹配状态聚合。

MLEngine 基于 PortableDB 持久化（purchase_orders/receipts/invoices/payments/match_results 表），
纯 stdlib 加权相似度匹配。每个测试用 tmp_path 隔离 db，结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ta_02.engine import MLEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> MLEngine:
    eng = MLEngine(config={"db_path": str(tmp_path / "ta_02_engine.db"), **overrides})
    eng.setup()
    return eng


def _close(eng: MLEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_weights_and_thresholds(tmp_path):
    """setup 后 model 含 field_weights / tolerances / match_threshold。"""
    eng = _make_engine(tmp_path)
    try:
        assert "field_weights" in eng.model
        assert "tolerances" in eng.model
        assert eng.model["match_threshold"] == 0.7
        assert eng.model["field_weights"]["amount_incl_tax"] == 0.35
    finally:
        _close(eng)


def test_db_tables_created(tmp_path):
    """setup 后 db 含 5 张表。"""
    db_path = tmp_path / "ta_02_tables.db"
    eng = MLEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"purchase_orders", "receipts", "invoices",
                "payments", "match_results"} <= tables
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_parses_four_lists(tmp_path):
    """预处理解析 invoices/orders/receipts/payments 四列表。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert len(prepared["invoices"]) == 3
        assert len(prepared["orders"]) == 2
        assert len(prepared["receipts"]) == 1
        assert len(prepared["payments"]) == 1
        inv = prepared["invoices"][0]
        assert inv["id"] == "INV-001"
        assert inv["amount_incl_tax"] == 1130.0
        assert inv["supplier_name"] == "供应商A"
    finally:
        _close(eng)


def test_preprocess_generates_id_if_missing(tmp_path):
    """无 id 时自动生成。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"invoices": [{"supplier_name": "S"}]})
        assert prepared["invoices"][0]["id"].startswith("INVOICES-")
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


def test_preprocess_skips_invalid_items(tmp_path):
    """非 dict 元素或金额无法解析的项被跳过。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"invoices": [
            "not a dict",
            {"id": "OK", "supplier_name": "S", "amount_incl_tax": "bad"},
        ]})
        assert len(prepared["invoices"]) == 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 相似度计算
# ----------------------------------------------------------------------
def test_compute_similarity_identical_items(tmp_path):
    """完全相同的两条目相似度为 1.0。"""
    eng = _make_engine(tmp_path)
    try:
        a = {"amount_incl_tax": 1000, "amount_excl_tax": 800, "tax_amount": 200,
             "quantity": 10, "supplier_name": "供应商X", "date": "2026-07-01"}
        score = eng._compute_similarity(a, a, eng.model["field_weights"],
                                        eng.model["tolerances"],
                                        eng.model["max_date_diff_days"])
        assert score == pytest.approx(1.0, abs=0.01)
    finally:
        _close(eng)


def test_compute_similarity_different_suppliers(tmp_path):
    """不同供应商降低相似度。"""
    eng = _make_engine(tmp_path)
    try:
        a = {"amount_incl_tax": 1000, "amount_excl_tax": 800, "tax_amount": 200,
             "quantity": 10, "supplier_name": "供应商AAA", "date": "2026-07-01"}
        b = {"amount_incl_tax": 1000, "amount_excl_tax": 800, "tax_amount": 200,
             "quantity": 10, "supplier_name": "供应商BBB", "date": "2026-07-01"}
        score = eng._compute_similarity(a, b, eng.model["field_weights"],
                                        eng.model["tolerances"],
                                        eng.model["max_date_diff_days"])
        assert score < 1.0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 匹配状态
# ----------------------------------------------------------------------
def test_full_match_status(tmp_path):
    """INV-001 四单齐全（order+receipt+payment 均匹配）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        inv001 = next(m for m in result["matches"] if m["invoice_id"] == "INV-001")
        assert inv001["status"] == "四单齐全"
        assert inv001["matched_orders"] == 3
        assert inv001["overall_confidence"] > 0.7
    finally:
        _close(eng)


def test_unmatched_status(tmp_path):
    """INV-003 无候选 → 未匹配。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        inv003 = next(m for m in result["matches"] if m["invoice_id"] == "INV-003")
        assert inv003["status"] == "未匹配"
        assert inv003["matched_orders"] == 0
    finally:
        _close(eng)


def test_match_details_contain_target_ids(tmp_path):
    """匹配明细含 target_id 与 score。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        inv001 = next(m for m in result["matches"] if m["invoice_id"] == "INV-001")
        order_match = inv001["matches"]["order_match"]
        assert order_match["matched"] is True
        assert order_match["target_id"] == "PO-001"
        assert "score" in order_match
    finally:
        _close(eng)


def test_no_candidates_returns_reason(tmp_path):
    """无候选时返回 matched=False + reason。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [{"id": "X", "supplier_name": "S",
                                            "amount_incl_tax": 100}],
                              "orders": [], "receipts": [], "payments": []})
        m = result["matches"][0]
        assert m["matches"]["order_match"]["matched"] is False
        assert m["matches"]["order_match"]["reason"] == "无候选"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_matches_and_summary(tmp_path):
    """execute 返回 matches + summary（含 high_confidence）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "matches" in result
        assert "summary" in result
        assert len(result["matches"]) == 3
        assert "high_confidence" in result["summary"]
    finally:
        _close(eng)


def test_summary_aggregates_counts(tmp_path):
    """summary 聚合 fully/partially/unmatched 计数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["invoice_count"] == 3
        assert s["fully_matched"] + s["partially_matched"] + s["unmatched"] == 3
        assert s["fully_matched"] >= 1
        assert "avg_confidence" in s
    finally:
        _close(eng)


def test_high_confidence_sorted_desc(tmp_path):
    """high_confidence 按置信度降序。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        confs = [h["confidence"] for h in result["summary"]["high_confidence"]]
        assert confs == sorted(confs, reverse=True)
        assert len(confs) <= 10
    finally:
        _close(eng)


def test_low_similarity_not_matched(tmp_path):
    """相似度低于阈值(0.7)时不匹配。"""
    eng = _make_engine(tmp_path)
    try:
        # 供应商不同 + 金额差异大 → score 远低于 0.7
        result = eng.execute({"invoices": [
            {"id": "X", "supplier_name": "供应商AAA", "amount_incl_tax": 1000,
             "amount_excl_tax": 800, "tax_amount": 200, "quantity": 10,
             "date": "2026-07-01"}
        ], "orders": [
            {"id": "O1", "supplier_name": "供应商BBB", "amount_incl_tax": 500,
             "amount_excl_tax": 400, "tax_amount": 100, "quantity": 5,
             "date": "2026-07-01"}
        ], "receipts": [], "payments": []})
        m = result["matches"][0]
        assert m["matches"]["order_match"]["matched"] is False
        assert m["matches"]["order_match"]["best_score"] < 0.7
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_input(tmp_path):
    """空输入返回零计数 summary。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"invoices": [], "orders": [],
                              "receipts": [], "payments": []})
        assert result["matches"] == []
        assert result["summary"]["invoice_count"] == 0
    finally:
        _close(eng)


def test_partial_match_status(tmp_path):
    """仅匹配 1 单 → 部分匹配。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "invoices": [{"id": "P1", "supplier_name": "供应商A",
                          "amount_incl_tax": 1000, "amount_excl_tax": 800,
                          "tax_amount": 200, "quantity": 10, "date": "2026-07-01"}],
            "orders": [{"id": "O1", "supplier_name": "供应商A",
                        "amount_incl_tax": 1000, "amount_excl_tax": 800,
                        "tax_amount": 200, "quantity": 10, "date": "2026-07-01"}],
            "receipts": [],
            "payments": [],
        })
        m = result["matches"][0]
        assert m["status"] == "部分匹配"
        assert m["matched_orders"] == 1
    finally:
        _close(eng)
