"""[IT-01] pipeline 端到端单测：Pipeline.run() 全流程跑通。

it_01 的 custom_thresholds / custom_rules / format_output 为真实实现
（非 pass-through），Pipeline 串联 engine.execute + 阈值分级 + 规则标记 + 格式化。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from modules.it_01.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    pipe = Pipeline(config=overrides)
    pipe.engine.setup()
    return pipe


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 module=IT-01 标记。"""
    random.seed(42)
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert output["status"] == "ok"
    assert output["module"] == "IT-01"
    assert output["audit_plan"]["total_programs"] == 9
    assert len(output["execution_summary"]["domains_covered"]) == 4


def test_pipeline_format_output_structure():
    """format_output 后输出含 execution_summary / findings_summary / recommendations / conclusion。"""
    random.seed(42)
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "execution_summary" in output
    assert "findings" in output
    assert "findings_summary" in output
    assert "evidence_chain" in output
    assert "recommendations" in output
    assert "conclusion" in output


def test_pipeline_thresholds_propagate_to_conclusion():
    """custom_thresholds 把 audit_status / severity_counts / thresholds 写入 conclusion。"""
    random.seed(42)
    pipe = _make_pipeline(threshold={"critical_high_count": 5, "high_count": 2, "medium_count": 4})
    output = pipe.run(_sample())
    conclusion = output["conclusion"]
    assert conclusion["audit_status"] in {"critical", "high", "medium", "low"}
    assert "thresholds" in conclusion
    assert conclusion["thresholds"]["critical_high_count"] == 5
    assert "severity_counts" in conclusion


def test_pipeline_custom_rules_marks_special_findings():
    """SoD / 闲置账号 / 特权账号 规则触发对应标记（若产生相关发现项）。"""
    random.seed(1)
    pipe = _make_pipeline(rpa_success_rate=0.1)  # 低成功率制造更多发现项
    output = pipe.run(_sample())
    # 检查规则触发统计写入 conclusion.rule_adjustments
    ra = output["conclusion"].get("rule_adjustments", {})
    # 至少有这几个统计字段（即使计数为 0）
    assert "critical_findings" in ra
    assert "auto_disable_recommended" in ra
    assert "mfa_required" in ra
    assert "require_immediate_action" in ra


def test_pipeline_finding_details_carry_priority():
    """Pipeline 输出的 finding 明细带 priority（1-5）。"""
    random.seed(3)
    pipe = _make_pipeline(rpa_success_rate=0.2)
    output = pipe.run(_sample())
    for f in output["findings"]:
        assert "priority" in f
        assert 1 <= f["priority"] <= 5


def test_pipeline_empty_input_handled():
    """空 list 输入经 Pipeline 后仍返回零计数结构（不崩）。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["status"] == "ok"
    assert output["audit_plan"]["total_programs"] == 0
    assert output["findings_summary"]["total"] == 0
