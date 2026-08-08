"""[CB-04] pipeline 端到端单测：Pipeline.run() 全流程跑通。

cb_04 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.cb_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_conversion():
    """用 sample_input.json 端到端跑 IFRS→US_GAAP 转换。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert output["from_standard"] == "IFRS"
    assert output["to_standard"] == "US_GAAP"
    assert len(output["matched_differences"]) >= 1
    assert output["audit_plan"]["module"] == "CB-04"
    assert output["audit_plan"]["family"] == "llm_rag"


def test_pipeline_generates_adjustments():
    """Pipeline 输出含调节分录列表。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert len(output["adjustments"]) >= 1
    for adj in output["adjustments"]:
        assert "debit_accounts" in adj
        assert "credit_accounts" in adj


def test_pipeline_string_input():
    """Pipeline 接受字符串输入（当作 notes）。"""
    pipe = _make_pipeline()
    output = pipe.run("本公司采用 IFRS 15 收入确认五步法")
    assert output["from_standard"] == "IFRS"
    assert "audit_plan" in output


def test_pipeline_empty_policies_handled():
    """空政策列表经 Pipeline 透传后不崩。"""
    pipe = _make_pipeline()
    output = pipe.run({
        "from_standard": "IFRS",
        "to_standard": "US_GAAP",
        "accounting_policies": [],
    })
    assert "matched_differences" in output
    assert "audit_plan" in output


def test_pipeline_passes_through_custom_stages():
    """custom 阶段为 pass-through，Pipeline 输出与 engine.execute 结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    pipe.engine.setup()
    direct = pipe.engine.execute(sample)
    assert output["summary"]["total_differences"] == direct["summary"]["total_differences"]
    assert len(output["matched_differences"]) == len(direct["matched_differences"])
