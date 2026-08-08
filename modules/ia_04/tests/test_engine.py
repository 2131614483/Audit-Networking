"""[IA-04] engine 单测：审计价值仪表板（三层 KPI + 价值量化 + 热力图 + What-If）。

DashboardEngine 为纯 stdlib 实现，价值量化含 4 维度（财务/风险/合规/战略），
KPI 分战略/运营/执行三层，附风险覆盖热力图与趋势分析。

engine bug workaround：_compute_operational 的 sum(spans) start=0 与 timedelta
相加 TypeError（projects 非空时必崩）。不改 engine.py，在 fixture 中用
_fixed_compute_operational 修复实例方法（仅改 sum 的 start=timedelta(0)）。
"""
from __future__ import annotations

import json
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from modules.ia_04.engine import DashboardEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _fixed_compute_operational(self, findings, projects, audit_hours):
    """engine bug workaround：sum(spans) → sum(spans, timedelta(0))，其余逻辑不变。"""
    completed = [p for p in projects if p["status"] == "已完成"]
    on_time = sum(1 for p in completed if p.get("completed_on_time", False))
    on_time_rate = on_time / max(len(completed), 1) * 100
    total_budget_hours = sum(p["budget_hours"] for p in projects)
    total_actual_hours = sum(p["actual_hours"] for p in projects)
    budget_execution = (total_actual_hours / max(total_budget_hours, 1)) * 100
    spans = [
        (p["actual_end"] or p.get("planned_end") or datetime.now())
        - (p["planned_start"] or datetime.now())
        for p in projects
    ]
    total_project_span = sum(spans, timedelta(0))
    avg_span_days = (
        total_project_span.total_seconds() / 86400 / max(len(projects), 1)
        if hasattr(total_project_span, "total_seconds") else 0
    )
    adopted = sum(1 for f in findings if f.get("suggestion_adopted", False))
    adoption_rate = adopted / max(len(findings), 1) * 100
    capacity_util = (total_actual_hours / max(audit_hours, 1)) * 100
    return {
        "on_time_delivery_rate": round(on_time_rate, 2),
        "budget_execution_rate": round(budget_execution, 2),
        "avg_audit_cycle_days": round(avg_span_days, 1),
        "suggestion_adoption_rate": round(adoption_rate, 2),
        "auditor_utilization": round(capacity_util, 2),
        "projects_completed": len(completed),
        "projects_on_time": on_time,
    }


@pytest.fixture
def make_engine(tmp_path):
    """工厂 fixture：tmp_path 隔离 db，结束前 close；修复 _compute_operational bug。"""
    created = []

    def _factory(**overrides):
        eng = DashboardEngine(config={"db_path": tmp_path / "ia_04.db", **overrides})
        eng.setup()
        eng._compute_operational = types.MethodType(_fixed_compute_operational, eng)
        created.append(eng)
        return eng

    yield _factory
    for e in created:
        e.close()


# ----------------------------------------------------------------------
# 基本输出
# ----------------------------------------------------------------------
def test_dashboard_action_and_counts(make_engine):
    """action=dashboard，统计 findings/projects 数量。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert result["action"] == "dashboard"
    assert result["total_findings"] == 3
    assert result["total_projects"] == 2


def test_strategic_kpis_structure(make_engine):
    """战略层 KPI 含核心字段。"""
    eng = make_engine()
    strat = eng.execute(_sample())["strategic"]
    for key in ("audit_total_value", "audit_roi", "audit_roi_ratio",
                "risk_coverage", "remediation_rate", "management_satisfaction",
                "high_risk_findings", "budget"):
        assert key in strat
    assert strat["budget"] == 20_000_000


def test_operational_kpis_structure(make_engine):
    """运营层 KPI 含核心字段，projects_completed/on_time 正确。"""
    eng = make_engine()
    ops = eng.execute(_sample())["operational"]
    for key in ("on_time_delivery_rate", "budget_execution_rate",
                "avg_audit_cycle_days", "suggestion_adoption_rate",
                "auditor_utilization", "projects_completed", "projects_on_time"):
        assert key in ops
    assert ops["projects_completed"] == 1
    assert ops["projects_on_time"] == 1


# ----------------------------------------------------------------------
# 价值量化
# ----------------------------------------------------------------------
def test_value_quantification_four_dimensions(make_engine):
    """单个 finding 量化出 4 维度价值与组合总价值。"""
    eng = make_engine()
    prepared = eng._preprocess(_sample())
    q = eng._quantify_value(prepared["findings"][0])  # F001 合规类
    assert q["financial_value"] > 0
    assert q["risk_value"] > 0
    assert q["compliance_value"] > 0   # 合规类
    assert q["strategic_value"] > 0    # suggestion_adopted
    assert q["total_value"] > 0


def test_compliance_finding_has_compliance_value(make_engine):
    """合规类 finding 的 compliance_value > 0，非合规类为 0。"""
    eng = make_engine()
    prepared = eng._preprocess(_sample())
    qf = [eng._quantify_value(f) for f in prepared["findings"]]
    by_id = {q["finding_id"]: q for q in qf}
    assert by_id["F001"]["compliance_value"] > 0   # 合规类 + GDPR
    assert by_id["F002"]["compliance_value"] == 0  # 内部控制，无 regulations


def test_strategic_finding_has_strategic_value(make_engine):
    """战略类 finding 的 strategic_value > 0，非战略类为 0。"""
    eng = make_engine()
    prepared = eng._preprocess(_sample())
    qf = [eng._quantify_value(f) for f in prepared["findings"]]
    by_id = {q["finding_id"]: q for q in qf}
    assert by_id["F003"]["strategic_value"] > 0   # 战略建议类
    assert by_id["F002"]["strategic_value"] == 0  # 非战略类，未采纳


# ----------------------------------------------------------------------
# 战略 KPI 计算
# ----------------------------------------------------------------------
def test_roi_positive(make_engine):
    """审计 ROI > 0（总价值 / 预算）。"""
    eng = make_engine()
    strat = eng.execute(_sample())["strategic"]
    assert strat["audit_roi"] > 0
    assert strat["audit_roi_ratio"] == round(strat["audit_roi"] / 100, 2)


def test_remediation_rate(make_engine):
    """整改率 = 已整改 finding 占比（1/3 ≈ 33.33）。"""
    eng = make_engine()
    strat = eng.execute(_sample())["strategic"]
    assert strat["remediation_rate"] == round(1 / 3 * 100, 2)


# ----------------------------------------------------------------------
# 热力图 / top_findings / 趋势
# ----------------------------------------------------------------------
def test_heatmap_structure_and_levels(make_engine):
    """热力图含 bu × category 矩阵，level ∈ {green, yellow, red}。"""
    eng = make_engine()
    hm = eng.execute(_sample())["heatmap"]
    assert set(hm.keys()) == {"business_units", "categories", "cells"}
    assert len(hm["cells"]) == len(hm["business_units"]) * len(hm["categories"])
    levels = {c["level"] for c in hm["cells"]}
    assert levels <= {"green", "yellow", "red"}
    # 零售银行有严重发现 → 至少一个 yellow
    assert "yellow" in levels


def test_top_findings_sorted_desc(make_engine):
    """top_findings 按 total_value 降序，rank 从 1 开始。"""
    eng = make_engine()
    top = eng.execute(_sample())["top_findings"]
    assert len(top) == 3
    values = [t["total_value"] for t in top]
    assert values == sorted(values, reverse=True)
    assert [t["rank"] for t in top] == [1, 2, 3]


def test_trends_value_breakdown(make_engine):
    """趋势分解含 4 维度，且均 > 0（sample 覆盖 4 类价值）。"""
    eng = make_engine()
    breakdown = eng.execute(_sample())["trends"]["value_breakdown"]
    for key in ("financial", "risk", "compliance", "strategic"):
        assert key in breakdown
        assert breakdown[key] > 0


# ----------------------------------------------------------------------
# executive_summary / 持久化 / What-If / 边界
# ----------------------------------------------------------------------
def test_executive_summary(make_engine):
    """后处理注入 executive_summary，含汇总指标。"""
    eng = make_engine()
    result = eng.execute(_sample())
    es = result["executive_summary"]
    assert es["audit_total_value_wan"] > 0
    assert es["total_findings"] == 3
    assert es["total_projects"] == 2
    assert es["on_time_delivery"] == 100.0


def test_persistence_kpi_snapshots(make_engine):
    """execute 后三层 KPI 数值写入 kpi_snapshots 表。"""
    eng = make_engine()
    eng.execute(_sample())
    assert eng.db.count("kpi_snapshots") > 0
    layers = {row["layer"] for row in eng.db.all("kpi_snapshots")}
    assert {"strategic", "operational", "executive"} <= layers


def test_what_if_scenario(make_engine):
    """scenario 参数触发 What-If 分析，返回新旧 ROI 对比。"""
    eng = make_engine()
    data = _sample()
    data["scenario"] = {
        "name": "提高整改系数",
        "remediation_coef_multiplier": 1.5,
        "risk_reduction_multiplier": 1.2,
        "new_budget": 15_000_000,
    }
    result = eng.execute(data)
    sc = result["scenario"]
    assert sc["scenario_name"] == "提高整改系数"
    assert "value_delta" in sc
    assert "roi_delta" in sc
    assert sc["new_roi"] != sc["original_roi"]


def test_empty_findings(make_engine):
    """空 findings/projects → 0 总价值，结构完整。"""
    eng = make_engine()
    result = eng.execute({"findings": [], "projects": []})
    assert result["total_findings"] == 0
    assert result["total_projects"] == 0
    assert result["strategic"]["audit_total_value"] == 0
    assert result["top_findings"] == []


def test_non_dict_input_raises(make_engine):
    """非 dict 输入抛 ValueError。"""
    eng = make_engine()
    with pytest.raises(ValueError):
        eng.execute("not a dict")
