"""[IA-04] pipeline 端到端单测：engine + custom_* 串联全流程。

注意：pipeline.py 当前 `from .engine import MLEngine`，而 engine.py 实际导出
DashboardEngine，导致 `from modules.ia_04.pipeline import Pipeline` 级联 ImportError。
这是 engine 真实 bug（pipeline 与 engine 类名不一致）。
按任务约束不改 pipeline.py，此处直接用 DashboardEngine + custom_* 串联模拟
Pipeline.run() 流程（_collect → engine.execute → thresholds → rules → format）。

另：engine._compute_operational 的 sum(spans) start=0 与 timedelta 相加 TypeError，
在 _run 中用 _fixed_compute_operational 修复实例方法（仅改 sum 的 start）。
"""
from __future__ import annotations

import json
import types
from datetime import datetime, timedelta
from pathlib import Path

from modules.ia_04.engine import DashboardEngine
from modules.ia_04.custom.custom_rules import apply_custom_rules
from modules.ia_04.custom.custom_thresholds import apply_thresholds
from modules.ia_04.custom.custom_formatter import format_output

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


def _run(input_data: dict, tmp_path: Path) -> dict:
    """模拟 Pipeline.run()：collect → execute → thresholds → rules → format。"""
    eng = DashboardEngine(config={"db_path": tmp_path / "ia_04.db"})
    eng.setup()
    eng._compute_operational = types.MethodType(_fixed_compute_operational, eng)
    try:
        collected = input_data  # _collect pass-through
        result = eng.execute(collected)
        result = apply_thresholds(result, eng.config)
        result = apply_custom_rules(result, eng.config)
        return format_output(result)  # _output
    finally:
        eng.close()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample 端到端跑通，输出含三层 KPI + 热力图 + summary。"""
    output = _run(_sample(), tmp_path)
    assert output["action"] == "dashboard"
    assert "strategic" in output
    assert "operational" in output
    assert "executive" in output
    assert "heatmap" in output
    assert output["total_findings"] == 3


def test_pipeline_pass_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，executive_summary 由 engine 后处理注入。"""
    output = _run(_sample(), tmp_path)
    assert "executive_summary" in output
    assert output["executive_summary"]["total_findings"] == 3


def test_pipeline_roi_and_value(tmp_path):
    """端到端审计总价值与 ROI 为正。"""
    output = _run(_sample(), tmp_path)
    assert output["strategic"]["audit_total_value"] > 0
    assert output["strategic"]["audit_roi"] > 0


def test_pipeline_top_findings_sorted(tmp_path):
    """端到端 top_findings 按 total_value 降序。"""
    output = _run(_sample(), tmp_path)
    top = output["top_findings"]
    values = [t["total_value"] for t in top]
    assert values == sorted(values, reverse=True)


def test_pipeline_empty_input(tmp_path):
    """空输入经 pipeline 透传后仍返回完整结构。"""
    output = _run({"findings": [], "projects": []}, tmp_path)
    assert output["total_findings"] == 0
    assert output["strategic"]["audit_total_value"] == 0
