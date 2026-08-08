"""[IT-03] engine 单测：代码审计 / 漏洞模式匹配 / CPG / 风险评分。

KGEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * _preprocess : 代码片段 → AST 级 CPG（函数/类/导入）
  * _infer      : 正则模式匹配 → CWE 映射 → 可利用性评估 → 风险评分
  * _postprocess: 输出审计报告（top 风险文件 + 严重发现项）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.it_03.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> KGEngine:
    eng = KGEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_vulnerability_patterns():
    """setup 后 patterns 含 8 种漏洞类型。"""
    eng = _make_engine()
    expected_types = {"SQL注入", "命令注入", "路径遍历", "硬编码密钥",
                      "不安全加密", "跨站脚本", "反序列化", "日志敏感信息"}
    assert set(eng.patterns.keys()) == expected_types


def test_severity_score_loaded():
    """severity_score 映射 高/中/低 → 10/5/2。"""
    eng = _make_engine()
    assert eng.severity_score == {"高": 10, "中": 5, "低": 2}


# ----------------------------------------------------------------------
# 语言检测
# ----------------------------------------------------------------------
def test_detect_language_python():
    eng = _make_engine()
    assert eng._detect_language("import os\ndef f():\n    pass\n") == "python"


def test_detect_language_java():
    eng = _make_engine()
    assert eng._detect_language("public class Foo {\n    System.out.println();\n}\n") == "java"


def test_detect_language_js():
    eng = _make_engine()
    assert eng._detect_language("function foo() {\n  const x = 1;\n}\n") == "js"


def test_detect_language_unknown():
    eng = _make_engine()
    assert eng._detect_language("hello world") == "unknown"


# ----------------------------------------------------------------------
# CPG 构建
# ----------------------------------------------------------------------
def test_build_cpg_extracts_functions_classes_imports():
    """CPG 提取 python 函数/类/导入。"""
    eng = _make_engine()
    code = "import os\nfrom sys import path\n\nclass Foo:\n    def bar(self):\n        pass\n\ndef baz():\n    return 1\n"
    cpg = eng._build_cpg(code, "test.py", "python")
    func_names = [f["name"] for f in cpg["functions"]]
    assert "bar" in func_names
    assert "baz" in func_names
    assert any(c["name"] == "Foo" for c in cpg["classes"])
    assert len(cpg["imports"]) == 2
    assert cpg["language"] == "python"


# ----------------------------------------------------------------------
# 模式匹配
# ----------------------------------------------------------------------
def test_match_pattern_finds_sql_injection():
    """SQL 注入模式命中字符串拼接 SQL。"""
    eng = _make_engine()
    rule = {"id": "SQLI-01", "pattern": r"execute\s*\(\s*['\"].*%s.*['\"]",
            "severity": "高", "cwe": "CWE-89", "languages": ["python"]}
    code = 'cursor.execute("SELECT * FROM u WHERE name=\'%s\'" % name)\n'
    matches = eng._match_pattern(rule, code, code.splitlines())
    assert len(matches) >= 1
    assert matches[0]["line"] == 1
    assert "execute" in matches[0]["snippet"]


def test_match_pattern_invalid_regex_returns_empty():
    """无效正则返回空列表（不抛异常）。"""
    eng = _make_engine()
    rule = {"pattern": r"[unclosed", "languages": ["python"]}
    matches = eng._match_pattern(rule, "code", ["code"])
    assert matches == []


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_postprocessed_structure():
    """execute 返回后处理结构（overall_assessment / top_risk_files / critical_findings）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "overall_assessment" in result
    assert "top_risk_files" in result
    assert "critical_findings" in result
    assert "all_findings_count" in result
    assert "generated_at" in result


def test_vuln_file_findings_cover_multiple_types():
    """vuln_app.py 触发多种漏洞类型（SQL注入/命令注入/反序列化等）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # 取 _infer 的原始 file_reports（execute 已后处理，需重新调 _infer）
    prepared = eng._preprocess(_sample())
    inferred = eng._infer(prepared)
    vuln_file = next(fr for fr in inferred["file_reports"] if fr["filename"] == "vuln_app.py")
    assert vuln_file["finding_count"] > 0
    vuln_types = {f["vulnerability_type"] for f in vuln_file["findings"]}
    # 至少命中 SQL注入 + 命令注入 + 反序列化 + 硬编码密钥
    assert {"SQL注入", "命令注入", "反序列化"} <= vuln_types


def test_safe_file_has_no_findings():
    """safe_app.py 无漏洞模式命中。"""
    eng = _make_engine()
    prepared = eng._preprocess(_sample())
    inferred = eng._infer(prepared)
    safe_file = next(fr for fr in inferred["file_reports"] if fr["filename"] == "safe_app.py")
    assert safe_file["finding_count"] == 0
    assert safe_file["risk_score"] == 0


def test_finding_structure_complete():
    """每个 finding 含 rule_id / severity / cwe / line_number / remediation / exploitability。"""
    eng = _make_engine()
    prepared = eng._preprocess(_sample())
    inferred = eng._infer(prepared)
    for f in inferred["findings"]:
        assert "rule_id" in f
        assert "severity" in f
        assert "cwe" in f
        assert "line_number" in f
        assert "remediation" in f
        assert "exploitability" in f
        assert f["severity"] in {"高", "中", "低"}
        assert f["exploitability"] in {"高", "中", "低"}


def test_exploitability_mapping():
    """_exploitability 按严重度 + 漏洞类型映射。"""
    eng = _make_engine()
    # 高严重度 + SQL注入 → 高
    assert eng._exploitability("SQL注入", "高") == "高"
    # 高严重度 + 硬编码密钥 → 中
    assert eng._exploitability("硬编码密钥", "高") == "中"
    # 中严重度 → 中
    assert eng._exploitability("路径遍历", "中") == "中"
    # 低严重度 → 低
    assert eng._exploitability("日志敏感信息", "低") == "低"


def test_risk_level_thresholds():
    """_risk_level 按 norm=risk_score/(n_lines/100) 分级。"""
    eng = _make_engine()
    # norm = 50/(100/100)=50 > 5 → 严重风险
    assert eng._risk_level(50, 100) == "严重风险"
    # norm = 3/(100/100)=3 > 2 → 高风险
    assert eng._risk_level(3, 100) == "高风险"
    # norm = 1/(100/100)=1 > 0.5 → 中风险
    assert eng._risk_level(1, 100) == "中风险"
    # norm = 0.1 → 低风险
    assert eng._risk_level(0.1, 100) == "低风险"


def test_overall_assessment_aggregates():
    """overall_assessment 聚合严重度分布 + CWE 分布 + 类型分布。"""
    eng = _make_engine()
    prepared = eng._preprocess(_sample())
    inferred = eng._infer(prepared)
    oa = inferred["overall_assessment"]
    assert oa["total_files"] == 2
    assert oa["files_with_findings"] == 1
    assert oa["total_findings"] > 0
    assert sum(oa["severity_distribution"].values()) == oa["total_findings"]
    assert "top_vulnerability_types" in oa
    assert "top_cwes" in oa
    assert oa["overall_risk_level"] in {"高风险", "中风险", "低风险"}


def test_top_risk_files_sorted_desc():
    """top_risk_files 按风险分降序，最多 10 条。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    top = result["top_risk_files"]
    assert len(top) <= 10
    scores = [f["risk_score"] for f in top]
    assert scores == sorted(scores, reverse=True)
    # vuln_app.py 应排首位
    assert top[0]["filename"] == "vuln_app.py"


def test_critical_findings_are_high_severity():
    """critical_findings 仅含 severity=高 的发现项。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for f in result["critical_findings"]:
        assert f["severity"] == "高"
    assert len(result["critical_findings"]) > 0


# ----------------------------------------------------------------------
# 输入形态 / 边界
# ----------------------------------------------------------------------
def test_string_input_accepted():
    """直接传字符串输入（inline 代码）。"""
    eng = _make_engine()
    result = eng.execute("import os\nos.system('ls')\n")
    assert "overall_assessment" in result


def test_dict_input_wrapped_as_list():
    """dict 输入被包装为单元素 list。"""
    eng = _make_engine()
    prepared = eng._preprocess({"code": "os.system('x')\n", "language": "python"})
    assert len(prepared) == 1
    assert prepared[0]["language"] == "python"


def test_empty_input_handled():
    """空 list 输入返回零计数结构（不崩）。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["overall_assessment"]["total_files"] == 0
    assert result["all_findings_count"] == 0
    assert result["critical_findings"] == []


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 时 patterns 为空 → 无漏洞命中。"""
    eng = KGEngine()
    result = eng.execute([{"code": "os.system('x')\n", "language": "python"}])
    assert result["all_findings_count"] == 0
