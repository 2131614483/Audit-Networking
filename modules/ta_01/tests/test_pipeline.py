"""[TA-01] pipeline 端到端单测：Pipeline.run() 全流程跑通。

ta_01 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果（含 results + summary）。
每个测试用 tmp_path 隔离 db，结束前关闭 engine.db。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.ta_01.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    pipe = Pipeline(config={"db_path": str(tmp_path / "ta_01_pipe.db"), **overrides})
    pipe.engine.setup()
    return pipe


def _close(pipe: Pipeline) -> None:
    if pipe.engine.db is not None:
        pipe.engine.db.close()
        pipe.engine.db = None


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(tmp_path):
    """用 sample_input.json 端到端跑通，输出含 results + summary。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run(_sample())
        assert "results" in output
        assert "summary" in output
        assert len(output["results"]) == 5
        assert output["summary"]["total"] == 5
    finally:
        _close(pipe)


def test_pipeline_passes_through_custom_stages(tmp_path):
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致（含 summary）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        # pass-through 下输出仍含 issue_type_distribution（postprocess 产物）
        assert "issue_type_distribution" in output["summary"]
        assert output["summary"]["total"] == 5
        # 每个 result 含 audit_status / issues / risk_score
        for r in output["results"]:
            assert "audit_status" in r
            assert "issues" in r
            assert "risk_score" in r
    finally:
        _close(pipe)


def test_pipeline_config_propagates_to_engine(tmp_path):
    """Pipeline config 中的 db_path 透传到 engine.config。"""
    pipe = _make_pipeline(tmp_path, tolerance=0.05)
    try:
        assert pipe.engine.config.get("tolerance") == 0.05
        # db_path 透传
        assert "ta_01_pipe.db" in str(pipe.engine.db_path)
    finally:
        _close(pipe)


def test_pipeline_empty_input_handled(tmp_path):
    """空 invoices 经 Pipeline 透传后返回 total=0（不崩）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({"invoices": []})
        assert output["results"] == []
        assert output["summary"]["total"] == 0
    finally:
        _close(pipe)


def test_pipeline_custom_thresholds_passthrough(tmp_path):
    """custom_thresholds 未实现时，Pipeline 不修改 result（保持原值）。"""
    pipe = _make_pipeline(tmp_path)
    try:
        sample = _sample()
        output = pipe.run(sample)
        # thresholds pass-through：风险分未被裁剪/分级
        direct = pipe.engine.execute(sample)
        assert output["summary"]["avg_risk_score"] == direct["summary"]["avg_risk_score"]
    finally:
        _close(pipe)


def test_pipeline_duplicate_detection_through_pipeline(tmp_path):
    """重复报销检测经 Pipeline 仍生效。"""
    pipe = _make_pipeline(tmp_path)
    try:
        output = pipe.run({
            "audit_date": "2026-08-01",
            "invoices": [
                {"invoice_id": "D1", "invoice_no": "11111111",
                 "seller_name": "供应商X", "buyer_name": "B",
                 "amount_excl_tax": 1000, "tax_rate": 0.13,
                 "tax_amount": 130, "amount_incl_tax": 1130,
                 "invoice_date": "2026-07-01"},
                {"invoice_id": "D2", "invoice_no": "22222222",
                 "seller_name": "供应商X", "buyer_name": "B",
                 "amount_excl_tax": 1000, "tax_rate": 0.13,
                 "tax_amount": 130, "amount_incl_tax": 1130,
                 "invoice_date": "2026-07-15"},
            ],
        })
        d2 = next(r for r in output["results"] if r["invoice_id"] == "D2")
        assert any(i["type"] == "重复报销" for i in d2["issues"])
    finally:
        _close(pipe)
