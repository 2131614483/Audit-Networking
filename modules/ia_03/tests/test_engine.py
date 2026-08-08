"""[IA-03] engine 单测：审计资源智能分配（GA 优化 + 技能匹配）。

ResourceEngine 为纯 stdlib 遗传算法实现，技能匹配用加权余弦相似度，
目标函数含 6 维度（技能/负载/成本/发展/协同/连续性）+ 硬约束惩罚。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ia_03.engine import ResourceEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


@pytest.fixture
def make_engine(tmp_path):
    """工厂 fixture：每个测试用 tmp_path 隔离 db，结束后 close。"""
    created = []

    def _factory(**overrides):
        eng = ResourceEngine(config={"db_path": tmp_path / "ia_03.db", **overrides})
        eng.setup()
        created.append(eng)
        return eng

    yield _factory
    for e in created:
        e.close()


# ----------------------------------------------------------------------
# 基本分配
# ----------------------------------------------------------------------
def test_allocate_returns_plans_and_best(make_engine):
    """给定审计师与项目，返回 plans 列表与 best_plan。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert result["action"] == "allocate"
    assert len(result["plans"]) > 0
    assert result["best_plan"] is not None
    assert result["best_plan"]["plan_id"] == "plan_ga_best"


def test_assignment_count_matches_required(make_engine):
    """每个项目分配人数 = required_count。"""
    eng = make_engine()
    result = eng.execute(_sample())
    best = result["best_plan"]
    for proj in _sample()["projects"]:
        pid = proj["project_id"]
        assert len(best["assignments"][pid]) == proj["required_count"]


def test_best_plan_is_highest_score(make_engine):
    """best_plan 得分最高，plans 按得分降序。"""
    eng = make_engine()
    result = eng.execute(_sample())
    plans = result["plans"]
    scores = [p["score"] for p in plans]
    assert result["best_plan"]["score"] == max(scores)
    assert plans[0]["score"] >= plans[1]["score"]


def test_plans_count_is_four(make_engine):
    """GA 返回 best + rank2-4 共 4 个方案。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert len(result["plans"]) == 4


def test_total_projects_and_auditors(make_engine):
    """输出统计 total_projects / total_auditors。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert result["total_projects"] == 2
    assert result["total_auditors"] == 4


# ----------------------------------------------------------------------
# 评分维度
# ----------------------------------------------------------------------
def test_skill_match_positive(make_engine):
    """技能匹配维度得分为正。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert result["best_plan"]["skill_match"] > 0


def test_fitness_dimensions_present(make_engine):
    """best_plan 含 6 维度评分字段。"""
    eng = make_engine()
    best = eng.execute(_sample())["best_plan"]
    for key in ("skill_match", "load_balance", "cost_efficiency",
                "development", "team_synergy", "continuity"):
        assert key in best


def test_min_senior_constraint_checked(make_engine):
    """min_senior 约束参与 violations 计算（字段存在且 >= 0）。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert result["best_plan"]["violations"] >= 0


# ----------------------------------------------------------------------
# summary / 持久化
# ----------------------------------------------------------------------
def test_summary_structure(make_engine):
    """summary 字段与 best_plan 一致。"""
    eng = make_engine()
    result = eng.execute(_sample())
    summary = result["summary"]
    best = result["best_plan"]
    assert summary["total_plans"] == 4
    assert summary["best_score"] == best["score"]
    assert summary["best_skill_match"] == best["skill_match"]
    assert summary["best_violations"] == best["violations"]


def test_persistence_plans_written_to_db(make_engine):
    """execute 后 plans 与 assignments 写入 db。"""
    eng = make_engine()
    eng.execute(_sample())
    assert eng.db.count("plans") == 4
    assert eng.db.count("assignments") > 0


def test_auditor_loads_populated(make_engine):
    """best_plan 的 auditor_loads 非空，且每人 > 0。"""
    eng = make_engine()
    best = eng.execute(_sample())["best_plan"]
    assert len(best["auditor_loads"]) > 0
    for load in best["auditor_loads"].values():
        assert load > 0


# ----------------------------------------------------------------------
# 边界 / 可复现性
# ----------------------------------------------------------------------
def test_empty_auditors_returns_empty(make_engine):
    """无审计师 → 空 plans，best_plan=None。"""
    eng = make_engine()
    result = eng.execute({"auditors": [], "projects": [{"project_id": "P1", "required_count": 1}]})
    assert result["plans"] == []
    assert result["best_plan"] is None


def test_empty_projects_returns_empty(make_engine):
    """无项目 → 空 plans，best_plan=None。"""
    eng = make_engine()
    result = eng.execute({"auditors": [{"auditor_id": "A1"}], "projects": []})
    assert result["plans"] == []
    assert result["best_plan"] is None


def test_non_dict_input_raises(make_engine):
    """非 dict 输入抛 ValueError。"""
    eng = make_engine()
    with pytest.raises(ValueError):
        eng.execute("not a dict")


def test_reproducible_with_same_seed(tmp_path):
    """相同 seed → 相同 best_score 与 assignments。"""
    e1 = ResourceEngine(config={"db_path": tmp_path / "e1.db", "seed": 42})
    e1.setup()
    e2 = ResourceEngine(config={"db_path": tmp_path / "e2.db", "seed": 42})
    e2.setup()
    try:
        r1 = e1.execute(_sample())
        r2 = e2.execute(_sample())
        assert r1["best_plan"]["score"] == r2["best_plan"]["score"]
        assert r1["best_plan"]["assignments"] == r2["best_plan"]["assignments"]
    finally:
        e1.close()
        e2.close()
