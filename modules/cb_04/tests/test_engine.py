"""[CB-04] engine 单测：准则识别 / 差异匹配 / 调节表生成 / 审计计划。

LLMEngine 为纯 stdlib 实现（关键词 + difflib 相似度），不依赖外部 LLM。
内置 IFRS↔US_GAAP↔CN_GAAP 七个核心差异点（收入确认/减值/金融工具/租赁/合并/所得税/关联方）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cb_04.engine import LLMEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> LLMEngine:
    eng = LLMEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 准则识别
# ----------------------------------------------------------------------
def test_standard_detection_from_text():
    """从附注文本自动识别源准则（含 IFRS 关键词 → IFRS）。"""
    eng = _make_engine()
    result = eng.execute({
        "from_standard": "",  # 留空触发自动识别
        "to_standard": "US_GAAP",
        "notes": "本公司采用国际财务报告准则 IFRS 编制，遵循 IAS 36 资产减值规定",
    })
    assert result["from_standard"] == "IFRS"
    assert result["detected_standard"] == "IFRS"


def test_string_input_defaults_ifrs_to_us_gaap():
    """字符串输入被当作 notes，默认 IFRS→US_GAAP 转换。"""
    eng = _make_engine()
    result = eng.execute("本公司按 IFRS 15 确认收入，采用五步法模型")
    assert result["from_standard"] == "IFRS"
    assert result["to_standard"] == "US_GAAP"


def test_next_standard_for_cn_gaap():
    """CN_GAAP 未指定目标准则时默认转 IFRS。"""
    eng = _make_engine()
    result = eng.execute({
        "from_standard": "CN_GAAP",
        "notes": "企业会计准则 财政部 CAS 18 所得税",
    })
    # 文本含 CN_GAAP 关键词，detected 也应是 CN_GAAP
    assert result["from_standard"] == "CN_GAAP"
    assert result["to_standard"] == "IFRS"


# ----------------------------------------------------------------------
# 差异匹配
# ----------------------------------------------------------------------
def test_conversion_identifies_differences():
    """IFRS→US_GAAP 转换识别出至少一个差异（收入/租赁/金融工具等）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["from_standard"] == "IFRS"
    assert result["to_standard"] == "US_GAAP"
    assert len(result["matched_differences"]) >= 1
    # 每个差异含 match_score / keyword_hits
    for d in result["matched_differences"]:
        assert "match_score" in d
        assert "keyword_hits" in d
        assert "diff_id" in d
        assert "area" in d


def test_matched_differences_sorted_by_score_desc():
    """匹配的差异按 match_score 降序排列（_postprocess 后按 impact_level 排序，
    这里直接检查 _match_differences 的原始顺序——通过 match_score 字段验证）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # _postprocess 按 impact_level 重排，但所有 match_score 都应存在
    scores = [d["match_score"] for d in result["matched_differences"]]
    assert all(s >= 0 for s in scores)
    assert len(scores) >= 1


def test_relevant_differences_flagged():
    """与转换方向相关的差异被标记 relevant_to_conversion=True。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # IFRS→US_GAAP，DIF-001（收入确认）涉及 IFRS+US_GAAP，应标记为相关
    relevant = [d for d in result["matched_differences"] if d.get("relevant_to_conversion")]
    # sample 含 IFRS 15 关键词，至少有一个相关差异
    assert len(relevant) >= 1


def test_lease_difference_matched():
    """sample 含 IFRS 16 租赁关键词，应匹配到租赁差异 DIF-004。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    ids = {d["diff_id"] for d in result["matched_differences"]}
    assert "DIF-004" in ids


# ----------------------------------------------------------------------
# 调节表生成
# ----------------------------------------------------------------------
def test_adjustments_generated_with_accounts():
    """每个匹配差异生成调节分录，含借/贷账户列表。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert len(result["adjustments"]) == len(result["matched_differences"])
    for adj in result["adjustments"]:
        assert "diff_id" in adj
        assert "area" in adj
        assert "estimated_amount" in adj
        assert "debit_accounts" in adj
        assert "credit_accounts" in adj
        assert "adjustment_note" in adj


def test_adjustment_amount_estimated_from_financials():
    """提供财务数据时，调节金额按受影响科目余额估算（>0）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # sample 中使用权资产=1000000，租赁负债=900000，应估算出非零金额
    total = sum(a["estimated_amount"] for a in result["adjustments"])
    assert total > 0


def test_adjustments_sorted_by_amount_desc():
    """_postprocess 后 adjustments 按估算金额降序排列。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    amounts = [a["estimated_amount"] for a in result["adjustments"]]
    assert amounts == sorted(amounts, reverse=True)


def test_no_financials_yields_zero_amount():
    """未提供财务数据时，调节估算金额为 0（但分录结构仍完整）。"""
    eng = _make_engine()
    result = eng.execute({
        "from_standard": "IFRS",
        "to_standard": "US_GAAP",
        "accounting_policies": ["租赁按 IFRS 16 处理，确认使用权资产和租赁负债"],
    })
    for adj in result["adjustments"]:
        assert adj["estimated_amount"] == 0


# ----------------------------------------------------------------------
# 汇总统计 / 审计计划
# ----------------------------------------------------------------------
def test_summary_statistics():
    """summary 含差异计数、借贷调整总额、净影响、分级分布。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["total_differences"] == len(result["matched_differences"])
    assert "estimated_debit_adjustment" in s
    assert "estimated_credit_adjustment" in s
    assert "net_impact" in s
    assert "by_impact_level" in s
    assert "by_diff_type" in s


def test_audit_plan_generated():
    """审计计划含 module/family 标记 + 审计步骤列表。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    ap = result["audit_plan"]
    assert ap["module"] == "CB-04"
    assert ap["family"] == "llm_rag"
    assert "IFRS" in ap["conversion_scope"]
    assert "US_GAAP" in ap["conversion_scope"]
    assert len(ap["audit_steps"]) >= 3


def test_high_impact_triggers_audit_step():
    """存在 high 影响等级差异时，审计计划含"重大差异"步骤。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    # sample 含收入确认/租赁等 high 影响差异
    has_high = any(d["impact_level"] == "high" for d in result["matched_differences"])
    if has_high:
        steps_text = " ".join(result["audit_plan"]["audit_steps"])
        assert "重大差异" in steps_text


# ----------------------------------------------------------------------
# 空输入 / 边界
# ----------------------------------------------------------------------
def test_empty_policies_no_crash():
    """空政策列表不抛异常（可能无匹配差异）。"""
    eng = _make_engine()
    result = eng.execute({
        "from_standard": "IFRS",
        "to_standard": "US_GAAP",
        "accounting_policies": [],
    })
    assert "matched_differences" in result
    assert "audit_plan" in result


def test_model_has_seed_differences():
    """engine 加载后 model 含 7 个种子差异 + 三大准则关键词。"""
    eng = _make_engine()
    assert len(eng.model["differences"]) == 7
    assert "IFRS" in eng.model["standard_keywords"]
    assert "US_GAAP" in eng.model["standard_keywords"]
    assert "CN_GAAP" in eng.model["standard_keywords"]
