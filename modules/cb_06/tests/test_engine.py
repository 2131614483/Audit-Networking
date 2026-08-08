"""[CB-06] engine 单测：指令生成 / 进度追踪 / 结果汇总 / 知识库检索。

LLMEngine 为纯 stdlib 实现（模板渲染 + difflib 相似度），不依赖外部 LLM。
内置 3 个风险等级指令模板 + 5 个审计程序 + 4 条最佳实践知识。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cb_06.engine import LLMEngine, _render_template, _parse_date
from datetime import datetime

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 智能指令生成
# ----------------------------------------------------------------------
def test_generate_orders_for_multiple_subsidiaries():
    """为 3 个子公司生成 3 条指令。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["group_name"] == "测试集团"
    assert result["total_orders"] == 3
    assert len(result["orders"]) == 3
    # 每条指令含 task_id / title / instructions
    for o in result["orders"]:
        assert o["task_id"].startswith("TASK-")
        assert "title" in o
        assert "instructions" in o
        assert o["status"] == "pending"
        assert o["deadline"] == "2025-03-15"


def test_high_risk_uses_high_risk_template():
    """高风险子公司使用加强版模板（TPL-003）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    high_risk = next(o for o in result["orders"] if o["risk_level"] == "high")
    # TPL-003 title 含 "加强版"
    assert "加强版" in high_risk["title"]
    assert "北京子公司" in high_risk["title"]
    # instructions 含高风险特有内容
    assert "强制" in high_risk["instructions"] or "全面" in high_risk["instructions"]


def test_low_risk_uses_low_risk_template():
    """低风险子公司使用精简版模板（TPL-001）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    low_risk = next(o for o in result["orders"] if o["risk_level"] == "low")
    # TPL-001 精简版
    assert "精简版" in low_risk["instructions"]


def test_orders_contain_additional_programs():
    """每条指令含 additional_programs（按风险等级匹配的审计程序）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    high_risk = next(o for o in result["orders"] if o["risk_level"] == "high")
    # 高风险应匹配所有 risk_min=low/medium 的程序
    assert len(high_risk["additional_programs"]) >= 4


def test_summary_by_risk():
    """summary.by_risk 按风险等级统计指令数。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["high_risk_count"] == 1
    assert s["medium_risk_count"] == 1
    assert s["low_risk_count"] == 1


def test_generate_orders_empty_subsidiaries_returns_error():
    """无子公司数据时返回 error。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "generate_orders",
        "group_name": "X集团",
        "subsidiaries": [],
    })
    assert "error" in result


def test_render_template_fills_placeholders():
    """_render_template 辅助函数填充占位符。"""
    rendered = _render_template(
        ["{集团名称}{子公司}审计", "截止：{截止日期}"],
        {"集团名称": "测试集团", "子公司": "北京公司", "截止日期": "2025-03-15"},
    )
    assert rendered[0] == "测试集团北京公司审计"
    assert rendered[1] == "截止：2025-03-15"


# ----------------------------------------------------------------------
# 进度追踪
# ----------------------------------------------------------------------
def test_track_progress_empty_tasks():
    """无任务时进度统计为空。"""
    eng = _make_engine()
    result = eng.execute({"action": "track_progress"})
    assert result["total_tasks"] == 0
    assert result["completion_rate"] == 0.0
    assert result["details"] == []


def test_track_progress_after_generate():
    """生成指令后追踪进度，含 3 个 pending 任务。"""
    eng = _make_engine()
    eng.execute(_sample())  # 生成 3 个任务
    result = eng.execute({"action": "track_progress"})
    assert result["total_tasks"] == 3
    assert result["status_breakdown"]["pending"] == 3
    # deadline 已过（2025-03-15 < 今天），所有 pending 任务应逾期
    assert result["overdue_count"] == 3


def test_track_progress_by_task_id():
    """按 task_id 过滤追踪单个任务。"""
    eng = _make_engine()
    eng.execute(_sample())
    result = eng.execute({"action": "track_progress", "task_id": "TASK-0001"})
    assert result["total_tasks"] == 1
    assert result["details"][0]["task_id"] == "TASK-0001"


# ----------------------------------------------------------------------
# 结果汇总（注意：_preprocess 未传递 submissions，engine 返回空）
# ----------------------------------------------------------------------
def test_summarize_empty_returns_no_data():
    """无提交数据时返回"暂无提交数据"。

    注：engine 的 _preprocess 未将 input_data.submissions 透传到 prepared，
    所以 summarize_results 始终读到空列表。这是 engine 的已知限制。
    """
    eng = _make_engine()
    result = eng.execute({"action": "summarize_results"})
    assert result["summary"] == "暂无提交数据"
    assert result["total_count"] == 0


# ----------------------------------------------------------------------
# 知识库检索
# ----------------------------------------------------------------------
def test_kb_query_returns_relevant():
    """查询"函证回收率"命中相关最佳实践。"""
    eng = _make_engine()
    result = eng.execute({"action": "kb_query", "kb_query": "函证回收率低"})
    assert result["total"] >= 4
    assert len(result["results"]) >= 1
    # 最相关的应含"函证"
    assert "函证" in result["results"][0]["problem"] or "函证" in result["results"][0]["solution"]


def test_kb_query_empty_returns_all():
    """空查询返回全部知识库条目。"""
    eng = _make_engine()
    result = eng.execute({"action": "kb_query", "kb_query": ""})
    assert len(result["results"]) >= 4


def test_kb_query_no_match():
    """完全无关的查询可能返回低分或空结果。"""
    eng = _make_engine()
    result = eng.execute({"action": "kb_query", "kb_query": "zzznomatchqqq"})
    # 不抛异常即通过
    assert "results" in result


# ----------------------------------------------------------------------
# 子公司注册
# ----------------------------------------------------------------------
def test_add_subsidiary():
    """add_subsidiary 注册子公司到 model。"""
    eng = _make_engine()
    result = eng.execute({
        "action": "add_subsidiary",
        "subsidiaries": [
            {"id": "S1", "name": "子公司A", "risk_level": "medium"},
            {"id": "S2", "name": "子公司B", "risk_level": "low"},
        ],
    })
    assert result["added_count"] == 2
    assert result["total"] == 2


def test_generate_orders_after_add_subsidiary():
    """先 add_subsidiary，再 generate_orders（不传 subsidiaries）能复用注册数据。"""
    eng = _make_engine()
    eng.execute({
        "action": "add_subsidiary",
        "subsidiaries": [{"id": "S1", "name": "子公司A", "risk_level": "medium"}],
    })
    result = eng.execute({
        "action": "generate_orders",
        "group_name": "X集团",
        "deadline": "2025-06-30",
    })
    assert result["total_orders"] == 1
    assert result["orders"][0]["subsidiary_name"] == "子公司A"


# ----------------------------------------------------------------------
# 空输入 / 边界 / 元数据
# ----------------------------------------------------------------------
def test_string_input_defaults_kb_query():
    """字符串输入默认 action=kb_query。"""
    eng = _make_engine()
    result = eng.execute("函证")
    assert "results" in result


def test_unknown_action_returns_error():
    """未知 action 返回 error。"""
    eng = _make_engine()
    result = eng.execute({"action": "unknown"})
    assert "error" in result


def test_collaboration_metadata():
    """结果带 collaboration 元数据（module/family）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["collaboration"]["module"] == "CB-06"
    assert result["collaboration"]["family"] == "llm_rag"


def test_parse_date_helper():
    """_parse_date 支持 ISO / 中文日期格式。"""
    assert _parse_date("2024-01-15") == datetime(2024, 1, 15)
    assert _parse_date("2024年01月15日") == datetime(2024, 1, 15)
    # 空字符串回退为当前时间
    assert _parse_date("") is not None


def test_model_has_templates_and_programs():
    """engine 加载后 model 含模板 + 程序 + 知识库。"""
    eng = _make_engine()
    assert len(eng.model["templates"]) == 3
    assert len(eng.model["programs"]) == 5
    assert len(eng.model["knowledge_base"]) == 4
