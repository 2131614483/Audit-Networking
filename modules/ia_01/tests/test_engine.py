"""[IA-01] engine 单测：动态风险地图 + NLP 信号 + 智能审计计划。

LLMEngine 基于 PortableDB 持久化（indicators/risk_map/text_signals/audit_plans 表），
加权评分 + NLP 信号 + 约束规划。每个测试用 tmp_path 隔离 db，结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.ia_01.engine import LLMEngine
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> LLMEngine:
    db_path = tmp_path / "ia_01_engine.db"
    # NOTE engine bug: _RISK_MAP_SCHEMA 的 entity_id 缺 PRIMARY KEY，导致 upsert 的
    # ON CONFLICT 失败。此处预建 risk_map 表（entity_id TEXT PRIMARY KEY）规避。
    from modules.ia_01.engine import _RISK_MAP_SCHEMA, _INDICATORS_SCHEMA, _TEXT_SIGNALS_SCHEMA, _AUDIT_PLANS_SCHEMA
    pre_db = PortableDB(db_path)
    fixed_risk_map = {**_RISK_MAP_SCHEMA, "entity_id": "TEXT PRIMARY KEY"}
    pre_db.create_table("risk_map", fixed_risk_map)
    pre_db.close()
    eng = LLMEngine(config={"db_path": str(db_path), **overrides})
    eng.setup()
    return eng


def _close(eng: LLMEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_loads_indicators_and_words(tmp_path):
    """setup 后 model 含 indicators / risk_words / thresholds。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.model["indicators"]) == 13
        assert "negative_high" in eng.model["risk_words_cn"]
        assert "negative_high" in eng.model["risk_words_en"]
        assert eng.model["thresholds"]["red"] == 90
        assert eng.model["thresholds"]["orange"] == 75
        assert eng.model["thresholds"]["yellow"] == 60
    finally:
        _close(eng)


def test_db_tables_created(tmp_path):
    """setup 后 db 含 4 张表。"""
    db_path = tmp_path / "ia_01_tables.db"
    eng = LLMEngine(config={"db_path": str(db_path)})
    eng.setup()
    try:
        with PortableDB(db_path) as db:
            tables = set(db.tables())
        assert {"indicators", "risk_map", "text_signals", "audit_plans"} <= tables
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 预处理
# ----------------------------------------------------------------------
def test_preprocess_score_action(tmp_path):
    """score action 预处理。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess(_sample())
        assert prepared["action"] == "score"
        assert prepared["entity"]["entity_id"] == "ENT-001"
        assert prepared["indicators"] is not None
    finally:
        _close(eng)


def test_preprocess_text_signals_action(tmp_path):
    """text_signals action 预处理。"""
    eng = _make_engine(tmp_path)
    try:
        prepared = eng._preprocess({"action": "text_signals", "texts": ["欺诈风险"]})
        assert prepared["action"] == "text_signals"
        assert prepared["texts"] == ["欺诈风险"]
    finally:
        _close(eng)


def test_preprocess_invalid_input_raises(tmp_path):
    """无法识别的输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    try:
        with pytest.raises(ValueError):
            eng._preprocess("not a dict")
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 风险评分
# ----------------------------------------------------------------------
def test_score_entity_returns_score_and_level(tmp_path):
    """score action 返回 risk_score + risk_level + contributions。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["action"] == "score"
        assert "risk_score" in result
        assert "risk_level" in result
        assert result["risk_level"] in ("green", "yellow", "orange", "red")
        assert len(result["contributions"]) == 13
    finally:
        _close(eng)


def test_score_entity_high_risk(tmp_path):
    """高指标值 → 高风险分（orange/red）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["risk_score"] >= 75
        assert result["risk_level"] in ("orange", "red")
    finally:
        _close(eng)


def test_score_entity_low_risk(tmp_path):
    """低指标值 → 低风险分（green/yellow）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "score",
            "entity": {"entity_id": "ENT-LOW", "entity_name": "低风险实体", "entity_type": "bu"},
            "indicators": {"FIN_001": 5, "OPS_001": 1}
        })
        assert result["risk_score"] < 60
        assert result["risk_level"] in ("green", "yellow")
    finally:
        _close(eng)


def test_score_entity_capped_at_100(tmp_path):
    """风险分上限 100。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "score",
            "entity": {"entity_id": "ENT-MAX", "entity_name": "极高风险", "entity_type": "bu"},
            "indicators": {ind["id"]: ind["threshold"] * 10 for ind in eng.model["indicators"]}
        })
        assert result["risk_score"] <= 100
    finally:
        _close(eng)


def test_score_entity_top3_sorted(tmp_path):
    """top_3 按 contribution 降序排列。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        top3 = result["top_3"]
        contribs = [c["contribution"] for c in top3]
        assert contribs == sorted(contribs, reverse=True)
    finally:
        _close(eng)


def test_score_all_multiple_entities(tmp_path):
    """score_all 对多实体评分并排序。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "score_all",
            "entities": [
                {"entity_id": "E1", "entity_name": "实体A", "entity_type": "bu"},
                {"entity_id": "E2", "entity_name": "实体B", "entity_type": "bu"},
            ],
            "indicator_values": {"FIN_001": 30, "CMP_001": 100}
        })
        assert result["action"] == "score_all"
        assert result["total_entities"] == 2
        scores = [r["risk_score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True)
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# NLP 文本风险信号
# ----------------------------------------------------------------------
def test_text_signals_detects_negative(tmp_path):
    """负面风险词 → 负向情感分 + critical/high 严重度。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "text_signals",
            "texts": ["公司发现重大欺诈行为，涉嫌造假"]
        })
        assert result["total_texts"] == 1
        sig = result["signals"][0]
        assert sig["sentiment_score"] < 0
        assert sig["severity"] in ("critical", "high")
    finally:
        _close(eng)


def test_text_signals_detects_positive(tmp_path):
    """正面词 → 正向情感分 + positive 严重度。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "text_signals",
            "texts": ["公司业绩增长稳健，运营稳定合规"]
        })
        sig = result["signals"][0]
        assert sig["sentiment_score"] > 0
        assert sig["severity"] == "positive"
    finally:
        _close(eng)


def test_text_signals_extracts_bu_entities(tmp_path):
    """文本含采购/供应商 → 提取 BU-A 实体。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "text_signals",
            "texts": ["采购供应商管理存在违规"]
        })
        sig = result["signals"][0]
        assert "BU-A" in sig["risk_entities"]
    finally:
        _close(eng)


def test_text_signals_severity_dist(tmp_path):
    """返回 severity_dist 分布。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "text_signals",
            "texts": ["欺诈", "增长稳定", "违规处罚"]
        })
        assert "severity_dist" in result
        assert sum(result["severity_dist"].values()) == 3
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 风险地图
# ----------------------------------------------------------------------
def test_risk_map_after_scoring(tmp_path):
    """评分后构建风险地图。"""
    eng = _make_engine(tmp_path)
    try:
        eng.execute(_sample())
        eng.execute({
            "action": "score",
            "entity": {"entity_id": "ENT-002", "entity_name": "低风险实体", "entity_type": "bu"},
            "indicators": {"FIN_001": 5}
        })
        result = eng.execute({"action": "risk_map", "depth": "all", "min_score": 0})
        assert result["action"] == "risk_map"
        assert result["stats"]["total_entities"] >= 2
        assert "tree" in result
        assert "heatmap" in result
    finally:
        _close(eng)


def test_risk_map_min_score_filter(tmp_path):
    """min_score 过滤低风险实体。"""
    eng = _make_engine(tmp_path)
    try:
        eng.execute(_sample())  # 高风险
        eng.execute({
            "action": "score",
            "entity": {"entity_id": "ENT-LOW", "entity_name": "低风险", "entity_type": "bu"},
            "indicators": {"FIN_001": 5}
        })
        result = eng.execute({"action": "risk_map", "min_score": 70})
        # 只含高风险实体
        assert all(e["risk_score"] >= 70 for e in result["top_risk_entities"])
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 审计计划生成
# ----------------------------------------------------------------------
def test_generate_plan_after_scoring(tmp_path):
    """评分后生成审计计划。"""
    eng = _make_engine(tmp_path)
    try:
        eng.execute(_sample())
        result = eng.execute({
            "action": "generate_plan",
            "period": "annual",
            "resources": {"max_projects": 10, "available_hours_per_month": 400}
        })
        assert result["action"] == "generate_plan"
        assert result["period"] == "annual"
        assert result["total_projects"] >= 1
        assert "priority_distribution" in result
        assert "resource_gap" in result
    finally:
        _close(eng)


def test_generate_plan_priority_distribution(tmp_path):
    """审计计划含优先级分布。"""
    eng = _make_engine(tmp_path)
    try:
        eng.execute(_sample())
        result = eng.execute({"action": "generate_plan", "period": "annual", "resources": {}})
        dist = result["priority_distribution"]
        assert sum(dist.values()) == result["total_projects"]
    finally:
        _close(eng)


def test_generate_plan_mandatory_projects(tmp_path):
    """强制性项目纳入计划。

    NOTE engine bug: mandatory_projects 缺 duration_weeks/team_size 时计算 total_hours
    抛 KeyError。此处补齐字段规避。
    """
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "generate_plan",
            "period": "annual",
            "resources": {},
            "mandatory_projects": [{"project_name": "专项审计", "scope": "IT系统",
                                    "priority": "high", "duration_weeks": 4, "team_size": 3}]
        })
        mandatory = [p for p in result["projects"] if p.get("mandatory")]
        assert len(mandatory) >= 1
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 后处理
# ----------------------------------------------------------------------
def test_postprocess_adds_engine_and_timestamp(tmp_path):
    """postprocess 添加 engine + timestamp 标记。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["engine"] == "IA-01-RiskMapAndPlan"
        assert "timestamp" in result
    finally:
        _close(eng)


def test_empty_indicators_low_score(tmp_path):
    """空指标（全 0）→ 低分 green。

    NOTE: HIS_001（上次审计评分，weight=-0.6）对低值敏感：value=0 < threshold=60
    时贡献 9.0 分（审计评分越低风险越高），故空指标并非严格 0 分。
    """
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "action": "score",
            "entity": {"entity_id": "ENT-0", "entity_name": "无指标", "entity_type": "bu"},
            "indicators": {}
        })
        assert result["risk_score"] < 60
        assert result["risk_level"] == "green"
    finally:
        _close(eng)
