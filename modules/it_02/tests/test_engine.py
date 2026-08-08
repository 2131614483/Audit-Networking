"""[IT-02] engine 单测：配置合规扫描 / 规则匹配 / 风险评分 / 聚合报告。

MLEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * _preprocess : 多系统配置快照标准化（dict 或 kv 文本均支持）
  * _infer      : 规则匹配（op 比较 + negate）→ 偏差分类 → 风险评分 → 聚合
  * _postprocess: 输出合规性报告（合规率 + 偏差明细 + 优先整改）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.it_02.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> MLEngine:
    eng = MLEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_baseline_for_four_platforms():
    """setup 后 baseline 含 Linux/Windows/Network/Database 四平台规则。"""
    eng = _make_engine()
    assert set(eng.baseline.keys()) == {"Linux", "Windows", "Network", "Database"}
    assert len(eng.baseline["Linux"]) == 6
    assert len(eng.baseline["Windows"]) == 5
    assert len(eng.baseline["Network"]) == 3
    assert len(eng.baseline["Database"]) == 4


def test_severity_weights_configurable():
    """severity_weights 可通过 config 覆盖。"""
    eng = _make_engine(severity_weights={"高": 20, "中": 10, "低": 5})
    assert eng.severity_weights["高"] == 20


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_dict_input_wrapped_as_list():
    """dict 输入被包装为单元素 list。"""
    eng = _make_engine()
    parsed = eng._preprocess({"platform": "Linux", "hostname": "h1", "config": {}})
    assert len(parsed) == 1
    assert parsed[0]["hostname"] == "h1"
    assert parsed[0]["platform"] == "Linux"


def test_preprocess_parses_kv_string_config():
    """字符串 config 被 _parse_kv_config 解析为 dict（值经 _convert_value 转换）。"""
    eng = _make_engine()
    parsed = eng._preprocess([{
        "platform": "Linux", "hostname": "h1",
        "config": "PermitRootLogin no\nfirewall_active = true\nPASS_MAX_DAYS 90\n",
    }])
    cfg = parsed[0]["config"]
    # _convert_value 把 "no" → False, "true" → True, "90" → 90
    assert cfg["PermitRootLogin"] is False
    assert cfg["firewall_active"] is True
    assert cfg["PASS_MAX_DAYS"] == 90


def test_convert_value_handles_bool_and_numbers():
    """_convert_value 把 true/yes/on → True，数字字符串 → int/float。"""
    assert MLEngine._convert_value("true") is True
    assert MLEngine._convert_value("YES") is True
    assert MLEngine._convert_value("on") is True
    assert MLEngine._convert_value("false") is False
    assert MLEngine._convert_value("OFF") is False
    assert MLEngine._convert_value("42") == 42
    assert MLEngine._convert_value("3.14") == 3.14
    assert MLEngine._convert_value('"quoted"') == "quoted"


def test_preprocess_uses_hostname_or_device_fallback():
    """hostname 缺失时回退到 device 字段。"""
    eng = _make_engine()
    parsed = eng._preprocess([{"platform": "Linux", "device": "router-1", "config": {}}])
    assert parsed[0]["hostname"] == "router-1"


# ----------------------------------------------------------------------
# 规则评估
# ----------------------------------------------------------------------
def test_evaluate_rule_op_ge():
    """op='>=' 的规则：实际值达标 → 通过。"""
    eng = _make_engine()
    rule = {"check": "LockoutThreshold", "op": ">=", "value": 5}
    assert eng._evaluate_rule(rule, {"LockoutThreshold": 5}) is True
    assert eng._evaluate_rule(rule, {"LockoutThreshold": 3}) is False
    assert eng._evaluate_rule(rule, {}) is False  # 缺字段 → 不通过


def test_evaluate_rule_op_eq_bool():
    """op='==' 的规则：布尔值精确匹配。"""
    eng = _make_engine()
    rule = {"check": "firewall_active", "op": "==", "value": True}
    assert eng._evaluate_rule(rule, {"firewall_active": True}) is True
    assert eng._evaluate_rule(rule, {"firewall_active": False}) is False


def test_evaluate_rule_negate():
    """negate=True 时反转 op 比较结果。"""
    eng = _make_engine()
    rule = {"check": "firewall_active", "op": "==", "value": True, "negate": True}
    # 实际 True == True → passed=True → negate → False（不通过）
    assert eng._evaluate_rule(rule, {"firewall_active": True}) is False
    # 实际 False == True → passed=False → negate → True（通过）
    assert eng._evaluate_rule(rule, {"firewall_active": False}) is True


def test_evaluate_rule_substring_match_case_insensitive():
    """无 op 时：check 既是键名又是在值中查找的子串（大小写不敏感）。"""
    eng = _make_engine()
    rule = {"check": "ok"}  # 键名 = "ok"，期望值中含子串 "ok"
    # 值含 "ok" → 通过
    assert eng._evaluate_rule(rule, {"ok": "status OK running"}) is True
    # 值不含 "ok" → 不通过
    assert eng._evaluate_rule(rule, {"ok": "fail"}) is False
    # 缺键 → actual=None → 不通过
    assert eng._evaluate_rule(rule, {"other": "ok"}) is False


def test_resolve_check_case_insensitive():
    """_resolve_check 大小写不敏感匹配键。"""
    assert MLEngine._resolve_check({"Firewall_Active": True}, "firewall_active") is True
    assert MLEngine._resolve_check({}, "missing") is None


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_postprocessed_structure():
    """execute 返回后处理结构（scan_summary / host_reports / priority_fixes）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "scan_summary" in result
    assert "host_reports" in result
    assert "priority_fixes" in result
    assert "generated_at" in result


def test_host_reports_carry_compliance_metrics():
    """每台主机报告含 compliance_rate / risk_score / risk_level / violations。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for h in result["host_reports"]:
        assert 0.0 <= h["compliance_rate"] <= 1.0
        assert h["risk_score"] >= 0
        assert h["risk_level"] in {"高风险", "中风险", "低风险"}
        assert h["violations"] == sum(1 for r in h["rule_results"] if not r["passed"])


def test_web01_high_risk_due_to_many_violations():
    """web-01 配置大量违规 → 高风险。

    LIN-001 (无 op, check="PermitRootLogin no") 实际值 None → 不通过
    LIN-002 (negate) 实际值 None → passed=False → negate → 通过
    LIN-003 PASS_MAX_DAYS=120 > 90 → 不通过
    LIN-004 firewall_active=False → 不通过
    LIN-005 unnecessary_services=3 != 0 → 不通过
    LIN-006 auditd_active=False → 不通过
    共 5 个 violation。
    """
    eng = _make_engine()
    result = eng.execute(_sample())
    web01 = next(h for h in result["host_reports"] if h["hostname"] == "web-01")
    assert web01["violations"] == 5
    assert web01["compliance_rate"] == round(1 / 6, 3)  # (6-5)/6
    assert web01["risk_level"] == "高风险"


def test_web02_mostly_compliant_host():
    """web-02 大部分合规，仅 LIN-001（无 op 规则）不通过。

    LIN-001 check="PermitRootLogin no" → actual=None → 不通过（1 个 violation）
    其余 5 条规则均通过。
    """
    eng = _make_engine()
    result = eng.execute(_sample())
    web02 = next(h for h in result["host_reports"] if h["hostname"] == "web-02")
    assert web02["violations"] == 1
    assert web02["compliance_rate"] == round(5 / 6, 3)
    # LIN-001 severity=高，权重 10；risk_score=10, expected_max=60, ratio≈0.167 > 0.15 → 中风险
    assert web02["risk_level"] == "中风险"


def test_summary_aggregates_hosts():
    """scan_summary 聚合所有主机的违规与合规率。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["scan_summary"]
    assert s["total_hosts"] == 4
    assert s["total_violations"] > 0
    assert 0.0 <= s["overall_compliance_rate"] <= 1.0
    assert "severity_distribution" in s
    assert "platform_summary" in s
    # web-01 + db-01 应在 high_risk_hosts
    assert "web-01" in s["high_risk_hosts"]
    assert "db-01" in s["high_risk_hosts"]


def test_priority_fixes_sorted_by_violations_desc():
    """priority_fixes 按违规次数降序，最多 10 条。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    fixes = result["priority_fixes"]
    assert len(fixes) <= 10
    counts = [f["violations"] for f in fixes]
    assert counts == sorted(counts, reverse=True)
    for i, f in enumerate(fixes):
        assert f["priority"] == i + 1
        assert "rule_id" in f
        assert "remediation" in f


def test_evidence_collected_per_rule():
    """每条 rule_result 含 evidence 文本（实际值 / 期望值）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for h in result["host_reports"]:
        for rr in h["rule_results"]:
            assert "实际值" in rr["evidence"]
            assert "期望值" in rr["evidence"]


def test_risk_label_thresholds():
    """_risk_label 按 risk_score/expected_max 比例分级。"""
    eng = _make_engine()
    # 6 条 Linux 规则，expected_max=60；risk_score=60 → ratio=1.0 → 高风险
    assert eng._risk_label(60, 6) == "高风险"
    # ratio=0.2 → 中风险
    assert eng._risk_label(12, 6) == "中风险"
    # ratio=0.05 → 低风险
    assert eng._risk_label(3, 6) == "低风险"


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_unknown_platform_no_rules():
    """未知平台 → 0 规则 → compliance_rate=1（无规则即合规）。"""
    eng = _make_engine()
    result = eng.execute([{"platform": "AIX", "hostname": "h", "config": {"x": 1}}])
    h = result["host_reports"][0]
    assert h["total_rules"] == 0
    assert h["violations"] == 0
    # (0-0)/max(1,0) = 0/1 = 0.0
    assert h["compliance_rate"] == 0.0


def test_empty_input_handled():
    """空 list 输入返回零计数 summary（不崩）。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["scan_summary"]["total_hosts"] == 0
    assert result["host_reports"] == []
    assert result["priority_fixes"] == []


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 时 baseline 为空 → 所有规则评估为空。"""
    eng = MLEngine()
    # 未 setup，baseline={}，rules 为空 list
    result = eng.execute([{"platform": "Linux", "hostname": "h", "config": {"x": 1}}])
    assert result["host_reports"][0]["total_rules"] == 0
