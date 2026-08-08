"""[FI-02] engine 单测：担保链风险知识图谱（拓扑风险 / PageRank / 社区 / 冲击模拟）。

KGEngine 基于 PortableDB 持久化担保网络，纯 stdlib：
  * 担保图：有向图 Guarantor → Borrower，权重=担保金额
  * 风险评分：leverage + connectedness + guarantee_concentration + financial_health + historical_default
  * 系统重要性：PageRank
  * 社区检测：Louvain 标签传播
  * 冲击模拟：BFS 多米诺扩散（decay=0.7, max_depth=5）
每个测试用 tmp_path 隔离 db，Windows 下结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.fi_02.engine import KGEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> KGEngine:
    eng = KGEngine(config={
        "db_path": str(tmp_path / "fi_02_engine.db"),
        **overrides,
    })
    eng.setup()
    return eng


def _close(eng: KGEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


def _entity(**fields) -> dict:
    base = {
        "entity_id": "X1",
        "name": "测试实体",
        "industry": "制造业",
        "leverage": 0.5,
        "current_ratio": 1.5,
        "has_default_history": False,
        "total_assets": 1000000,
    }
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 风险评分结构
# ----------------------------------------------------------------------
def test_risk_scores_cover_all_entities(tmp_path):
    """每个实体都有风险评分。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert set(result["risk_scores"].keys()) == {"E1", "E2", "E3", "E4", "E5"}
    finally:
        _close(eng)


def test_risk_score_structure(tmp_path):
    """风险评分含 total / level / breakdown / pagerank。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for eid, r in result["risk_scores"].items():
            assert "total" in r
            assert "level" in r
            assert "breakdown" in r
            assert "pagerank" in r
            assert 0.0 <= r["total"] <= 1.0
            assert r["level"] in ("高", "中", "低")
    finally:
        _close(eng)


def test_breakdown_has_five_dimensions(tmp_path):
    """breakdown 含 5 个风险维度。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        bd = result["risk_scores"]["E1"]["breakdown"]
        assert set(bd.keys()) == {
            "leverage", "connectedness", "guarantee_concentration",
            "financial_health", "historical_default",
        }
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 风险评分公式
# ----------------------------------------------------------------------
def test_high_risk_entity_e1(tmp_path):
    """E1（高杠杆+违约历史+担保集中）风险评分 >= 0.6 → 高。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        r = result["risk_scores"]["E1"]
        assert r["level"] == "高"
        assert r["total"] >= 0.6
        # leverage 维度
        assert r["breakdown"]["leverage"] == 0.95
        # 历史违约 → historical_default = 1.0
        assert r["breakdown"]["historical_default"] == 1.0
        # 担保集中度：10M / 5M = 2.0 → 2.0/2.0 = 1.0
        assert r["breakdown"]["guarantee_concentration"] == 1.0
    finally:
        _close(eng)


def test_low_risk_entity_e5(tmp_path):
    """E5（低杠杆+无违约+无对外担保）风险评分 < 0.3 → 低。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        r = result["risk_scores"]["E5"]
        assert r["level"] == "低"
        assert r["total"] < 0.3
        assert r["breakdown"]["historical_default"] == 0.1  # 无违约历史
        assert r["breakdown"]["guarantee_concentration"] == 0.0  # 无对外担保
    finally:
        _close(eng)


def test_risk_level_thresholds(tmp_path):
    """风险等级阈值：>=0.6 高 / >=0.3 中 / <0.3 低。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for eid, r in result["risk_scores"].items():
            if r["total"] >= 0.6:
                assert r["level"] == "高"
            elif r["total"] >= 0.3:
                assert r["level"] == "中"
            else:
                assert r["level"] == "低"
    finally:
        _close(eng)


def test_default_history_increases_risk(tmp_path):
    """有违约历史的实体 historical_default=1.0，无违约=0.1。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["risk_scores"]["E1"]["breakdown"]["historical_default"] == 1.0
        assert result["risk_scores"]["E2"]["breakdown"]["historical_default"] == 0.1
    finally:
        _close(eng)


def test_financial_health_peaks_at_cr_1_5(tmp_path):
    """current_ratio=1.5 时 financial_health 最高（=1.0）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [
            _entity(entity_id="H1", current_ratio=1.5),
        ], "guarantees": []})
        assert result["risk_scores"]["H1"]["breakdown"]["financial_health"] == 1.0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# PageRank / 系统重要性
# ----------------------------------------------------------------------
def test_pagerank_non_negative(tmp_path):
    """所有节点 PageRank >= 0。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for eid, r in result["risk_scores"].items():
            assert r["pagerank"] >= 0
    finally:
        _close(eng)


def test_pagerank_sink_node_lower(tmp_path):
    """无出边的节点（E3/E5）PageRank 不高于有出边的节点（E1）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        pr_e1 = result["risk_scores"]["E1"]["pagerank"]
        pr_e3 = result["risk_scores"]["E3"]["pagerank"]
        assert pr_e1 >= pr_e3
    finally:
        _close(eng)


def test_top_systemic_in_summary(tmp_path):
    """summary.top_systemic 按 PageRank 降序排列，最多 10 个。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        top = result["summary"]["top_systemic"]
        assert len(top) <= 10
        prs = [r["pagerank"] for _, r in top]
        assert prs == sorted(prs, reverse=True)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 社区检测
# ----------------------------------------------------------------------
def test_communities_assigned_to_all(tmp_path):
    """每个实体都被分配到某个社区。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        comms = result["communities"]
        assert set(comms.keys()) == {"E1", "E2", "E3", "E4", "E5"}
    finally:
        _close(eng)


def test_community_count_in_summary(tmp_path):
    """summary.community_count 与实际社区数一致。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        actual = len(set(result["communities"].values()))
        assert result["summary"]["community_count"] == actual
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 冲击模拟
# ----------------------------------------------------------------------
def test_shock_simulations_for_high_risk_seeds(tmp_path):
    """有高风险实体时产生冲击模拟结果。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        shocks = result["shock_simulations"]
        assert len(shocks) >= 1
        for s in shocks:
            assert "seed" in s
            assert "affected_count" in s
            assert "max_intensity" in s
            assert "spread_depth" in s
    finally:
        _close(eng)


def test_shock_seed_is_high_risk(tmp_path):
    """冲击模拟的种子节点都是高风险实体。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        high_ids = {eid for eid, r in result["risk_scores"].items()
                    if r["level"] == "高"}
        for s in result["shock_simulations"]:
            assert s["seed"] in high_ids
    finally:
        _close(eng)


def test_shock_max_intensity_is_seed(tmp_path):
    """冲击模拟最大强度 = 种子节点强度（1.0）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for s in result["shock_simulations"]:
            assert s["max_intensity"] == 1.0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 汇总统计 / 系统性风险
# ----------------------------------------------------------------------
def test_summary_structure(tmp_path):
    """summary 含实体数 / 担保数 / 高风险数 / 担保总额。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["entity_count"] == 5
        assert s["guarantee_count"] == 5
        assert s["high_risk_count"] == 2  # E1 + E4
        assert s["total_guarantee_amount"] == 13000000  # 5+3+2+1+2 M
    finally:
        _close(eng)


def test_systemic_risk_level_high(tmp_path):
    """高风险实体占比 > 20% → 系统性风险等级=高。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        # 2/5 = 40% > 20%
        assert result["summary"]["systemic_risk_level"] == "高"
    finally:
        _close(eng)


def test_systemic_risk_level_low_for_healthy_network(tmp_path):
    """无高风险实体 → 系统性风险等级=低。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [
            _entity(entity_id="H1", leverage=0.2, current_ratio=2.0,
                    has_default_history=False, total_assets=10000000),
            _entity(entity_id="H2", leverage=0.2, current_ratio=2.0,
                    has_default_history=False, total_assets=10000000),
        ], "guarantees": [
            {"guarantor": "H1", "borrower": "H2", "amount": 100000, "guarantee_ratio": 0.1},
        ]})
        assert result["summary"]["systemic_risk_level"] == "低"
        assert result["summary"]["high_risk_count"] == 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界 / 异常输入
# ----------------------------------------------------------------------
def test_empty_entities_and_guarantees(tmp_path):
    """空实体和担保列表返回零汇总。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [], "guarantees": []})
        assert result["summary"]["entity_count"] == 0
        assert result["summary"]["guarantee_count"] == 0
        assert result["risk_scores"] == {}
    finally:
        _close(eng)


def test_non_dict_input_raises_value_error(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute("invalid")
    finally:
        _close(eng)


def test_entities_auto_created_from_edges(tmp_path):
    """边中出现的实体（不在 entities 列表中）自动创建默认节点。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [], "guarantees": [
            {"guarantor": "A", "borrower": "B", "amount": 100000, "guarantee_ratio": 1.0},
        ]})
        assert "A" in result["guarantors"]
        assert "B" in result["guarantors"]
        assert result["summary"]["entity_count"] == 2
    finally:
        _close(eng)


def test_from_to_aliases_accepted(tmp_path):
    """担保边支持 from/to 作为 guarantor/borrower 的别名。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [], "guarantees": [
            {"from": "A", "to": "B", "amount": 50000, "guarantee_ratio": 1.0},
        ]})
        assert len(result["edges"]) == 1
        assert result["edges"][0]["guarantor"] == "A"
        assert result["edges"][0]["borrower"] == "B"
    finally:
        _close(eng)


def test_missing_fields_use_defaults(tmp_path):
    """缺少财务字段的实体使用默认值（不崩）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [{"entity_id": "M1"}], "guarantees": []})
        r = result["risk_scores"]["M1"]
        assert 0 <= r["total"] <= 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 模型加载 / DB
# ----------------------------------------------------------------------
def test_db_tables_created(tmp_path):
    """engine 初始化后 db 含 guarantee_edges / guarantor_nodes 两表。"""
    db_path = tmp_path / "fi_02_tables.db"
    eng = KGEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"guarantee_edges", "guarantor_nodes"} <= tables
    finally:
        _close(eng)


def test_model_has_risk_weights(tmp_path):
    """model 含风险权重 / 冲击阈值 / 衰减系数。"""
    eng = _make_engine(tmp_path)
    try:
        assert "risk_weights" in eng.model
        assert eng.model["risk_weights"]["leverage"] == 0.25
        assert eng.model["contagion_decay"] == 0.7
        assert eng.model["max_shock_depth"] == 5
    finally:
        _close(eng)


def test_lazy_load_on_execute(tmp_path):
    """不调 setup() 直接 execute 也能懒加载模型。"""
    eng = KGEngine(config={"db_path": str(tmp_path / "fi_02_lazy.db")})
    assert eng.model is None
    try:
        result = eng.execute({"entities": [], "guarantees": []})
        assert eng.model is not None
        assert result["summary"]["entity_count"] == 0
    finally:
        _close(eng)
