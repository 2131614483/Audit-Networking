"""[FI-03] engine 单测：贷款违约预测（逻辑回归 sigmoid + 标准化 + 风险评级）。

MLEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * 特征标准化：(raw - mean) / std
  * 逻辑回归：z = bias + Σ w_i × x_i，prob = sigmoid(z)
  * 风险评级：A(<=0.05) / B(<=0.15) / C(<=0.30) / D(<=0.50) / E(<=1.0)
  * 审批建议：A/B→通过 / C→人工复核 / D/E→拒绝
  * 结果按违约概率降序排列
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from modules.fi_03.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> MLEngine:
    eng = MLEngine(config=overrides)
    eng.setup()
    return eng


def _applicant(**fields) -> dict:
    """构造申请人，补默认字段（所有特征在均值上）。"""
    base = {
        "applicant_id": "T1",
        "name": "测试",
        "credit_score": 680,
        "dti_ratio": 0.35,
        "ltv_ratio": 0.75,
        "employment_years": 8,
        "default_history": 0,
        "loan_amount": 300000,
    }
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 逻辑回归 / 违约概率
# ----------------------------------------------------------------------
def test_default_probability_formula():
    """PD = sigmoid(bias + Σ w_i × standardized_x_i)。"""
    eng = _make_engine()
    # _applicant 默认特征在均值上，但 default_history=0（均值=0.3）→ standardized=-0.375
    result = eng.execute({"applicants": [_applicant()]})
    a = result["applicants"][0]
    # z = bias + w_default_history * ((0 - 0.3) / 0.8)
    expected_z = -1.2 + 1.6 * ((0 - 0.3) / 0.8)
    expected_prob = 1 / (1 + math.exp(-expected_z))
    assert a["logit"] == round(expected_z, 4)
    assert a["default_probability"] == round(expected_prob, 4)


def test_high_credit_score_lower_probability():
    """信用分越高 → 违约概率越低。"""
    eng = _make_engine()
    r_high = eng.execute({"applicants": [_applicant(credit_score=800)]})
    r_low = eng.execute({"applicants": [_applicant(credit_score=550)]})
    assert r_high["applicants"][0]["default_probability"] < r_low["applicants"][0]["default_probability"]


def test_high_dti_ratio_higher_probability():
    """收入负债比越高 → 违约概率越高。"""
    eng = _make_engine()
    r_low = eng.execute({"applicants": [_applicant(dti_ratio=0.2)]})
    r_high = eng.execute({"applicants": [_applicant(dti_ratio=0.55)]})
    assert r_high["applicants"][0]["default_probability"] > r_low["applicants"][0]["default_probability"]


def test_default_history_increases_probability():
    """历史违约次数越多 → 违约概率越高。"""
    eng = _make_engine()
    r_clean = eng.execute({"applicants": [_applicant(default_history=0)]})
    r_default = eng.execute({"applicants": [_applicant(default_history=3)]})
    assert r_default["applicants"][0]["default_probability"] > r_clean["applicants"][0]["default_probability"]


def test_probability_in_range():
    """所有违约概率 ∈ [0, 1]。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["applicants"]:
        assert 0.0 <= a["default_probability"] <= 1.0


# ----------------------------------------------------------------------
# 风险评级 / 审批建议
# ----------------------------------------------------------------------
def test_rating_assignment():
    """四类申请人覆盖 A/B/C/E 评级。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    by_id = {a["applicant_id"]: a for a in result["applicants"]}
    assert by_id["AP001"]["rating"] == "A"   # 优质客户
    assert by_id["AP004"]["rating"] == "B"   # 次优客户
    assert by_id["AP002"]["rating"] == "C"   # 中等客户
    assert by_id["AP003"]["rating"] == "E"   # 高风险客户


def test_decision_corresponds_to_rating():
    """审批建议：A/B→通过 / C→人工复核 / D/E→拒绝。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    by_id = {a["applicant_id"]: a for a in result["applicants"]}
    assert by_id["AP001"]["decision"] == "通过"
    assert by_id["AP004"]["decision"] == "通过"
    assert by_id["AP002"]["decision"] == "人工复核"
    assert by_id["AP003"]["decision"] == "拒绝"


def test_rating_thresholds():
    """评级阈值：A<=0.05 / B<=0.15 / C<=0.30 / D<=0.50 / E<=1.0。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["applicants"]:
        p = a["default_probability"]
        if p <= 0.05:
            assert a["rating"] == "A"
        elif p <= 0.15:
            assert a["rating"] == "B"
        elif p <= 0.30:
            assert a["rating"] == "C"
        elif p <= 0.50:
            assert a["rating"] == "D"
        else:
            assert a["rating"] == "E"


# ----------------------------------------------------------------------
# 结果排序 / 结构
# ----------------------------------------------------------------------
def test_results_sorted_by_probability_desc():
    """结果按违约概率降序排列。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    probs = [a["default_probability"] for a in result["applicants"]]
    assert probs == sorted(probs, reverse=True)


def test_applicant_info_preserved():
    """结果含 applicant_id / name。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    by_id = {a["applicant_id"]: a for a in result["applicants"]}
    assert by_id["AP001"]["name"] == "优质客户"
    assert by_id["AP003"]["name"] == "高风险客户"


def test_features_extracted():
    """features 含模型权重对应的特征（不含 applicant_id）。"""
    eng = _make_engine()
    result = eng.execute({"applicants": [_applicant(credit_score=750, dti_ratio=0.4)]})
    feats = result["applicants"][0]["features"]
    assert "credit_score" in feats
    assert "dti_ratio" in feats
    assert "applicant_id" not in feats
    assert feats["credit_score"] == 750


# ----------------------------------------------------------------------
# 汇总统计
# ----------------------------------------------------------------------
def test_summary_structure():
    """summary 含 total / approved / review / rejected / avg_probability。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["total"] == 4
    assert s["approved"] == 2   # A + B
    assert s["review"] == 1     # C
    assert s["rejected"] == 1   # E
    assert s["approved"] + s["review"] + s["rejected"] == s["total"]


def test_avg_probability():
    """avg_probability = 各申请人违约概率均值。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    probs = [a["default_probability"] for a in result["applicants"]]
    expected = round(sum(probs) / len(probs), 4)
    assert result["summary"]["avg_probability"] == expected


# ----------------------------------------------------------------------
# 输入形态 / 边界
# ----------------------------------------------------------------------
def test_list_input_accepted():
    """直接传 list 输入（无 applicants 包裹）也能处理。"""
    eng = _make_engine()
    result = eng.execute([_applicant(applicant_id="L1", credit_score=800)])
    assert len(result["applicants"]) == 1
    assert result["applicants"][0]["applicant_id"] == "L1"


def test_empty_applicants():
    """空 applicants 返回空结果 + 零汇总。"""
    eng = _make_engine()
    result = eng.execute({"applicants": []})
    assert result["applicants"] == []
    assert result["summary"]["total"] == 0
    assert result["summary"]["avg_probability"] == 0


def test_non_dict_non_list_input_returns_empty():
    """非 dict/list 输入回退为空列表（不崩）。"""
    eng = _make_engine()
    result = eng.execute("invalid input")
    assert result["applicants"] == []
    assert result["summary"]["total"] == 0


def test_missing_features_default_zero():
    """缺少特征字段时默认为 0（标准化后为负值，不崩）。"""
    eng = _make_engine()
    result = eng.execute({"applicants": [{"applicant_id": "M1", "name": "缺字段"}]})
    a = result["applicants"][0]
    assert a["applicant_id"] == "M1"
    assert 0 <= a["default_probability"] <= 1


def test_missing_id_defaults_unknown():
    """无 applicant_id 的申请人默认 '?'。"""
    eng = _make_engine()
    result = eng.execute({"applicants": [_applicant()]})
    # _applicant 有 applicant_id="T1"，去掉后测试默认值
    result2 = eng.execute({"applicants": [{"credit_score": 700, "dti_ratio": 0.3}]})
    assert result2["applicants"][0]["applicant_id"] == "?"


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_has_weights_bias_scaler_ratings():
    """engine 加载后 model 含权重 / 偏置 / 标准化参数 / 评级阈值。"""
    eng = _make_engine()
    assert "weights" in eng.model
    assert "bias" in eng.model
    assert "scaler" in eng.model
    assert "ratings" in eng.model
    assert eng.model["bias"] == -1.2
    assert eng.model["weights"]["credit_score"] == -0.035
    assert len(eng.model["ratings"]) == 5


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 也能懒加载模型。"""
    eng = MLEngine()
    assert eng.model is None
    result = eng.execute({"applicants": [_applicant()]})
    assert eng.model is not None
    assert len(result["applicants"]) == 1
