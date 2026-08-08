"""[FI-04] pipeline 端到端单测：engine + custom_* 串联全流程。

注意：pipeline.py 当前 `from .engine import RPAEngine`，而 engine.py 实际导出
LLMEngine，导致 `from modules.fi_04.pipeline import Pipeline` 级联 ImportError。
这是 engine 真实 bug（pipeline 与 engine 类名不一致）。
按任务约束不改 pipeline.py，此处直接用 LLMEngine + custom_* 串联模拟
Pipeline.run() 流程（_collect → engine.execute → thresholds → rules → format）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.fi_04.engine import LLMEngine
from modules.fi_04.custom.custom_rules import apply_custom_rules
from modules.fi_04.custom.custom_thresholds import apply_thresholds
from modules.fi_04.custom.custom_formatter import format_output

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _run(input_data: dict, tmp_path: Path) -> dict:
    """模拟 Pipeline.run()：collect → execute → thresholds → rules → format。"""
    eng = LLMEngine(config={"db_path": tmp_path / "fi_04.db"})
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
    """用 sample 端到端跑通，输出含 summary + violations。"""
    output = _run(_sample(), tmp_path)
    assert "summary" in output
    assert "violations" in output
    assert output["summary"]["report_count"] == 2
    assert output["summary"]["total_violations"] == 5


def test_pipeline_pass_through_custom_stages(tmp_path):
    """custom_* 均为 pass-through，输出结构等同 engine.execute。"""
    output = _run(_sample(), tmp_path)
    assert output["summary"]["compliance_status"] in {"通过", "需整改", "高风险"}
    assert output["summary"]["compliance_score"] == 44.44


def test_pipeline_clean_report(tmp_path):
    """全合规报表经 pipeline 后 score=100，status=通过。"""
    output = _run({
        "reports": [{
            "report_id": "R1",
            "items": {
                "资产总计": 1000000, "负债合计": 600000, "所有者权益合计": 400000,
                "流动资产合计": 500000, "流动负债合计": 300000, "货币资金": 200000,
                "应收账款": 120000, "存货": 100000, "净利润": 200000
            },
            "receivables_prev_year": 100000, "inventory_prev_year": 90000,
            "pl_net_profit": 200000, "cf_net": 180000
        }]
    }, tmp_path)
    assert output["summary"]["compliance_score"] == 100.0
    assert output["summary"]["compliance_status"] == "通过"


def test_pipeline_empty_input(tmp_path):
    """空 reports 经 pipeline 透传后仍返回 0 违规。"""
    output = _run({"reports": []}, tmp_path)
    assert output["summary"]["report_count"] == 0
    assert output["summary"]["total_violations"] == 0


def test_pipeline_violations_carry_context(tmp_path):
    """端到端违规项携带 report_id 上下文。"""
    output = _run({
        "reports": [{
            "report_id": "RPT-E2E",
            "report_type": "资产负债表",
            "period": "2024-Q4",
            "items": {
                "资产总计": 800000, "负债合计": 500000, "所有者权益合计": 300000,
                "流动资产合计": 200000, "流动负债合计": 400000, "货币资金": 300000,
                "应收账款": 100, "存货": 100, "净利润": 100000
            },
            "receivables_prev_year": 100, "inventory_prev_year": 100,
            "pl_net_profit": 100000, "cf_net": 100000
        }]
    }, tmp_path)
    assert len(output["violations"]) > 0
    assert all(v["report_id"] == "RPT-E2E" for v in output["violations"])
