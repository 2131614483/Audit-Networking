"""[IA-06] engine 单测：审计价值量化 / Monte Carlo / ROI / 归因分配。

MLEngine 为纯 stdlib 实现，使用 Monte Carlo 模拟（10000 次）量化内审五维价值。
测试用 tmp_path 隔离 SQLite，seed 固定保证可复现。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ia_06.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


@pytest.fixture
def make_engine(tmp_path):
    """工厂：创建已 setup 的 MLEngine，tmp_path 隔离 db，自动关闭连接。"""
    created = []

    def _factory(**overrides):
        cfg = {"db_path": str(tmp_path / "ia06_test.db"), "seed": 42}
        cfg.update(overrides)
        e = MLEngine(config=cfg)
        e.setup()
        created.append(e)
        return e

    yield _factory
    for e in created:
        if getattr(e, "db", None):
            e.db.close()


# ----------------------------------------------------------------------
# 基础执行 / 输出结构
# ----------------------------------------------------------------------
def test_execute_with_sample_returns_full_structure(make_engine):
    """用 sample_input 端到端执行，返回五维价值 + Monte Carlo + 归因。"""
    eng = make_engine()
    result = eng.execute(_sample())
    for key in ("total_point", "breakdown", "percentage", "total_cost",
                "roi_point", "roi_p50", "monte_carlo", "attribution",
                "sensitivity", "n_findings", "generated_at", "summary_text"):
        assert key in result, f"missing key: {key}"
    assert result["n_findings"] == 3


def test_execute_with_findings_list(make_engine):
    """直接传 findings 列表（非 dict）也能正常执行。"""
    eng = make_engine()
    findings = [
        {"finding_id": "X1", "loss_recovered": 50, "cost_saving": 30,
         "efficiency_improvement": 0.2, "impact_amount": 100,
         "probability_before": 0.3, "probability_after": 0.05, "fte_days": 10},
    ]
    result = eng.execute(findings)
    assert result["n_findings"] == 1
    assert result["breakdown"]["direct_financial"] > 0


def test_empty_findings_returns_zero(make_engine):
    """空 findings 列表 → total_point=0，不崩溃。"""
    eng = make_engine()
    result = eng.execute({"findings": [], "total_cost": 100})
    assert result["total_point"] == 0
    assert result["n_findings"] == 0


# ----------------------------------------------------------------------
# Monte Carlo
# ----------------------------------------------------------------------
def test_monte_carlo_percentile_ordering(make_engine):
    """P10 <= P50 <= P90。"""
    eng = make_engine()
    result = eng.execute(_sample())
    mc = result["monte_carlo"]
    assert mc["p10"] <= mc["p50"] <= mc["p90"]


def test_reproducible_with_same_seed(make_engine):
    """相同 seed → 相同 monte_carlo 结果（可复现）。"""
    e1 = make_engine(seed=99)
    r1 = e1.execute(_sample())
    e2 = make_engine(seed=99)  # setup 重置 random.seed(99)
    r2 = e2.execute(_sample())
    assert r1["monte_carlo"] == r2["monte_carlo"]
    assert r1["total_point"] == r2["total_point"]


# ----------------------------------------------------------------------
# 价值构成 / 占比
# ----------------------------------------------------------------------
def test_breakdown_has_five_dimensions(make_engine):
    """breakdown 含五维：直接财务/风险降低/战略/合规/预防。"""
    eng = make_engine()
    result = eng.execute(_sample())
    expected = {"direct_financial", "risk_reduction", "strategic",
                "compliance", "prevention"}
    assert set(result["breakdown"].keys()) == expected
    for v in result["breakdown"].values():
        assert isinstance(v, (int, float))
        assert v >= 0


def test_percentage_sums_approx_100(make_engine):
    """percentage 各维度占比之和约等于 100。"""
    eng = make_engine()
    result = eng.execute(_sample())
    total_pct = sum(result["percentage"].values())
    assert abs(total_pct - 100.0) < 0.5  # 四舍五入误差


# ----------------------------------------------------------------------
# ROI
# ----------------------------------------------------------------------
def test_roi_point_calculation(make_engine):
    """roi_point = (total_point - total_cost) / total_cost。"""
    eng = make_engine()
    result = eng.execute(_sample())
    expected_roi = round(
        (result["total_point"] - result["total_cost"]) / result["total_cost"], 2)
    assert result["roi_point"] == expected_roi


# ----------------------------------------------------------------------
# 归因分配
# ----------------------------------------------------------------------
def test_attribution_contribution_in_range(make_engine):
    """每条 finding 的贡献度在 [0.4, 0.9]。"""
    eng = make_engine()
    result = eng.execute(_sample())
    attr = result["attribution"]
    assert attr["range"]["min"] == 0.4
    assert attr["range"]["max"] == 0.9
    for pf in attr["per_finding"]:
        assert 0.4 <= pf["contribution"] <= 0.9
    assert 0.4 <= attr["average_contribution"] <= 0.9


def test_attribution_adjusted_by_flags(make_engine):
    """first_identified + 高 severity 提升贡献度；management_knew/external_force 降低。"""
    eng = make_engine()
    high = eng.execute([{
        "finding_id": "H", "loss_recovered": 10, "cost_saving": 10,
        "impact_amount": 100, "probability_before": 0.3, "probability_after": 0.05,
        "severity": 4, "first_identified": True,
        "management_knew": False, "external_force": False,
    }])
    low = eng.execute([{
        "finding_id": "L", "loss_recovered": 10, "cost_saving": 10,
        "impact_amount": 100, "probability_before": 0.3, "probability_after": 0.05,
        "severity": 2, "first_identified": False,
        "management_knew": True, "external_force": True,
    }])
    assert high["attribution"]["average_contribution"] > low["attribution"]["average_contribution"]


# ----------------------------------------------------------------------
# 后处理
# ----------------------------------------------------------------------
def test_summary_text_contains_key_info(make_engine):
    """summary_text 含审计总价值、成本、ROI 等关键信息。"""
    eng = make_engine()
    result = eng.execute(_sample())
    text = result["summary_text"]
    assert "审计总价值" in text
    assert "审计总成本" in text
    assert "审计ROI" in text
    assert "价值构成" in text


def test_total_cost_from_input_overrides_default(make_engine):
    """input 中的 total_cost 覆盖默认成本。"""
    eng = make_engine()
    result = eng.execute({"findings": _sample()["findings"], "total_cost": 1000.0})
    assert result["total_cost"] == 1000.0
