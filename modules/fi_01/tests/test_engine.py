"""[FI-01] engine 单测：信贷资产质量评估（PD/LGD/EAD/EL/RWA + 五级分类）。

MLEngine 基于 PortableDB 持久化信贷资产，纯 stdlib（Logistic 近似 PD）：
  * 违约概率 PD：Logistic(z) × (1 + payment_factor × 0.3)，z 由财务比率加权
  * 违约损失率 LGD：担保品类型查表，还款历史 <6 个月加 0.1
  * 预期损失 EL = PD × LGD × EAD
  * 五级分类：正常/关注/次级/可疑/损失 → 风险权重 0.2/0.5/1.0/1.5/1.5
  * RWA = EAD × risk_weight × industry_multiplier，资本要求 = RWA × 8%
每个测试用 tmp_path 隔离 db，Windows 下结束前 eng.close()。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from modules.fi_01.engine import MLEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    eng = MLEngine(config={
        "db_path": str(tmp_path / "fi_01_engine.db"),
        **overrides,
    })
    eng.setup()
    return eng


def _close(eng: MLEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


def _loan(**fields) -> dict:
    """构造单笔贷款，补默认字段（优质贷款基准）。"""
    base = {
        "asset_id": "T1",
        "borrower": "测试企业",
        "amount": 100000,
        "remaining_amount": 80000,
        "industry": "制造业",
        "collateral_type": "现金",
        "term_months": 12,
        "debt_ratio": 0.3,
        "current_ratio": 2.0,
        "operating_margin": 0.15,
        "cashflow_coverage": 2.0,
        "payment_history": 24,
    }
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 五级分类
# ----------------------------------------------------------------------
def test_grade_classification(tmp_path):
    """四笔贷款覆盖 正常/关注/次级/损失 四个等级。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        by_id = {a["asset_id"]: a for a in result["assessments"]}
        assert by_id["L001"]["grade"] == "正常"
        assert by_id["L002"]["grade"] == "关注"
        assert by_id["L003"]["grade"] == "次级"
        assert by_id["L004"]["grade"] == "损失"
    finally:
        _close(eng)


def test_grade_distribution_in_summary(tmp_path):
    """summary.grade_distribution 按等级计数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        dist = result["summary"]["grade_distribution"]
        assert dist["正常"] == 1
        assert dist["关注"] == 1
        assert dist["次级"] == 1
        assert dist["损失"] == 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# PD 计算（Logistic 近似）
# ----------------------------------------------------------------------
def test_pd_formula(tmp_path):
    """PD = sigmoid(z) × (1 + payment_factor × 0.3)，z = intercept + Σ coef × factor。"""
    eng = _make_engine(tmp_path)
    try:
        # L002: dr=0.7, cr=1.0, om=0.02, cc=0.8, ph=12
        z = -3.0 + 2.5 * 0.7 - 1.0 * 1.0 - 2.0 * 0.02 - 1.5 * 0.8
        payment_factor = max(0.0, 1.0 - 12 / 24.0)
        expected_pd = 1.0 / (1.0 + math.exp(-z)) * (1.0 + payment_factor * 0.3)
        result = eng.execute({"loans": [_loan(
            asset_id="L002", debt_ratio=0.7, current_ratio=1.0,
            operating_margin=0.02, cashflow_coverage=0.8, payment_history=12,
        )]})
        assert result["assessments"][0]["pd"] == round(expected_pd, 4)
    finally:
        _close(eng)


def test_pd_clamped_to_minimum(tmp_path):
    """极优质贷款 PD 被下限截断为 0.001。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [_loan(
            debt_ratio=0.1, current_ratio=3.0, operating_margin=0.3,
            cashflow_coverage=3.0, payment_history=24,
        )]})
        assert result["assessments"][0]["pd"] == 0.001
    finally:
        _close(eng)


def test_pd_clamped_to_maximum(tmp_path):
    """极劣质贷款 PD 被上限截断为 0.99。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [_loan(
            debt_ratio=5.0, current_ratio=0.01, operating_margin=-1.0,
            cashflow_coverage=0.01, payment_history=0,
        )]})
        assert result["assessments"][0]["pd"] == 0.99
    finally:
        _close(eng)


def test_higher_debt_ratio_higher_pd(tmp_path):
    """其他条件相同时，资产负债率越高 PD 越高。"""
    eng = _make_engine(tmp_path)
    try:
        r_low = eng.execute({"loans": [_loan(debt_ratio=0.3)]})
        r_high = eng.execute({"loans": [_loan(debt_ratio=0.9)]})
        assert r_high["assessments"][0]["pd"] > r_low["assessments"][0]["pd"]
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# LGD 计算
# ----------------------------------------------------------------------
def test_lgd_by_collateral_type(tmp_path):
    """不同担保品对应不同 LGD（现金 0.10 / 房产 0.35 / 信用 0.75）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [
            _loan(asset_id="C1", collateral_type="现金", payment_history=24),
            _loan(asset_id="C2", collateral_type="房产", payment_history=24),
            _loan(asset_id="C3", collateral_type="信用", payment_history=24),
        ]})
        by_id = {a["asset_id"]: a for a in result["assessments"]}
        assert by_id["C1"]["lgd"] == 0.10
        assert by_id["C2"]["lgd"] == 0.35
        assert by_id["C3"]["lgd"] == 0.75
    finally:
        _close(eng)


def test_lgd_boosted_for_short_payment_history(tmp_path):
    """还款历史 <6 个月时 LGD 加 0.1（上限 0.9）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [
            _loan(asset_id="P1", collateral_type="房产", payment_history=12),
            _loan(asset_id="P2", collateral_type="房产", payment_history=3),
        ]})
        by_id = {a["asset_id"]: a for a in result["assessments"]}
        assert by_id["P1"]["lgd"] == 0.35
        assert by_id["P2"]["lgd"] == 0.45  # 0.35 + 0.1
    finally:
        _close(eng)


def test_lgd_capped_at_0_9(tmp_path):
    """信用类担保 + 短还款历史 LGD 不超过 0.9。"""
    eng = _make_engine(tmp_path)
    try:
        # payment_history=1 < 6 → LGD 加 0.1（注意 0 会被 or 模式替换为 12）
        result = eng.execute({"loans": [
            _loan(collateral_type="信用", payment_history=1),
        ]})
        assert result["assessments"][0]["lgd"] == 0.85  # 0.75 + 0.1 < 0.9
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# EL / RWA / 资本要求
# ----------------------------------------------------------------------
def test_expected_loss_formula(tmp_path):
    """EL = PD × LGD × EAD。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [_loan(
            remaining_amount=100000, collateral_type="现金", payment_history=24,
            debt_ratio=0.3, current_ratio=2.0, operating_margin=0.15,
            cashflow_coverage=2.0,
        )]})
        a = result["assessments"][0]
        expected_el = round(a["pd"] * a["lgd"] * a["ead"], 2)
        assert a["expected_loss"] == expected_el
    finally:
        _close(eng)


def test_rwa_includes_industry_multiplier(tmp_path):
    """RWA = EAD × risk_weight × industry_multiplier。"""
    eng = _make_engine(tmp_path)
    try:
        # 正常(0.2) + 制造业(1.0) → rwa = 80000 × 0.2 × 1.0 = 16000
        result = eng.execute({"loans": [_loan(
            industry="制造业", remaining_amount=80000,
        )]})
        a = result["assessments"][0]
        assert a["industry_multiplier"] == 1.0
        assert a["rwa"] == round(80000 * 0.2 * 1.0, 2)
    finally:
        _close(eng)


def test_industry_multiplier_values(tmp_path):
    """行业调整因子：房地产 1.3 / 信息技术 0.9 / 制造业 1.0。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [
            _loan(asset_id="I1", industry="房地产"),
            _loan(asset_id="I2", industry="信息技术"),
            _loan(asset_id="I3", industry="制造业"),
        ]})
        by_id = {a["asset_id"]: a for a in result["assessments"]}
        assert by_id["I1"]["industry_multiplier"] == 1.3
        assert by_id["I2"]["industry_multiplier"] == 0.9
        assert by_id["I3"]["industry_multiplier"] == 1.0
    finally:
        _close(eng)


def test_capital_requirement_is_rwa_times_8pct(tmp_path):
    """资本要求 = RWA × 8%。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [_loan(remaining_amount=80000)]})
        a = result["assessments"][0]
        assert a["capital_requirement"] == round(a["rwa"] * 0.08, 2)
    finally:
        _close(eng)


def test_ead_falls_back_to_amount(tmp_path):
    """无 remaining_amount 时 EAD 回退到 amount。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [{
            "asset_id": "E1", "borrower": "X", "amount": 500000,
            "industry": "制造业", "collateral_type": "现金",
            "debt_ratio": 0.3, "current_ratio": 2.0,
            "operating_margin": 0.15, "cashflow_coverage": 2.0, "payment_history": 24,
        }]})
        assert result["assessments"][0]["ead"] == 500000
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 汇总统计 / 风险等级
# ----------------------------------------------------------------------
def test_summary_aggregation(tmp_path):
    """summary 汇总 total_ead / total_el / total_rwa / asset_count。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["asset_count"] == 4
        total_ead = sum(a["ead"] for a in result["assessments"])
        total_el = sum(a["expected_loss"] for a in result["assessments"])
        total_rwa = sum(a["rwa"] for a in result["assessments"])
        assert s["total_ead"] == round(total_ead, 2)
        assert s["total_expected_loss"] == round(total_el, 2)
        assert s["total_rwa"] == round(total_rwa, 2)
    finally:
        _close(eng)


def test_risk_level_high_when_el_ratio_above_5pct(tmp_path):
    """el_ratio > 0.05 → 高风险。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        # sample 的 el_ratio ≈ 0.0514 > 0.05
        assert result["summary"]["risk_level"] == "高风险"
    finally:
        _close(eng)


def test_risk_level_low_for_healthy_portfolio(tmp_path):
    """优质组合 el_ratio <= 0.02 → 低风险。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [_loan(
            remaining_amount=80000, collateral_type="现金", payment_history=24,
        )]})
        assert result["summary"]["risk_level"] == "低风险"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界 / 异常输入
# ----------------------------------------------------------------------
def test_empty_loans(tmp_path):
    """空 loans 列表返回零汇总。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": []})
        assert result["assessments"] == []
        assert result["summary"]["asset_count"] == 0
        assert result["summary"]["total_ead"] == 0
    finally:
        _close(eng)


def test_non_dict_input_raises_value_error(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute(["not", "a", "dict"])
    finally:
        _close(eng)


def test_missing_fields_use_defaults(tmp_path):
    """缺少财务比率字段时使用默认值（不崩）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"loans": [{"asset_id": "M1", "amount": 10000}]})
        a = result["assessments"][0]
        assert a["asset_id"] == "M1"
        assert a["ead"] == 10000
        assert 0 < a["pd"] < 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 模型加载 / DB
# ----------------------------------------------------------------------
def test_db_table_created(tmp_path):
    """engine 初始化后 db 含 credit_assets 表。"""
    db_path = tmp_path / "fi_01_tables.db"
    eng = MLEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            assert "credit_assets" in db.tables()
    finally:
        _close(eng)


def test_model_has_grade_ranges_and_lgd_table(tmp_path):
    """model 含五级分类区间 / 担保品 LGD 表 / 行业调整因子。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.model["grade_ranges"]) == 5
        assert eng.model["collateral_lgd"]["现金"] == 0.10
        assert eng.model["collateral_lgd"]["信用"] == 0.75
        assert eng.model["industry_adjustment"]["房地产"] == 1.3
        assert eng.model["pd_intercept"] == -3.0
    finally:
        _close(eng)


def test_lazy_load_on_execute(tmp_path):
    """不调 setup() 直接 execute 也能懒加载模型。"""
    eng = MLEngine(config={"db_path": str(tmp_path / "fi_01_lazy.db")})
    assert eng.model is None
    try:
        result = eng.execute({"loans": [_loan()]})
        assert eng.model is not None
        assert len(result["assessments"]) == 1
    finally:
        _close(eng)
