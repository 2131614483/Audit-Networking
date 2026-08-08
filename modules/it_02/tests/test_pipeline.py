"""[IT-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。

it_02 的 custom_thresholds / custom_rules 为真实实现，format_output 为 pass-through。
Pipeline 串联 engine.execute + 合规率分级 + 业务规则标记。
"""
from __future__ import annotations

import json
from pathlib import Path

from modules.it_02.pipeline import Pipeline

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
    """用 sample_input.json 端到端跑通，输出含 scan_summary / host_reports。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "scan_summary" in output
    assert "host_reports" in output
    assert output["scan_summary"]["total_hosts"] == 4


def test_pipeline_thresholds_assign_compliance_level():
    """custom_thresholds 给每台主机写 compliance_level。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    levels = {"compliant", "warning", "non_compliant"}
    for h in output["host_reports"]:
        assert h["compliance_level"] in levels
    # scan_summary 含 compliance_levels 计数
    cl = output["scan_summary"]["compliance_levels"]
    assert cl["compliant"] + cl["warning"] + cl["non_compliant"] == 4


def test_pipeline_custom_rules_generate_alerts():
    """custom_rules 生成 critical_alerts / security_flags / systemic_issues。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    # web-01 / db-01 有高严重度违规 → critical_alerts 非空
    assert len(output["critical_alerts"]) > 0
    # web-01 有 PasswordAuthentication=yes（CWE-521）→ security_flags 非空
    assert len(output["security_flags"]) > 0
    # scan_summary.alerts 含三项计数
    alerts = output["scan_summary"]["alerts"]
    assert "critical_alerts" in alerts
    assert "security_flags" in alerts
    assert "systemic_issues" in alerts


def test_pipeline_high_risk_host_downgraded_to_non_compliant():
    """有 critical_alerts 的主机被强制降级为 non_compliant。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    web01 = next(h for h in output["host_reports"] if h["hostname"] == "web-01")
    assert len(web01["critical_alerts"]) > 0
    assert web01["compliance_level"] == "non_compliant"


def test_pipeline_systemic_issues_for_multi_host_rule():
    """同一规则在多台主机失效 → systemic_issues。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    # web-01 + db-01 都有 firewall/audit 类违规；构造样本时两台 Linux 都未通过审计类
    # systemic_issues 列表里每项含 affected_hosts
    for si in output["systemic_issues"]:
        assert "rule_id" in si
        assert "affected_hosts" in si
        assert len(si["affected_hosts"]) >= 2


def test_pipeline_empty_input_handled():
    """空 list 输入经 Pipeline 后仍返回零计数结构（不崩）。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["scan_summary"]["total_hosts"] == 0
    assert output["host_reports"] == []
    assert output["critical_alerts"] == []
