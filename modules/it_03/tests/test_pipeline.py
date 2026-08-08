"""[IT-03] pipeline 端到端单测：Pipeline.run() 全流程跑通。

it_03 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.it_03.pipeline import Pipeline

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
    """用 sample_input.json 端到端跑通，输出含 overall_assessment + top_risk_files。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "overall_assessment" in output
    assert "top_risk_files" in output
    assert output["overall_assessment"]["total_files"] == 2
    assert output["all_findings_count"] > 0


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["all_findings_count"] == direct["all_findings_count"]
    assert output["overall_assessment"]["total_findings"] == direct["overall_assessment"]["total_findings"]
    assert len(output["top_risk_files"]) == len(direct["top_risk_files"])


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = Pipeline(config={"custom_key": "value"})
    pipe.engine.setup()
    assert pipe.engine.config.get("custom_key") == "value"


def test_pipeline_string_input_accepted():
    """Pipeline 接受字符串输入（inline 代码，需含 def+import 才识别为 python）。"""
    pipe = _make_pipeline()
    # _detect_language 要求同时含 "def " 和 "import " 才识别为 python
    # CMD-01 正则要求 os.system( 后跟变量名（非引号）
    output = pipe.run("import os\ndef f(cmd):\n    os.system(cmd)\n")
    assert output["overall_assessment"]["total_files"] == 1
    assert output["all_findings_count"] > 0


def test_pipeline_empty_input_handled():
    """空 list 输入经 Pipeline 后仍返回零计数结构（不崩）。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["overall_assessment"]["total_files"] == 0
    assert output["all_findings_count"] == 0
    assert output["critical_findings"] == []
