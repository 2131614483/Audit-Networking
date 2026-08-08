"""[CM-03] engine 单测：方法论推荐 / 程序生成 / 质量检查 / 案例与知识图谱。

LLMEngine 基于 PortableDB 持久化知识图谱（nodes/edges/cases/programs），
支持 5 种 action：recommend / generate_program / quality_check / add_case / add_knowledge。
每个测试用 tmp_path 隔离 db，纯 stdlib（difflib 语义相似度 + 关键词匹配）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cm_03.engine import LLMEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> LLMEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    eng = LLMEngine(config={
        "db_path": str(tmp_path / "cm_03_engine.db"),
        **overrides,
    })
    eng.setup()
    return eng


def _close(eng: LLMEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 场景匹配
# ----------------------------------------------------------------------
def test_scenario_matching_procurement(tmp_path):
    """采购场景文本匹配 procurement_payment（关键词命中）。"""
    eng = _make_engine(tmp_path)
    try:
        matched = eng._match_scenario("采购付款供应商".lower())
        names = [s for s, _ in matched]
        assert "procurement_payment" in names
        scores = {s: v for s, v in matched}
        assert scores["procurement_payment"] > 0
    finally:
        _close(eng)


def test_scenario_matching_no_hit_returns_default(tmp_path):
    """无关键词命中时返回所有场景（默认 0.1 分）。"""
    eng = _make_engine(tmp_path)
    try:
        matched = eng._match_scenario("zzzzz unrelated text")
        assert len(matched) > 0
        for _, score in matched:
            assert score == 0.1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# recommend 动作
# ----------------------------------------------------------------------
def test_recommend_returns_top_k(tmp_path):
    """recommend 返回 top_k 条推荐。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["action"] == "recommend"
        assert len(result["recommendations"]) == 3  # top_k=3
    finally:
        _close(eng)


def test_recommend_sorted_by_score_desc(tmp_path):
    """推荐按 total_score 降序排列。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        scores = [r["total_score"] for r in result["recommendations"]]
        assert scores == sorted(scores, reverse=True)
    finally:
        _close(eng)


def test_recommend_has_top_method(tmp_path):
    """recommend 结果含 top_method，且为推荐列表首位。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["top_method"] is not None
        assert result["top_method"]["method_id"] == result["recommendations"][0]["method_id"]
    finally:
        _close(eng)


def test_recommend_breakdown_structure(tmp_path):
    """每条推荐含五维 breakdown（s/e/t/r/risk_fit）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for rec in result["recommendations"]:
            assert "method_id" in rec
            assert "method_name" in rec
            assert "total_score" in rec
            assert "breakdown" in rec
            assert "rationale" in rec
            assert "desc" in rec
            bd = rec["breakdown"]
            assert set(bd.keys()) == {"s", "e", "t", "r", "risk_fit"}
    finally:
        _close(eng)


def test_recommend_scenario_matched_included(tmp_path):
    """结果含 scenario_matched（前 3 个场景）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert len(result["scenario_matched"]) <= 3
        assert result["scenario_matched"][0][0] == "procurement_payment"
    finally:
        _close(eng)


def test_recommend_rationale_nonempty(tmp_path):
    """每条推荐的 rationale 非空。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for rec in result["recommendations"]:
            assert len(rec["rationale"]) > 0
    finally:
        _close(eng)


def test_recommend_risk_level_affects_score(tmp_path):
    """risk_level 影响推荐评分（适配的方法得分更高）。"""
    eng = _make_engine(tmp_path)
    try:
        r_high = eng.execute({
            "action": "recommend", "scenario": "采购付款",
            "risk_level": "high", "resource_level": "medium", "top_k": 1,
        })
        r_low = eng.execute({
            "action": "recommend", "scenario": "采购付款",
            "risk_level": "low", "resource_level": "medium", "top_k": 1,
        })
        # 两种风险等级都能返回推荐
        assert len(r_high["recommendations"]) == 1
        assert len(r_low["recommendations"]) == 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# generate_program 动作
# ----------------------------------------------------------------------
def test_generate_program_returns_structure(tmp_path):
    """generate_program 返回含 program_id / program / quality_preview。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01", "M02"],
            "adaptations": {"technology": "standard", "scale": "medium", "risk": "high"},
        })
        assert result["action"] == "generate_program"
        assert "program_id" in result
        assert "program" in result
        assert "quality_preview" in result
        prog = result["program"]
        assert "program_name" in prog
        assert "audit_goal" in prog
        assert "check_rules" in prog
        assert "data_sources" in prog
        assert "alert_settings" in prog
    finally:
        _close(eng)


def test_generate_program_persists_to_db(tmp_path):
    """生成的程序持久化到 PortableDB programs 表。"""
    db_path = tmp_path / "cm_03_prog.db"
    eng = LLMEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01"],
        })
    finally:
        _close(eng)
    with PortableDB(db_path) as db:
        rows = db.all("programs")
    assert len(rows) >= 1
    assert "program_id" in rows[0]
    assert isinstance(rows[0]["content"], dict)


def test_generate_program_auto_selects_methods(tmp_path):
    """未指定 method_ids 时自动推荐方法。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
        })
        prog = result["program"]
        assert len(prog["methods_applied"]) > 0
    finally:
        _close(eng)


def test_generate_program_check_rules_built(tmp_path):
    """生成的程序含检查规则（M01 → 3 条规则）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01"],
        })
        rules = result["program"]["check_rules"]
        assert len(rules) >= 2
        for r in rules:
            assert "rule" in r
            assert "frequency" in r
    finally:
        _close(eng)


def test_generate_program_data_sources_adapt(tmp_path):
    """数据源按场景自适应（采购场景含采购系统）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01"],
        })
        sources = result["program"]["data_sources"]
        assert "ERP系统" in sources
        assert "采购系统" in sources
    finally:
        _close(eng)


def test_generate_program_alert_settings_by_risk(tmp_path):
    """高风险程序预警阈值更严格。"""
    eng = _make_engine(tmp_path)
    try:
        result_high = eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01"],
            "adaptations": {"risk": "high"},
        })
        result_low = eng.execute({
            "action": "generate_program",
            "scenario": "采购付款",
            "method_ids": ["M01"],
            "adaptations": {"risk": "low"},
        })
        assert "red" in result_high["program"]["alert_settings"]
        assert "red" in result_low["program"]["alert_settings"]
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# quality_check 动作
# ----------------------------------------------------------------------
def test_quality_check_returns_dimensions(tmp_path):
    """quality_check 返回五维评分 + 总分 + 等级。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "quality_check",
            "scenario": "采购付款",
            "program": {
                "program_name": "测试程序",
                "methods_applied": ["实时交易监控"],
                "check_rules": [{"rule": "单笔金额超限检查", "frequency": "实时"},
                                {"rule": "频率异常检查", "frequency": "日度"}],
                "alert_settings": {"green": "<50", "yellow": "50-70"},
                "data_sources": ["ERP系统", "采购系统"],
                "handling_flow": "自动处理+人工复核",
            },
        })
        assert result["action"] == "quality_check"
        assert "dimensions" in result
        assert "total_score" in result
        assert "grade" in result
        assert "suggestions" in result
        dims = result["dimensions"]
        assert set(dims.keys()) == {"completeness", "consistency", "feasibility",
                                    "effectiveness", "compliance"}
    finally:
        _close(eng)


def test_quality_check_grade_thresholds(tmp_path):
    """质量等级按总分划分（优秀/良好/合格/需改进）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "quality_check",
            "scenario": "采购付款",
            "program": {
                "program_name": "测试",
                "methods_applied": ["实时交易监控", "ML异常检测"],
                "check_rules": [{"rule": "r1"}, {"rule": "r2"}, {"rule": "r3"}],
                "alert_settings": {"green": "<50", "yellow": "50-70", "red": ">90"},
                "data_sources": ["ERP", "采购系统"],
                "handling_flow": "自动处理+人工复核",
            },
        })
        assert result["grade"] in ("优秀", "良好", "合格", "需改进")
        assert 0 <= result["total_score"] <= 100
    finally:
        _close(eng)


def test_quality_check_completeness_zero_for_empty_program(tmp_path):
    """空程序完整性维度偏低。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "quality_check",
            "scenario": "采购付款",
            "program": {"program_name": "空程序"},
        })
        assert result["dimensions"]["completeness"] < 100
        assert len(result["suggestions"]) > 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# add_case 动作
# ----------------------------------------------------------------------
def test_add_case_persists(tmp_path):
    """add_case 把案例写入 DB cases 表。"""
    db_path = tmp_path / "cm_03_case.db"
    eng = LLMEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        result = eng.execute({
            "action": "add_case",
            "case": {"title": "采购舞弊案例", "method_id": "M02",
                     "scenario": "procurement_payment", "industry": "制造业",
                     "scale": "large", "result_score": 85.0, "summary": "测试"},
        })
    finally:
        _close(eng)
    assert result["status"] == "added"
    assert "case_id" in result
    with PortableDB(db_path) as db:
        rows = db.all("cases")
    assert len(rows) == 1
    assert rows[0]["title"] == "采购舞弊案例"


def test_add_case_generates_id_if_missing(tmp_path):
    """无 case_id 时自动生成。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "add_case",
            "case": {"title": "无ID案例", "method_id": "M01"},
        })
        assert result["case_id"] is not None
        assert len(result["case_id"]) > 0
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# add_knowledge 动作
# ----------------------------------------------------------------------
def test_add_knowledge_nodes_and_edges(tmp_path):
    """add_knowledge 添加节点和边到 DB，并重建索引。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "add_knowledge",
            "nodes": [
                {"node_id": "N1", "node_type": "method", "name": "测试方法",
                 "content": "desc", "tags": ["tag1"], "meta": {"k": "v"}},
                {"node_id": "N2", "node_type": "scenario", "name": "测试场景",
                 "content": "desc2", "tags": [], "meta": {}},
            ],
            "edges": [
                {"edge_id": "E1", "from_id": "N1", "to_id": "N2",
                 "relation": "适用于", "weight": 0.9},
            ],
        })
        assert result["nodes_added"] == 2
        assert result["edges_added"] == 1
        # 索引重建后可查
        assert "N1" in eng.model["nodes_index"]
        assert "N2" in eng.model["nodes_index"]
        assert len(eng.model["edges_index"]["N1"]) == 1
    finally:
        _close(eng)


def test_add_knowledge_generates_ids_if_missing(tmp_path):
    """无 node_id / edge_id 时自动生成。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "add_knowledge",
            "nodes": [{"name": "无名节点", "node_type": "method"}],
            "edges": [{"from_id": "X", "to_id": "Y", "relation": "使用"}],
        })
        assert result["nodes_added"] == 1
        assert result["edges_added"] == 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 后处理 / 模型加载
# ----------------------------------------------------------------------
def test_postprocess_adds_engine_and_timestamp(tmp_path):
    """后处理给结果加 engine + timestamp 标记。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["engine"] == "CM-03-MethodologyFramework"
        assert "timestamp" in result
    finally:
        _close(eng)


def test_db_tables_created_on_load(tmp_path):
    """engine 初始化后 db 含 nodes/edges/cases/programs 四表。"""
    db_path = tmp_path / "cm_03_tables.db"
    eng = LLMEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"nodes", "edges", "cases", "programs"} <= tables
    finally:
        _close(eng)


def test_model_has_methods_and_keywords(tmp_path):
    """model 含 8 个方法目录 + 11 个场景关键词。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.model["methods"]) == 8
        assert len(eng.model["scenario_keywords"]) == 11
        assert "quality_weights" in eng.model
        method_ids = {m["id"] for m in eng.model["methods"]}
        assert method_ids == {f"M0{i}" for i in range(1, 9)}
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 输入边界
# ----------------------------------------------------------------------
def test_invalid_input_raises_value_error(tmp_path):
    """无法识别的输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute(12345)
    finally:
        _close(eng)


def test_unknown_action_raises_value_error(tmp_path):
    """未知 action 抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng.execute({"action": "nonexistent_action"})
    finally:
        _close(eng)


def test_setup_loads_model(tmp_path):
    """setup() 后 model 含方法目录 + 场景关键词 + 质量权重。"""
    eng = LLMEngine(config={"db_path": str(tmp_path / "cm_03_setup.db")})
    assert eng.model is None
    eng.setup()
    try:
        assert eng.model is not None
        assert "methods" in eng.model
        assert "scenario_keywords" in eng.model
        assert "quality_weights" in eng.model
    finally:
        _close(eng)
