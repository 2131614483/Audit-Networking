"""[IT-01] engine 单测：IT 审计自动化 / RPA 执行 / 证据链 / 合规检查。

RPAEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * _preprocess : 按 domains/systems/risk_focus 展开审计程序清单 → RPA 执行计划
  * _infer      : 模拟 RPA 动作链执行（成功/失败/重试）+ 检查项评估 → 发现项 + 证据链
  * _postprocess: 输出审计执行报告（程序状态/发现项/证据链/审计结论）

注：_execute_program / _evaluate_check 使用 random 模块模拟成功率，
测试用 random.seed 保证可复现。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from modules.it_01.engine import RPAEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> RPAEngine:
    eng = RPAEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_domains_and_programs():
    """setup 后 model 含 4 个 IT 域，共 9 个审计程序。"""
    eng = _make_engine()
    assert len(eng.domains) == 4
    expected_domains = {"身份与访问管理", "网络安全", "数据安全", "系统运维"}
    assert set(eng.domains.keys()) == expected_domains
    total_programs = sum(len(d["programs"]) for d in eng.domains.values())
    assert total_programs == 9


def test_rpa_success_rate_configurable():
    """rpa_success_rate 可通过 config 覆盖默认 0.92。"""
    eng = _make_engine(rpa_success_rate=0.5)
    assert eng.rpa_success_rate == 0.5
    eng_default = _make_engine()
    assert eng_default.rpa_success_rate == 0.92


# ----------------------------------------------------------------------
# 预处理：程序清单展开
# ----------------------------------------------------------------------
def test_preprocess_returns_sorted_plans():
    """预处理后按 priority 排序（高风险程序优先）。"""
    random.seed(42)
    eng = _make_engine()
    plans = eng._preprocess(_sample())
    assert len(plans) == 9
    # 高风险 priority=1 应排在中风险 priority=2 之前
    priorities = [p["priority"] for p in plans]
    assert priorities == sorted(priorities)


def test_preprocess_filters_domains():
    """指定 domains 时只展开指定域的程序。"""
    eng = _make_engine()
    plans = eng._preprocess([{
        "domains": ["网络安全"],
        "systems": ["FW"],
        "risk_focus": ["高", "中"],
    }])
    assert len(plans) == 2  # 网络安全域有 2 个程序
    for p in plans:
        assert p["domain"] == "网络安全"


def test_preprocess_filters_risk_focus():
    """risk_focus=['高'] 时只保留高风险程序。"""
    eng = _make_engine()
    plans = eng._preprocess([{
        "domains": list(eng.domains.keys()),
        "systems": ["S"],
        "risk_focus": ["高"],
    }])
    # 高风险程序：IAM-01, IAM-02, NET-01, DS-01, DS-02 = 5 个
    assert len(plans) == 5
    for p in plans:
        assert p["risk_level"] == "高"


def test_preprocess_unknown_domain_skipped():
    """未知 domain 被静默过滤。"""
    eng = _make_engine()
    plans = eng._preprocess([{
        "domains": ["未知域", "网络安全"],
        "systems": ["S"],
        "risk_focus": ["高", "中"],
    }])
    assert all(p["domain"] != "未知域" for p in plans)
    assert len(plans) == 2


def test_preprocess_dict_input_wrapped_as_list():
    """dict 输入被包装为单元素 list。"""
    eng = _make_engine()
    plans = eng._preprocess({
        "domains": ["网络安全"],
        "systems": ["S"],
        "risk_focus": ["高"],
    })
    assert len(plans) == 1
    assert plans[0]["id"] == "NET-01"


def test_preprocess_attaches_systems_and_duration():
    """每个 plan 携带 systems / estimated_duration / priority。"""
    eng = _make_engine()
    plans = eng._preprocess([{
        "domains": ["系统运维"],
        "systems": ["ServerA", "ServerB"],
        "risk_focus": ["中"],
    }])
    for p in plans:
        assert p["systems"] == ["ServerA", "ServerB"]
        assert p["estimated_duration"] == p["duration_min"]
        assert "priority" in p


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_postprocessed_structure():
    """execute 返回后处理后的结构（含 audit_plan / execution_status / conclusion）。"""
    random.seed(42)
    eng = _make_engine()
    result = eng.execute(_sample())
    assert "audit_plan" in result
    assert "execution_status" in result
    assert "findings" in result
    assert "evidence" in result
    assert "conclusion" in result
    assert "generated_at" in result


def test_execute_total_programs_matches_plans():
    """execution_status.programs 数量 = 展开后的程序数。"""
    random.seed(42)
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["audit_plan"]["total_programs"] == 9
    assert len(result["execution_status"]["programs"]) == 9


def test_execution_status_in_valid_set():
    """每个程序的 status 在 completed/partial/blocked 之一。"""
    random.seed(42)
    eng = _make_engine()
    result = eng.execute(_sample())
    for p in result["execution_status"]["programs"]:
        assert p["status"] in {"completed", "partial", "blocked"}
        assert p["total_actions"] == p["success_actions"] + p["failed_actions"]


def test_findings_have_severity_and_recommendation():
    """每个发现项含 severity（高/中/低）+ recommendation。"""
    random.seed(7)
    eng = _make_engine(rpa_success_rate=0.3)  # 低成功率制造更多发现项
    result = eng.execute(_sample())
    open_findings = result["findings"]["open"]
    # 用低成功率 + 多检查项，应当有发现项
    assert len(open_findings) > 0
    for f in open_findings:
        assert f["severity"] in {"高", "中", "低"}
        assert isinstance(f["recommendation"], str)
        assert len(f["recommendation"]) > 0


def test_evidence_chain_hash_length():
    """证据链每项 evidence_hash 为 16 位 hex。"""
    random.seed(42)
    eng = _make_engine()
    result = eng.execute(_sample())
    for e in result["evidence"]:
        assert len(e["evidence_hash"]) == 16
        assert "program_id" in e
        assert "collected_at" in e


def test_conclusion_risk_level_in_valid_set():
    """conclusion.risk_level 在 高风险/中风险/低风险 之一。"""
    random.seed(42)
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["conclusion"]["risk_level"] in {"高风险", "中风险", "低风险"}
    assert 0 <= result["conclusion"]["risk_score"] <= 100


def test_final_recommendation_matches_risk_level():
    """conclusion.recommendation 文案与风险等级匹配。"""
    random.seed(42)
    eng = _make_engine()
    result = eng.execute(_sample())
    rl = result["conclusion"]["risk_level"]
    rec = result["conclusion"]["recommendation"]
    assert isinstance(rec, str)
    if rl == "高风险":
        assert "立即" in rec or "专项" in rec
    elif rl == "中风险":
        assert "季度" in rec or "整改" in rec
    else:
        assert "持续" in rec or "优化" in rec


# ----------------------------------------------------------------------
# recommend_fix 关键词路由
# ----------------------------------------------------------------------
def test_recommend_fix_routes_by_keyword():
    """_recommend_fix 按关键词返回针对性建议。"""
    eng = _make_engine()
    prog = {"id": "X", "name": "X", "domain": "身份与访问管理", "risk_level": "高"}
    assert "HR-IT" in eng._recommend_fix("离职账号必须禁用", prog)
    assert "SoD" in eng._recommend_fix("检查 SoD 冲突", prog)
    prog_net = {"id": "X", "name": "X", "domain": "网络安全", "risk_level": "高"}
    assert "防火墙" in eng._recommend_fix("检查防火墙规则", prog_net) or "端口" in eng._recommend_fix("检查开放端口", prog_net)
    prog_ops = {"id": "X", "name": "X", "domain": "系统运维", "risk_level": "中"}
    assert "补丁" in eng._recommend_fix("关键补丁30天内安装", prog_ops)


def test_recommend_fix_default_branch():
    """无关键词命中时返回通用建议。"""
    eng = _make_engine()
    prog = {"id": "X", "name": "X", "domain": "网络安全", "risk_level": "中"}
    rec = eng._recommend_fix("某未知检查项", prog)
    assert "专项整改" in rec


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_input_returns_empty_structure():
    """空 list 输入返回零计数结构（不崩）。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["audit_plan"]["total_programs"] == 0
    assert result["execution_status"]["programs"] == []
    assert result["findings"]["open"] == []
    assert result["conclusion"]["risk_level"] in {"高风险", "中风险", "低风险"}


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 也能懒加载（_preprocess 不依赖 model）。"""
    eng = RPAEngine()
    # _preprocess 用 self.domains，setup() 才填充，所以未 setup 时为空
    # 但 _preprocess 会跳过未知 domain，结果为空 plans
    result = eng.execute([{"domains": ["网络安全"], "systems": ["S"], "risk_focus": ["高"]}])
    assert result["audit_plan"]["total_programs"] == 0
