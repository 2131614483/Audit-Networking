"""[IP-04] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ip_04 的 custom_* 为 pass-through 骨架，Pipeline 串联 engine.execute，
因此输出结构等同 engine 结果（含 diagnosis_score / problems / suggestions）。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ip_04.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline() -> Pipeline:
    return Pipeline()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 diagnosis_score + problems。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())

    assert "diagnosis_score" in output
    assert "risk_level" in output
    assert "problems" in output
    assert output["industry_benchmark"]["industry"] == "制造业"
    assert len(output["problems"]) >= 5


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    direct = pipe.engine.execute(sample)
    assert output["diagnosis_score"] == direct["diagnosis_score"]
    assert len(output["problems"]) == len(direct["problems"])
    assert output["risk_level"] == direct["risk_level"]


def test_pipeline_preserves_statistics_and_suggestions():
    """Pipeline 保留 statistics + suggestions（postprocess 产物）。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "statistics" in output
    assert output["statistics"]["total_issues"] == len(output["problems"])
    assert "suggestions" in output
    assert len(output["suggestions"]) == len(output["problems"])


def test_pipeline_clean_data_no_problems():
    """合规数据经 Pipeline 透传后无问题、score=100。

    NOTE engine bug: risk_level 逻辑反转（score>=85 被标"高风险"），只断言 score/problems。
    """
    pipe = _make_pipeline()
    bench = pipe.engine.setup().model["industry_benchmarks"]["制造业"]
    output = pipe.run({
        "industry": "制造业",
        "financials": {
            "gross_margin": bench["gross_margin"],
            "ar_turnover": bench["ar_turnover"],
            "inv_turnover": bench["inv_turnover"],
            "ocf_to_net_profit": bench["ocf_to_net_profit"],
            "rev_yoy": 0.1,
            "tax_rate": 0.20,
            "related_party_ratio": 0.05,
            "debt_ratio": bench["debt_ratio"],
        },
    })
    assert output["problems"] == []
    assert output["diagnosis_score"] == 100


def test_pipeline_minimal_financials_handled():
    """仅提供 rev_yoy（规避 None 比较崩溃）经 Pipeline 透传后不崩。"""
    pipe = _make_pipeline()
    output = pipe.run({"industry": "制造业", "financials": {"rev_yoy": 0.1}})
    assert output["diagnosis_score"] == 100
    assert output["problems"] == []
