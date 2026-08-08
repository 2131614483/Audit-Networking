"""[IA-03] pipeline 端到端单测：engine + custom_* 串联全流程。

注意：pipeline.py 当前 `from .engine import MLEngine`，而 engine.py 实际导出
ResourceEngine，导致 `from modules.ia_03.pipeline import Pipeline` 级联 ImportError。
这是 engine 真实 bug（pipeline 与 engine 类名不一致）。
按任务约束不改 pipeline.py，此处直接用 ResourceEngine + custom_* 串联模拟
Pipeline.run() 流程（_collect → engine.execute → thresholds → rules → format）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ia_03.engine import ResourceEngine
from modules.ia_03.custom.custom_rules import apply_custom_rules
from modules.ia_03.custom.custom_thresholds import apply_thresholds
from modules.ia_03.custom.custom_formatter import format_output

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _run(input_data: dict, tmp_path: Path) -> dict:
    """模拟 Pipeline.run()：collect → execute → thresholds → rules → format。"""
    eng = ResourceEngine(config={"db_path": tmp_path / "ia_03.db"})
    eng.setup()
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
    """用 sample 端到端跑通，输出含 plans + best_plan + summary。"""
    output = _run(_sample(), tmp_path)
    assert output["action"] == "allocate"
    assert len(output["plans"]) == 4
    assert output["best_plan"] is not None
    assert "summary" in output


def test_pipeline_pass_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，summary 与 engine 输出一致。"""
    output = _run(_sample(), tmp_path)
    assert output["summary"]["total_plans"] == 4
    assert output["summary"]["best_score"] == output["best_plan"]["score"]


def test_pipeline_assignments_match_required(tmp_path):
    """端到端分配人数 = required_count。"""
    output = _run(_sample(), tmp_path)
    best = output["best_plan"]
    for proj in _sample()["projects"]:
        pid = proj["project_id"]
        assert len(best["assignments"][pid]) == proj["required_count"]


def test_pipeline_empty_input(tmp_path):
    """空审计师经 pipeline 透传后仍返回空 plans。"""
    output = _run({"auditors": [], "projects": []}, tmp_path)
    assert output["plans"] == []
    assert output["best_plan"] is None


def test_pipeline_total_counts(tmp_path):
    """端到端统计 total_projects / total_auditors。"""
    output = _run(_sample(), tmp_path)
    assert output["total_projects"] == 2
    assert output["total_auditors"] == 4
