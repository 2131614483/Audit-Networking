"""[FI-05] engine 单测：AI监管口径自动更新（变更检测 / 差异分析 / 影响评估 / 紧急度）。

LLMEngine 基于 PortableDB，纯 stdlib（difflib 文本相似度 + 关键词匹配）：
  * 法规变更检测：标题相似度匹配旧版（>=0.5），内容差异分析
  * 口径差异：按中文编号拆分条款，逐段比对（相似度 < 0.8 视为变更）
  * 影响评估：关键术语命中 → impact_score（每词 0.15，上限 1.0）→ high/medium/low
  * 紧急度：high_impact > 5 → 紧急 / high > 0 或 medium > 5 → 尽快 / 否则 正常
每个测试用 tmp_path 隔离 db，Windows 下结束前 eng.close()。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.fi_05.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(tmp_path, **overrides) -> LLMEngine:
    eng = LLMEngine(config={
        "db_path": str(tmp_path / "fi_05_engine.db"),
        **overrides,
    })
    eng.setup()
    return eng


def _close(eng: LLMEngine) -> None:
    if eng.db is not None:
        eng.db.close()
        eng.db = None


def _reg(**fields) -> dict:
    base = {
        "reg_id": "R1",
        "title": "测试法规",
        "content": "一、会计政策：企业应当采用合理的会计政策进行确认和计量。",
        "issued_date": "2025-01-01",
    }
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 变更检测 / 法规分类
# ----------------------------------------------------------------------
def test_new_regulation_detected(tmp_path):
    """无匹配旧版的法规标记为「新增法规」。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "new_regulations": [_reg(title="全新法规")],
            "current_regulations": [],
        })
        assert result["changes"][0]["change_type"] == "新增法规"
        assert result["changes"][0]["has_changes"] is True
    finally:
        _close(eng)


def test_revised_regulation_detected(tmp_path):
    """标题匹配旧版（相似度 >= 0.5）的法规标记为「修订」。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        by_id = {c["reg_id"]: c for c in result["changes"]}
        assert by_id["REG001"]["change_type"] == "修订"
        assert by_id["REG002"]["change_type"] == "新增法规"
    finally:
        _close(eng)


def test_changes_count_matches_new_regulations(tmp_path):
    """变更数量 = 新法规数量。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert len(result["changes"]) == 2
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 条款拆分 / 差异分析
# ----------------------------------------------------------------------
def test_sections_split_by_chinese_numbering(tmp_path):
    """按中文编号（一、二、三）拆分条款，每段 > 20 字。"""
    eng = _make_engine(tmp_path)
    try:
        sections = eng._split_sections(
            "一、会计政策：企业应当采用合理的会计政策进行确认和计量。\n"
            "二、计量方法：企业应当采用法定货币进行计量并考虑可变对价的影响。"
        )
        assert len(sections) == 2
        for s in sections:
            assert len(s) > 20
    finally:
        _close(eng)


def test_changed_sections_below_similarity_threshold(tmp_path):
    """修订法规中相似度 < 0.8 的条款被标记为变更段落。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        by_id = {c["reg_id"]: c for c in result["changes"]}
        reg001 = by_id["REG001"]
        # 修订法规有变更段落
        assert len(reg001["sections_changed"]) >= 1
        for sc in reg001["sections_changed"]:
            assert "section_text" in sc
            assert "impact_level" in sc
            assert "impact_score" in sc
            assert "impact_terms" in sc
            assert "similarity_to_old" in sc
    finally:
        _close(eng)


def test_new_regulation_all_sections_marked_new(tmp_path):
    """新增法规的变更段落 is_new=True。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "new_regulations": [_reg(
                title="全新法规",
                content="一、收入确认：企业应当根据收入确认条件确认收入和会计政策。\n"
                        "二、减值测试：企业应当对金融资产进行减值测试。",
            )],
            "current_regulations": [],
        })
        for sc in result["changes"][0]["sections_changed"]:
            assert sc["is_new"] is True
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 影响评估
# ----------------------------------------------------------------------
def test_impact_level_by_key_term_count(tmp_path):
    """关键术语命中数 → impact_score（每词 0.15）→ high/medium/low。"""
    eng = _make_engine(tmp_path)
    try:
        # 5 个关键术语 → 0.75 → high
        text_high = "会计准则 会计政策 计量方法 确认条件 披露要求"
        level, score, terms = eng._assess_impact(text_high)
        assert level == "high"
        assert score == 0.75
        assert len(terms) == 5

        # 2 个关键术语 → 0.30 → low
        text_low = "收入确认 合并范围"
        level, score, terms = eng._assess_impact(text_low)
        assert level == "low"
        assert score == 0.30
    finally:
        _close(eng)


def test_impact_score_capped_at_one(tmp_path):
    """impact_score 上限为 1.0。"""
    eng = _make_engine(tmp_path)
    try:
        # 8 个关键术语 → 1.2 → 截断为 1.0
        text = "会计准则 会计政策 计量方法 确认条件 披露要求 收入确认 金融资产 减值测试"
        _, score, _ = eng._assess_impact(text)
        assert score == 1.0
    finally:
        _close(eng)


def test_no_key_terms_returns_low(tmp_path):
    """无关键术语 → low / score=0。"""
    eng = _make_engine(tmp_path)
    try:
        level, score, terms = eng._assess_impact("这是一段普通文本不含关键术语")
        assert level == "low"
        assert score == 0.0
        assert terms == []
    finally:
        _close(eng)


def test_impact_terms_collected(tmp_path):
    """命中的关键术语被收集到 impact_terms。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        for c in result["changes"]:
            for sc in c["sections_changed"]:
                for term in sc["impact_terms"]:
                    assert term in eng.model["key_terms"]
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 汇总统计 / 紧急度
# ----------------------------------------------------------------------
def test_summary_structure(tmp_path):
    """summary 含法规数 / 变更段落数 / 高/中影响段落 / 有变更的法规数。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        s = result["summary"]
        assert s["regulation_count"] == 2
        assert "total_sections_changed" in s
        assert "high_impact_sections" in s
        assert "medium_impact_sections" in s
        assert "regulations_with_changes" in s
    finally:
        _close(eng)


def test_urgency_in_summary(tmp_path):
    """summary.urgency 由后处理添加（紧急/尽快/正常）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute(_sample())
        assert result["summary"]["urgency"] in ("紧急", "尽快", "正常")
    finally:
        _close(eng)


def test_urgency_normal_for_low_impact(tmp_path):
    """无高影响段落且中影响 <= 5 → 紧急度=正常。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "new_regulations": [_reg(
                title="低影响法规",
                content="一、一般性说明：本法规为一般性说明文档，不涉及重大变更。",
            )],
            "current_regulations": [],
        })
        assert result["summary"]["urgency"] == "正常"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 边界 / 异常输入
# ----------------------------------------------------------------------
def test_empty_regulations(tmp_path):
    """空法规列表返回零汇总。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({"new_regulations": [], "current_regulations": []})
        assert result["changes"] == []
        assert result["summary"]["regulation_count"] == 0
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


def test_reg_id_auto_generated_if_missing(tmp_path):
    """无 reg_id 时自动用 content 的 md5 生成。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "new_regulations": [{"title": "无ID法规", "content": "一、会计政策：这是一段测试用的法规内容用于验证。"}],
            "current_regulations": [],
        })
        assert len(result["changes"][0]["reg_id"]) > 0
    finally:
        _close(eng)


def test_missing_content_defaults_empty(tmp_path):
    """缺少 content 字段时默认空字符串（不崩）。"""
    eng = _make_engine(tmp_path)
    try:
        result = eng.execute({
            "new_regulations": [{"reg_id": "X1", "title": "空法规"}],
            "current_regulations": [],
        })
        assert result["changes"][0]["reg_id"] == "X1"
    finally:
        _close(eng)


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_has_key_terms_and_thresholds(tmp_path):
    """model 含关键术语 / 影响因子 / 相似度阈值。"""
    eng = _make_engine(tmp_path)
    try:
        assert len(eng.model["key_terms"]) == 14
        assert eng.model["impact_factors"]["high"] == 0.9
        assert eng.model["similarity_threshold"] == 0.8
    finally:
        _close(eng)


def test_lazy_load_on_execute(tmp_path):
    """不调 setup() 直接 execute 也能懒加载模型。"""
    eng = LLMEngine(config={"db_path": str(tmp_path / "fi_05_lazy.db")})
    assert eng.model is None
    try:
        result = eng.execute({"new_regulations": [], "current_regulations": []})
        assert eng.model is not None
        assert result["summary"]["regulation_count"] == 0
    finally:
        _close(eng)
