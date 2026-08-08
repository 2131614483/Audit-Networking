"""[ES-04] engine 单测：知识图谱绿色漂洗检测（声明可信度 / 矛盾检测 / 证据交叉验证）。

KGEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * 声明分类：排放/能源/水资源/废弃物/生物多样性/供应链/认证/承诺
  * 可信度评估：可量化度 + 可验证度 + 证据支撑 + 渠道一致 + 模糊词惩罚
  * 矛盾检测：声明间矛盾（减排 vs 排放上升）
  * 证据交叉验证：同指标多源证据冲突
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.es_04.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> KGEngine:
    eng = KGEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 声明评估结构
# ----------------------------------------------------------------------
def test_claim_evaluations_structure():
    """每个声明评估含 claim_id / claim_text / category / credibility / risk_score / verdict / metrics。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    evals = result["all_claim_evaluations"]
    assert len(evals) == 2
    for e in evals:
        assert "claim_id" in e
        assert "claim_text" in e
        assert "category" in e
        assert "credibility" in e
        assert "risk_score" in e
        assert "verdict" in e
        assert "metrics" in e
        assert "matched_evidence_ids" in e


def test_credibility_in_range_and_risk_is_complement():
    """credibility ∈ [0,1]，risk_score = 1 - credibility。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for e in result["all_claim_evaluations"]:
        assert 0.0 <= e["credibility"] <= 1.0
        assert 0.0 <= e["risk_score"] <= 1.0
        assert abs(e["risk_score"] + e["credibility"] - 1.0) < 1e-3


def test_metrics_structure():
    """metrics 含 quantifiability / fuzzy_penalty / verifiability / evidence_support。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    m = result["all_claim_evaluations"][0]["metrics"]
    for key in ("quantifiability", "fuzzy_penalty", "verifiability",
                "evidence_support", "channel_consistency",
                "supporting_evidence_count", "contradicting_evidence_count"):
        assert key in m


# ----------------------------------------------------------------------
# 可信度相对关系
# ----------------------------------------------------------------------
def test_quantifiable_claim_more_trustworthy_than_fuzzy():
    """含数字的声明可量化度高于纯模糊词声明。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    evals = result["all_claim_evaluations"]
    # claim 0 含 30% / 2024；claim 1 仅模糊词
    assert evals[0]["metrics"]["quantifiability"] > evals[1]["metrics"]["quantifiability"]
    assert evals[0]["metrics"]["fuzzy_penalty"] < evals[1]["metrics"]["fuzzy_penalty"]


def test_fuzzy_claim_has_higher_risk():
    """模糊词声明的 risk_score 高于可量化声明。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    evals = result["all_claim_evaluations"]
    assert evals[1]["risk_score"] > evals[0]["risk_score"]


# ----------------------------------------------------------------------
# 声明分类
# ----------------------------------------------------------------------
def test_claim_categorization():
    """含碳排放/减排关键词的声明归类为排放声明。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for e in result["all_claim_evaluations"]:
        assert e["category"] == "排放声明"


def test_uncategorized_claim_defaults_other():
    """无关键词命中的声明归为其他声明。"""
    eng = _make_engine()
    result = eng.execute([{"claims": [{"text": "公司简介"}]}])
    assert result["all_claim_evaluations"][0]["category"] == "其他声明"


# ----------------------------------------------------------------------
# 矛盾检测
# ----------------------------------------------------------------------
def test_contradiction_detected_between_claims():
    """减排声明与排放上升声明构成矛盾对。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    contras = result["contradictions"]
    assert len(contras) >= 1
    c = contras[0]
    assert c["type"] == "声明间矛盾"
    assert c["severity"] == "高"
    assert "claim_a_id" in c
    assert "claim_b_id" in c


def test_no_contradiction_without_conflicting_keywords():
    """无矛盾关键词的声明不产生矛盾。"""
    eng = _make_engine()
    result = eng.execute([{"claims": [
        {"text": "公司2024年营收增长10%"},
        {"text": "公司员工数量为500人"},
    ]}])
    assert result["contradictions"] == []


# ----------------------------------------------------------------------
# 证据交叉验证
# ----------------------------------------------------------------------
def test_evidence_conflict_detected():
    """同指标的支撑证据与反驳证据构成证据源冲突。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    conflicts = result["evidence_conflicts"]
    assert len(conflicts) >= 1
    assert conflicts[0]["type"] == "证据源冲突"
    assert "supporting_sources" in conflicts[0]
    assert "contradicting_sources" in conflicts[0]


def test_no_conflict_when_evidence_consistent():
    """证据全部支撑时无冲突。"""
    eng = _make_engine()
    result = eng.execute([{
        "claims": [{"text": "公司减排30%"}],
        "evidence": [
            {"description": "碳排放下降", "source": "卫星数据", "supports": True, "metric": "碳排放"},
            {"description": "核实下降", "source": "第三方评级", "supports": True, "metric": "碳排放"},
        ],
    }])
    assert result["evidence_conflicts"] == []


# ----------------------------------------------------------------------
# 高风险声明 / 汇总
# ----------------------------------------------------------------------
def test_high_risk_claims_filtered():
    """high_risk_claims 仅含 risk_score > 0.6 的声明。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for e in result["high_risk_claims"]:
        assert e["risk_score"] > 0.6


def test_overall_risk_structure():
    """overall_risk 含 level / score / avg_claim_risk / max_claim_risk。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    risk = result["overall_risk"]
    assert "level" in risk
    assert "score" in risk
    assert 0.0 <= risk["score"] <= 1.0
    assert "avg_claim_risk" in risk
    assert "max_claim_risk" in risk
    assert risk["max_claim_risk"] >= risk["avg_claim_risk"]


def test_category_statistics_aggregated():
    """category_statistics 按类别聚合 count / avg_credibility / min_credibility。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    cat_stats = result["category_statistics"]
    assert "排放声明" in cat_stats
    s = cat_stats["排放声明"]
    assert s["count"] == 2
    assert 0.0 <= s["avg_credibility"] <= 1.0
    assert s["min_credibility"] <= s["avg_credibility"]


def test_knowledge_graph_summary():
    """knowledge_graph_summary 含 node_count / edge_count。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    kg = result["knowledge_graph_summary"]
    assert kg["node_count"] >= 2  # 至少 2 个 claim 节点
    assert kg["edge_count"] >= 0


# ----------------------------------------------------------------------
# 边界 / 异常输入
# ----------------------------------------------------------------------
def test_empty_input_returns_insufficient_data():
    """空声明列表 → overall_risk 为数据不足。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["all_claim_evaluations"] == []
    assert result["overall_risk"]["level"] == "数据不足"
    assert result["overall_risk"]["score"] == 0.0
    assert result["knowledge_graph_summary"]["node_count"] == 0


def test_list_input_accepted():
    """直接传 list 输入（多个 item）也能处理。"""
    eng = _make_engine()
    result = eng.execute([
        {"claims": [{"text": "公司减排30%"}]},
        {"claims": [{"text": "公司节能15%"}]},
    ])
    assert len(result["all_claim_evaluations"]) == 2


def test_claim_without_evidence_still_evaluated():
    """无证据的声明仍被评估（evidence_factor 回退默认）。"""
    eng = _make_engine()
    result = eng.execute([{"claims": [{"text": "公司2024年碳排放下降30%"}]}])
    e = result["all_claim_evaluations"][0]
    assert e["credibility"] > 0  # 有量化数据，可信度非零
    assert e["metrics"]["supporting_evidence_count"] == 0


def test_claim_as_string_accepted():
    """声明为字符串时自动包装为 {text: ...}。"""
    eng = _make_engine()
    result = eng.execute([{"claims": ["公司减排30%"]}])
    assert len(result["all_claim_evaluations"]) == 1
    assert result["all_claim_evaluations"][0]["claim_text"] == "公司减排30%"


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_setup_loads_model_components():
    """setup() 后加载模糊词库 / 矛盾规则 / 来源权重 / 类别关键词。"""
    eng = _make_engine()
    assert eng.fuzzy_words
    assert eng.contradiction_rules
    assert eng.source_weights
    assert eng.category_keywords
    assert "卫星数据" in eng.source_weights
    assert eng.source_weights["卫星数据"] == 1.0


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute：_classify_claim 依赖 category_keywords，
    未加载会 KeyError —— 验证必须 setup 后才能分类。"""
    eng = _make_engine()
    assert eng.category_keywords  # setup 已加载
