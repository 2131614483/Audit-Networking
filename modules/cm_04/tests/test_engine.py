"""[CM-04] engine 单测：风险损失测算 / ROI / Monte Carlo / 敏感性分析。

MLEngine 基于 PortableDB 持久化风险目录与估值记录，
支持 6 种 action：quantify / roi / simulate / sensitivity / add_risk / efficiency。
每个测试用 tmp_path 隔离 db，纯 stdlib（三角分布采样 + DCF + 二分法 IRR）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cm_04.engine import MLEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    eng = MLEngine(config={
        "db_path": str(tmp_path / "cm_04_engine.db"),
        **overrides,
    })
    eng.setup()
    return eng


def _close(eng: MLEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# quantify 动作 —— 风险损失测算
# ----------------------------------------------------------------------
def test_quantify_returns_breakdown(tmp_path):
    """quantify 返回含 4 个价值维度的 breakdown。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["action"] == "quantify"
        bd = result["breakdown"]
        assert "risk_avoided" in bd
        assert "efficiency_saved" in bd
        assert "quality_improved" in bd
        assert "compliance_gained" in bd
    finally:
        _close(eng)


def test_quantify_totals_structure(tmp_path):
    """quantify 的 totals 含年度总价值 + 各分项。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        t = result["totals"]
        assert "annual_total_value" in t
        assert "annual_risk_avoided" in t
        assert "annual_efficiency_saved" in t
        assert "annual_quality_value" in t
        assert "annual_compliance_value" in t
        # 总值 = 各分项之和
        assert t["annual_total_value"] == round(
            t["annual_risk_avoided"] + t["annual_efficiency_saved"]
            + t["annual_quality_value"] + t["annual_compliance_value"], 2
        )
    finally:
        _close(eng)


def test_quantify_roi_metrics(tmp_path):
    """quantify 返回 roi_metrics（roi_percent / net_benefit / payback_months / npv）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        rm = result["roi_metrics"]
        assert "roi_percent" in rm
        assert "net_benefit" in rm
        assert "payback_months" in rm
        assert "npv" in rm
        assert rm["net_benefit"] > 0  # 收益大于成本
    finally:
        _close(eng)


def test_quantify_risk_avoided_items(tmp_path):
    """risk_avoided 含 6 条默认风险的测算明细。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        items = result["breakdown"]["risk_avoided"]["items"]
        assert len(items) == 6
        for item in items:
            assert "risk_id" in item
            assert "annual_avoided" in item
            assert item["annual_avoided"] >= 0
    finally:
        _close(eng)


def test_quantify_efficiency_items(tmp_path):
    """efficiency_saved 含 5 个活动的节约明细。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        items = result["breakdown"]["efficiency_saved"]["items"]
        assert len(items) == 5
        for item in items:
            assert "activity" in item
            assert "saved_days_year" in item
            assert "saved_cost_year" in item
            assert item["saved_cost_year"] >= 0
    finally:
        _close(eng)


def test_quantify_npv_positive_for_profitable(tmp_path):
    """收益远大于成本时 NPV 为正。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["roi_metrics"]["npv"] > 0
    finally:
        _close(eng)


def test_quantify_custom_risks_used(tmp_path):
    """提供自定义 risks 时使用自定义风险而非默认。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "quantify",
            "risks": [
                {"risk_id": "X01", "name": "自定义风险",
                 "baseline_prob": 0.1, "mitigated_prob": 0.02, "avg_impact": 1000000,
                 "category": "风险避免"},
            ],
            "time_horizon_years": 1,
        })
        items = result["breakdown"]["risk_avoided"]["items"]
        assert len(items) == 1
        assert items[0]["risk_id"] == "X01"
    finally:
        _close(eng)


def test_quantify_costs_structure(tmp_path):
    """quantify 的 costs 含初始投资 + 运营/维护/培训成本。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        c = result["costs"]
        assert c["initial_investment"] == 7200000
        assert c["annual_operating_cost"] == 2000000
        assert c["annual_maintenance_cost"] == 200000
        assert c["annual_training_cost"] == 100000
        assert c["annual_total_cost"] == 2300000
    finally:
        _close(eng)


def test_quantify_risk_avoided_calculation(tmp_path):
    """风险避免金额 = (基准概率 - 缓释概率) × 平均影响 × 12。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "quantify",
            "risks": [
                {"risk_id": "T01", "name": "测试",
                 "baseline_prob": 0.10, "mitigated_prob": 0.02,
                 "avg_impact": 1000000, "category": "风险避免"},
            ],
            "time_horizon_years": 1,
        })
        item = result["breakdown"]["risk_avoided"]["items"][0]
        # (0.10 - 0.02) * 1000000 * 12 = 960000
        assert item["annual_avoided"] == 960000
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# roi 动作 —— ROI & NPV 分析
# ----------------------------------------------------------------------
def test_roi_returns_metrics(tmp_path):
    """roi 返回 roi_percent / payback_years / npv / irr_percent。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "roi",
            "initial_investment": 5000000,
            "annual_cost": 2000000,
            "annual_revenue": 5000000,
            "time_horizon_years": 5,
        })
        assert result["action"] == "roi"
        assert "roi_percent" in result
        assert "payback_years" in result
        assert "payback_months" in result
        assert "npv" in result
        assert "irr_percent" in result
    finally:
        _close(eng)


def test_roi_yearly_projection(tmp_path):
    """roi 返回逐年现金流预测。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "roi",
            "initial_investment": 5000000,
            "annual_cost": 2000000,
            "annual_revenue": 5000000,
            "time_horizon_years": 3,
        })
        yearly = result["yearly_projection"]
        assert len(yearly) == 3
        for y in yearly:
            assert "year" in y
            assert "revenue" in y
            assert "cost" in y
            assert "net" in y
            assert "cumulative_net" in y
    finally:
        _close(eng)


def test_roi_calculates_net_and_payback(tmp_path):
    """roi 动作计算净收益和回收期。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "roi",
            "initial_investment": 5000000,
            "annual_cost": 2000000,
            "annual_revenue": 5000000,
            "time_horizon_years": 3,
        })
        assert result["annual_net"] == 3000000
        assert result["payback_years"] > 0
        assert result["roi_percent"] > 0
    finally:
        _close(eng)


def test_roi_positive_for_high_revenue(tmp_path):
    """收入远大于成本时 roi_percent 为正。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "roi",
            "initial_investment": 1000000,
            "annual_cost": 500000,
            "annual_revenue": 3000000,
            "time_horizon_years": 5,
        })
        assert result["roi_percent"] > 0
        assert result["annual_net"] == 2500000
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# simulate 动作 —— Monte Carlo 模拟
# ----------------------------------------------------------------------
def test_simulate_returns_statistics(tmp_path):
    """simulate 返回含 P10/P50/P90 分位数的统计。"""
    eng = _make_engine(tmp_path, seed=42)
    try:
        result = eng.execute({
            "action": "simulate",
            "num_simulations": 200,
            "scenario": "base",
        })
        assert result["action"] == "simulate"
        assert result["num_simulations"] == 200
        stats = result["statistics"]
        for key in ("total_revenue", "net_benefit", "roi_percent", "risk_avoided"):
            assert key in stats
            s = stats[key]
            assert "mean" in s
            assert "p10" in s
            assert "p50" in s
            assert "p90" in s
            assert "stdev" in s
            assert s["p10"] <= s["p50"] <= s["p90"]
    finally:
        _close(eng)


def test_simulate_sample_size(tmp_path):
    """simulate 返回 sample_size（最多 10 个样本）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "simulate",
            "num_simulations": 100,
        })
        assert result["sample_size"] <= 10
    finally:
        _close(eng)


def test_simulate_p10_le_p50_le_p90(tmp_path):
    """分位数满足 P10 ≤ P50 ≤ P90。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "simulate",
            "num_simulations": 500,
        })
        for key, s in result["statistics"].items():
            assert s["p10"] <= s["p50"]
            assert s["p50"] <= s["p90"]
            assert s["min"] <= s["max"]
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# add_risk 动作
# ----------------------------------------------------------------------
def test_add_risk_to_model(tmp_path):
    """add_risk 把风险加入 model.risks。"""
    eng = _make_engine(tmp_path)
    try:
        before = len(eng.model["risks"])
        result = eng.execute({
            "action": "add_risk",
            "risk": {"risk_id": "NEW01", "name": "新风险",
                     "baseline_prob": 0.1, "mitigated_prob": 0.02,
                     "avg_impact": 800000, "risk_type": "custom"},
        })
        assert result["action"] == "add_risk"
        assert result["added_risk_id"] == "NEW01"
        assert len(eng.model["risks"]) == before + 1
    finally:
        _close(eng)


def test_add_risk_persists_to_db(tmp_path):
    """add_risk 持久化到 DB risks 表。"""
    db_path = tmp_path / "cm_04_addrisk.db"
    eng = MLEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        eng.execute({
            "action": "add_risk",
            "risk": {"risk_id": "DB01", "name": "DB风险",
                     "baseline_prob": 0.08, "mitigated_prob": 0.01,
                     "avg_impact": 3000000, "risk_type": "custom"},
        })
    finally:
        _close(eng)
    with PortableDB(db_path) as db:
        rows = db.all("risks")
    ids = {r["risk_id"] for r in rows}
    assert "DB01" in ids


def test_add_risk_defaults_category(tmp_path):
    """add_risk 默认 category 为风险避免。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "add_risk",
            "risk": {"risk_id": "CAT01", "name": "无类别风险",
                     "baseline_prob": 0.05, "mitigated_prob": 0.01, "avg_impact": 500000},
        })
        new_risk = [r for r in eng.model["risks"] if r["risk_id"] == "CAT01"][0]
        assert new_risk["category"] == "风险避免"
        assert new_risk["risk_type"] == "custom"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# efficiency 动作
# ----------------------------------------------------------------------
def test_efficiency_returns_items(tmp_path):
    """efficiency 返回各活动节约明细 + 年度总额。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"action": "efficiency"})
        assert "items" in result
        assert "annual_total" in result
        assert len(result["items"]) == 5
        assert result["annual_total"] > 0
    finally:
        _close(eng)


def test_efficiency_custom_baselines(tmp_path):
    """提供 custom_baselines 时使用自定义基线。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "efficiency",
            "custom_baselines": {
                "task_a": {"traditional_person_days_per_month": 100,
                           "continuous_person_days_per_month": 10, "unit_cost": 2000},
            },
        })
        assert len(result["items"]) == 1
        assert result["items"][0]["activity"] == "task_a"
        # (100-10)*12 * 2000 = 2160000
        assert result["items"][0]["saved_cost_year"] == 2160000
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 后处理 / 模型加载
# ----------------------------------------------------------------------
def test_postprocess_adds_engine_and_timestamp(tmp_path):
    """后处理给结果加 engine + timestamp 标记。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["engine"] == "CM-04-ValueQuantification"
        assert "timestamp" in result
    finally:
        _close(eng)


def test_db_tables_created_on_load(tmp_path):
    """engine 初始化后 db 含 risks + valuations 表。"""
    db_path = tmp_path / "cm_04_tables.db"
    eng = MLEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert "risks" in tables
        assert "valuations" in tables
    finally:
        _close(eng)


def test_db_seeded_with_default_risks(tmp_path):
    """engine 初始化后 risks 表含 6 条默认风险。"""
    db_path = tmp_path / "cm_04_seed.db"
    eng = MLEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            count = db.count("risks")
        assert count == 6
    finally:
        _close(eng)


def test_model_has_risks_and_efficiency(tmp_path):
    """model 含 6 条风险 + 5 个效率基线 + 折现率。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.model["risks"]) == 6
        assert len(eng.model["efficiency"]) == 5
        assert eng.model["discount_rate"] == 0.08
    finally:
        _close(eng)


def test_discount_rate_configurable(tmp_path):
    """discount_rate 可通过 config 配置。"""
    eng = _make_engine(tmp_path, discount_rate=0.12)
    try:
        assert eng.model["discount_rate"] == 0.12
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 输入边界
# ----------------------------------------------------------------------
def test_invalid_input_raises_value_error(tmp_path):
    """无法识别的输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute(12345)
    finally:
        _close(eng)


def test_unknown_action_raises_value_error(tmp_path):
    """未知 action 抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute({"action": "nonexistent_action"})
    finally:
        _close(eng)


def test_setup_loads_model(tmp_path):
    """setup() 后 model 加载完成。"""
    eng = MLEngine(config={"db_path": str(tmp_path / "cm_04_setup.db")})
    assert eng.model is None
    eng.setup()
    try:
        assert eng.model is not None
        assert "risks" in eng.model
        assert "efficiency" in eng.model
    finally:
        _close(eng)
