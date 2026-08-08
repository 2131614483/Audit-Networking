"""[TA-06] engine 单测：知识图谱关联交易 / 壳公司 / 避税天堂 / 风险评分。

KGEngine 基于 PortableDB 持久化（entity_nodes/transaction_edges 表），
纯 stdlib 图分析 + 风险评分。每个测试用 tmp_path 隔离 db，结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ta_06.engine import KGEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> KGEngine:
    eng = KGEngine(config={"db_path": str(tmp_path / "ta_06_engine.db"), **overrides})
    eng.setup()
    return eng


def _close(eng: KGEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_risk_weights_and_havens(tmp_path):
    """setup 后 model 含 risk_weights / tax_havens / shell_company_markers。"""
    eng = _make_engine(tmp_path)
    try:
        assert "risk_weights" in eng.model
        assert "tax_havens" in eng.model
        assert "shell_company_markers" in eng.model
        assert "开曼" in eng.model["tax_havens"]
        assert "香港" in eng.model["tax_havens"]
    finally:
        _close(eng)


def test_db_tables_created(tmp_path):
    """setup 后 db 含 entity_nodes / transaction_edges 两表。"""
    db_path = tmp_path / "ta_06_tables.db"
    eng = KGEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"entity_nodes", "transaction_edges"} <= tables
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_parses_entities_and_edges(tmp_path):
    """预处理解析 entities + transactions → edges。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert len(prepared["entities"]) == 5
        assert len(prepared["edges"]) == 4
        e = prepared["entities"][0]
        assert e["node_id"] == "ENT-001"
        assert e["name"] == "中国制造有限公司"
    finally:
        _close(eng)


def test_preprocess_generates_id_if_missing(tmp_path):
    """无 entity_id 时自动生成。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"entities": [{"name": "X"}]})
        assert prepared["entities"][0]["node_id"].startswith("ENT-")
    finally:
        _close(eng)


def test_preprocess_non_dict_raises(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng._preprocess("not a dict")
    finally:
        _close(eng)


def test_preprocess_deduplicates_entities(tmp_path):
    """重复 entity_id 的实体被去重。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"entities": [
            {"entity_id": "DUP", "name": "A"},
            {"entity_id": "DUP", "name": "B"},
        ]})
        assert len(prepared["entities"]) == 1
    finally:
        _close(eng)


def test_preprocess_skips_invalid_transactions(tmp_path):
    """缺 from/to 的交易被跳过。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({
            "entities": [{"entity_id": "E1"}, {"entity_id": "E2"}],
            "transactions": [
                {"from": "E1", "to": "E2", "amount": 100},
                {"from": "E1", "amount": "bad"},  # 缺 to + amount 无效
                {"amount": 50},  # 缺 from/to
            ],
        })
        assert len(prepared["edges"]) == 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 壳公司检测
# ----------------------------------------------------------------------
def test_shell_company_detection_by_no_operations(tmp_path):
    """无实际经营 → 壳公司。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        shells = {e["node_id"]: e["is_shell"] for e in prepared["entities"]}
        # ENT-002 has_operations=False → shell
        assert shells["ENT-002"] is True
        # ENT-001 has_operations=True → not shell
        assert shells["ENT-001"] is False
    finally:
        _close(eng)


def test_shell_company_detection_by_type(tmp_path):
    """company_type=投资控股 → 壳公司。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        e2 = next(e for e in prepared["entities"] if e["node_id"] == "ENT-002")
        assert e2["is_shell"] is True
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 风险评分
# ----------------------------------------------------------------------
def test_risk_scores_computed(tmp_path):
    """每个实体有风险评分（total + level + breakdown）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for eid, risk in result["risk_scores"].items():
            assert "total" in risk
            assert "level" in risk
            assert "breakdown" in risk
            assert risk["level"] in {"高风险", "中风险", "低风险"}
    finally:
        _close(eng)


def test_tax_haven_risk(tmp_path):
    """避税天堂实体的 tax_haven 评分为 1.0。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        ent002 = result["risk_scores"]["ENT-002"]
        assert ent002["breakdown"]["tax_haven"] == 1.0  # 开曼
        ent001 = result["risk_scores"]["ENT-001"]
        assert ent001["breakdown"]["tax_haven"] == 0.1  # 中国
    finally:
        _close(eng)


def test_shell_company_risk(tmp_path):
    """壳公司 shell_company 评分为 1.0。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        ent002 = result["risk_scores"]["ENT-002"]
        assert ent002["breakdown"]["shell_company"] == 1.0
        ent001 = result["risk_scores"]["ENT-001"]
        assert ent001["breakdown"]["shell_company"] == 0.2
    finally:
        _close(eng)


def test_risk_level_classification(tmp_path):
    """风险分级：高风险/中风险/低风险。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        levels = {eid: r["level"] for eid, r in result["risk_scores"].items()}
        # ENT-002（开曼+壳+多层）应为高风险
        assert levels["ENT-002"] == "高风险"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 社区检测 & 集团聚类
# ----------------------------------------------------------------------
def test_community_detection(tmp_path):
    """社区检测返回 communities dict。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "communities" in result
        assert len(result["communities"]) == 5
    finally:
        _close(eng)


def test_group_clustering_by_parent(tmp_path):
    """按 ultimate_parent 聚类为集团。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        clusters = result["group_clusters"]
        assert "GROUP-A" in clusters
        assert "GROUP-B" in clusters
        assert len(clusters["GROUP-A"]) == 3  # ENT-001/002/003
        assert len(clusters["GROUP-B"]) == 2  # ENT-004/005
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 路径追踪
# ----------------------------------------------------------------------
def test_path_tracing_from_first_entity(tmp_path):
    """从第一个实体 BFS 追踪关联路径。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        paths = result["paths"]
        assert len(paths) > 0
        # 路径以 ENT-001 的名称开头
        assert paths[0]["path"][0] == "中国制造有限公司"
        assert paths[0]["length"] >= 2
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 端到端 execute
# ----------------------------------------------------------------------
def test_execute_returns_full_result(tmp_path):
    """execute 返回完整结果（entities/edges/communities/risk_scores/paths/summary）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "entities" in result
        assert "edges" in result
        assert "communities" in result
        assert "risk_scores" in result
        assert "group_clusters" in result
        assert "paths" in result
        assert "summary" in result
    finally:
        _close(eng)


def test_summary_aggregates(tmp_path):
    """summary 聚合 entity/transaction/shell/total_volume 计数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["entity_count"] == 5
        assert s["transaction_count"] == 4
        assert s["shell_count"] == 3  # ENT-002/003/005
        assert s["total_volume"] == 11000000.0  # 5M+3M+2M+1M
        assert s["group_count"] == 2
        assert "avg_risk_score" in s
    finally:
        _close(eng)


def test_postprocess_adds_high_risk_count(tmp_path):
    """postprocess 添加 high_risk_entities 计数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert "high_risk_entities" in result["summary"]
        assert result["summary"]["high_risk_entities"] >= 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界
# ----------------------------------------------------------------------
def test_empty_input(tmp_path):
    """空输入返回零计数 summary（不崩）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"entities": [], "transactions": []})
        assert result["summary"]["entity_count"] == 0
        assert result["summary"]["transaction_count"] == 0
        assert result["paths"] == []
    finally:
        _close(eng)
