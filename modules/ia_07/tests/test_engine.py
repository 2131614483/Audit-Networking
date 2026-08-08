"""[IA-07] engine 单测：整改跟踪状态机 / 超时升级 / 失败风险 / 推荐方案。

RPAEngine 为纯 stdlib 实现，使用状态机驱动整改生命周期。
测试用 tmp_path 隔离 SQLite，通过 created_at/deadline 控制时间窗口。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from modules.ia_07.engine import RPAEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _ts(days_offset: float) -> str:
    """相对现在偏移 days_offset 天的 ISO 时间戳。"""
    return (datetime.now() + timedelta(days=days_offset)).isoformat()


@pytest.fixture
def make_engine(tmp_path):
    """工厂：创建已 setup 的 RPAEngine，tmp_path 隔离 db，自动关闭连接。"""
    created = []

    def _factory(**overrides):
        cfg = {"db_path": str(tmp_path / "ia07_test.db")}
        cfg.update(overrides)
        e = RPAEngine(config=cfg)
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
def test_execute_single_task_returns_one_result(make_engine):
    """单任务 dict 输入 → 输出含 1 条结果。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T1", "finding_id": "F1", "issue_type": "流程缺陷",
        "severity": "重要", "assignee": "张三", "department": "财务部",
        "created_at": _ts(-10), "deadline": _ts(20),
    })
    assert result["total"] == 1
    assert result["tasks"][0]["task_id"] == "T1"


def test_execute_multiple_tasks(make_engine):
    """多任务列表输入 → 输出含 N 条结果。"""
    eng = make_engine()
    result = eng.execute(_sample())
    assert result["total"] == len(_sample())
    for t in result["tasks"]:
        assert "state" in t
        assert "escalation" in t
        assert "failure_risk" in t


def test_postprocess_adds_escalation_labels(make_engine):
    """后处理为每条任务添加 escalation_label / escalation_desc / timestamp。"""
    eng = make_engine()
    result = eng.execute(_sample())
    for t in result["tasks"]:
        assert "escalation_label" in t
        assert "escalation_desc" in t
        assert "timestamp" in t
    assert "generated_at" in result


# ----------------------------------------------------------------------
# 状态机
# ----------------------------------------------------------------------
def test_state_pending_assignment_for_new_task(make_engine):
    """刚创建的任务（days_passed <= 0.5）状态为待分配。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T2", "created_at": _ts(0), "deadline": _ts(30),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    assert result["tasks"][0]["state"] == "待分配"


def test_state_in_progress_when_overdue_short(make_engine):
    """轻度超期（-7 <= days_remaining < 0, severity < 4）→ 整改中。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T3", "created_at": _ts(-10), "deadline": _ts(-3),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    assert result["tasks"][0]["state"] == "整改中"


def test_state_disputed_when_overdue_severe(make_engine):
    """严重发现超期（days_remaining < 0, severity >= 4）→ 争议中。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T4", "created_at": _ts(-15), "deadline": _ts(-5),
        "severity": "严重", "issue_type": "控制缺失",
    })
    assert result["tasks"][0]["state"] == "争议中"


def test_state_closed_when_long_overdue(make_engine):
    """超期 30 天以上 → 已关闭。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T5", "created_at": _ts(-80), "deadline": _ts(-40),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    assert result["tasks"][0]["state"] == "已关闭"


# ----------------------------------------------------------------------
# 升级级别
# ----------------------------------------------------------------------
def test_escalation_zero_for_on_track(make_engine):
    """未超期且未临近截止 → escalation=0。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T6", "created_at": _ts(-5), "deadline": _ts(60),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    assert result["tasks"][0]["escalation"] == 0


def test_escalation_increases_with_overdue(make_engine):
    """超期越久，升级级别越高。"""
    eng = make_engine()
    short_overdue = eng.execute({
        "task_id": "S", "created_at": _ts(-15), "deadline": _ts(-5),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    long_overdue = eng.execute({
        "task_id": "L", "created_at": _ts(-60), "deadline": _ts(-20),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    assert long_overdue["tasks"][0]["escalation"] > short_overdue["tasks"][0]["escalation"]


# ----------------------------------------------------------------------
# 失败风险
# ----------------------------------------------------------------------
def test_failure_risk_severity_weighted(make_engine):
    """高严重度 → 更高失败风险。"""
    eng = make_engine()
    low = eng.execute({
        "task_id": "LO", "created_at": _ts(-5), "deadline": _ts(20),
        "severity": "一般", "issue_type": "流程缺陷",
    })
    high = eng.execute({
        "task_id": "HI", "created_at": _ts(-5), "deadline": _ts(20),
        "severity": "严重", "issue_type": "流程缺陷",
    })
    assert high["tasks"][0]["failure_risk"] > low["tasks"][0]["failure_risk"]


def test_risk_level_labels(make_engine):
    """risk_level 为 高/中/低 之一。"""
    eng = make_engine()
    result = eng.execute(_sample())
    for t in result["tasks"]:
        assert t["risk_level"] in ("高", "中", "低")


# ----------------------------------------------------------------------
# 推荐方案 / 下一步动作
# ----------------------------------------------------------------------
def test_recommended_plan_has_strategies(make_engine):
    """每条任务返回 3 个推荐方案。"""
    eng = make_engine()
    result = eng.execute({
        "task_id": "T7", "created_at": _ts(-5), "deadline": _ts(20),
        "severity": "重要", "issue_type": "流程缺陷",
    })
    plan = result["tasks"][0]["recommended_plan"]
    assert len(plan) == 3
    for p in plan:
        assert "strategy" in p
        assert "expected_effectiveness" in p
        assert "typical_duration_days" in p


def test_next_action_non_empty(make_engine):
    """每条任务都有非空的 next_action。"""
    eng = make_engine()
    result = eng.execute(_sample())
    for t in result["tasks"]:
        assert isinstance(t["next_action"], str)
        assert len(t["next_action"]) > 0
