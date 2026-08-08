"""[FA-02] engine 单测：多策略匹配 / 置信度 / Top-3 / 科目标准化 / 增量学习。

每个测试用独立 tmp_path 隔离 PortableDB，避免增量学习互相污染。
"""
from __future__ import annotations

import pytest

from modules.fa_02.engine import MLEngine, _clean


def _make_engine(tmp_path, threshold: float = 0.85) -> MLEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    eng = MLEngine(config={
        "threshold": {"confidence": threshold},
        "db_path": str(tmp_path / "fa_02_engine.db"),
    })
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 策略 ① 精确同义词命中
# ----------------------------------------------------------------------
def test_exact_synonym_match(tmp_path):
    """精确同义词命中置信度为 1.0，并附带正确科目代码。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "source": "ERP-A",
        "fields": [
            {"raw_name": "应收账款", "value": 100},
            {"raw_name": "A/R", "value": 200},
            {"raw_name": "Accounts Receivable", "value": 300},
        ],
    })
    for f in result["fields"]:
        assert f["best_match"] == "accounts_receivable"
        assert f["confidence"] == 1.0
        assert f["subject_code"] == "1122"
        assert f["unmapped"] is False


def test_exact_match_across_sources(tmp_path):
    """多源同义字段（中英文/缩写）都映射到同一标准字段。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [
            {"raw_name": "营业收入", "value": 1},
            {"raw_name": "Revenue", "value": 1},
            {"raw_name": "主营业务收入", "value": 1},
            {"raw_name": "Sales Revenue", "value": 1},
        ],
    })
    stds = {f["raw_name"]: f["best_match"] for f in result["fields"]}
    assert all(v == "revenue" for v in stds.values())
    codes = {f["raw_name"]: f["subject_code"] for f in result["fields"]}
    assert all(v == "6001" for v in codes.values())


# ----------------------------------------------------------------------
# 策略 ② 字符相似度匹配
# ----------------------------------------------------------------------
def test_similarity_match_for_near_name(tmp_path):
    """近似名通过字符相似度匹配，置信度介于 0.6 和 0.85 之间（review 区间）。

    "应收款项" vs "应收账款"：SequenceMatcher 匹配 "应收"+"款"=3，ratio=2*3/(4+4)=0.75
    """
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [{"raw_name": "应收款项", "value": 100}],
    })
    f = result["fields"][0]
    assert f["best_match"] == "accounts_receivable"
    assert 0.6 < f["confidence"] < 0.85
    assert f["subject_code"] == "1122"
    assert f["need_review"] is True  # 低于 0.85 阈值


# ----------------------------------------------------------------------
# Top-3 候选
# ----------------------------------------------------------------------
def test_top3_candidates_sorted(tmp_path):
    """Top-3 候选按置信度降序排列，且首个为最佳匹配。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [{"raw_name": "应收账款", "value": 1}],
    })
    f = result["fields"][0]
    assert 1 <= len(f["top3_candidates"]) <= 3
    assert f["top3_candidates"][0]["standard_name"] == "accounts_receivable"
    confs = [c["confidence"] for c in f["top3_candidates"]]
    assert confs == sorted(confs, reverse=True)


def test_top3_candidates_for_near_name(tmp_path):
    """近似名的 Top-3 候选都来自已知标准字段，且按分数降序。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [{"raw_name": "Receivable", "value": 1}],
    })
    f = result["fields"][0]
    assert len(f["top3_candidates"]) >= 1
    confs = [c["confidence"] for c in f["top3_candidates"]]
    assert confs == sorted(confs, reverse=True)
    # 所有候选都应是已知标准字段名
    known_stds = set(eng.model["raw_to_std"].values())
    for c in f["top3_candidates"]:
        assert c["standard_name"] in known_stds


# ----------------------------------------------------------------------
# 未映射字段
# ----------------------------------------------------------------------
def test_unmapped_field(tmp_path):
    """真正未映射字段：best_match=None, unmapped=True, need_review=True。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [{"raw_name": "Pending Settlement XYZQQ", "value": 1}],
    })
    f = result["fields"][0]
    assert f["best_match"] is None
    assert f["unmapped"] is True
    assert f["subject_code"] is None
    assert f["need_review"] is True
    assert f["confidence"] == 0.0


# ----------------------------------------------------------------------
# 科目代码标准化
# ----------------------------------------------------------------------
def test_subject_code_standardization(tmp_path):
    """科目代码标准化到统一科目表（应收/应付/固定资产/营收/存货）。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [
            {"raw_name": "应收账款", "value": 1},
            {"raw_name": "应付账款", "value": 1},
            {"raw_name": "固定资产", "value": 1},
            {"raw_name": "营业收入", "value": 1},
            {"raw_name": "存货", "value": 1},
        ],
    })
    codes = {f["raw_name"]: f["subject_code"] for f in result["fields"]}
    assert codes["应收账款"] == "1122"
    assert codes["应付账款"] == "2202"
    assert codes["固定资产"] == "1601"
    assert codes["营业收入"] == "6001"
    assert codes["存货"] == "1241"


def test_subject_meta_attached(tmp_path):
    """科目元信息（subject_name / category）随科目代码附带。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({"fields": [{"raw_name": "固定资产", "value": 1}]})
    f = result["fields"][0]
    assert f["subject_code"] == "1601"
    assert f["subject_meta"]["subject_name"] == "固定资产"
    assert f["subject_meta"]["category"] == "asset_noncurrent"


# ----------------------------------------------------------------------
# 阈值标记
# ----------------------------------------------------------------------
def test_threshold_marking(tmp_path):
    """高置信度不需复核，低置信度需复核。"""
    eng = _make_engine(tmp_path, threshold=0.85)
    result = eng.execute({
        "fields": [
            {"raw_name": "应收账款", "value": 1},                    # 1.0 → 不复核
            {"raw_name": "应收款项", "value": 1},                    # 相似度 0.75 → 复核
            {"raw_name": "Pending Settlement XYZQQ", "value": 1},   # 未映射 → 复核
        ],
    })
    by_name = {f["raw_name"]: f for f in result["fields"]}
    assert by_name["应收账款"]["need_review"] is False
    assert by_name["应收款项"]["need_review"] is True
    assert by_name["Pending Settlement XYZQQ"]["need_review"] is True


# ----------------------------------------------------------------------
# 增量学习
# ----------------------------------------------------------------------
def test_incremental_learning_immediate(tmp_path):
    """增量学习：learn 后再 execute，新映射立即在当前实例生效。

    选用 "待处理财产损溢" 作为种子：该词与 fixtures 中所有已知 raw 名
    最大字符相似度仅 0.18（< _MIN_SIMILARITY 0.4），确保 learn 前为未映射。
    """
    eng = _make_engine(tmp_path)
    r1 = eng.execute({"fields": [{"raw_name": "待处理财产损溢", "value": 1}]})
    assert r1["fields"][0]["best_match"] is None

    eng.learn("待处理财产损溢", "pending_property_loss_or_gain", subject_code="1901")

    r2 = eng.execute({"fields": [{"raw_name": "待处理财产损溢", "value": 1}]})
    f = r2["fields"][0]
    assert f["best_match"] == "pending_property_loss_or_gain"
    assert f["confidence"] == 1.0
    assert f["subject_code"] == "1901"
    assert f["unmapped"] is False


def test_incremental_learning_persisted_across_engines(tmp_path):
    """增量学习写入 PortableDB，新 engine 实例 _load_model 时自动合并。"""
    db_path = tmp_path / "fa_02_persist.db"
    eng1 = MLEngine(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(db_path),
    })
    eng1.setup()
    eng1.learn("研发支出", "rd_expenses", subject_code="6602")

    # 新实例加载同一个 db
    eng2 = MLEngine(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(db_path),
    })
    eng2.setup()
    r = eng2.execute({"fields": [{"raw_name": "研发支出", "value": 1}]})
    f = r["fields"][0]
    assert f["best_match"] == "rd_expenses"
    assert f["confidence"] == 1.0
    assert f["subject_code"] == "6602"


def test_incremental_learning_overrides_fixture(tmp_path):
    """增量学习优先级最高：覆盖 fixtures 中的同名映射。"""
    eng = _make_engine(tmp_path)
    # fixtures 中 "应收账款" → accounts_receivable (1122)
    # 人工纠正为 other_receivables (1221)
    eng.learn("应收账款", "other_receivables", subject_code="1221")
    r = eng.execute({"fields": [{"raw_name": "应收账款", "value": 1}]})
    f = r["fields"][0]
    assert f["best_match"] == "other_receivables"
    assert f["subject_code"] == "1221"


# ----------------------------------------------------------------------
# 字段清洗
# ----------------------------------------------------------------------
def test_cleaning_normalizes_input(tmp_path):
    """清洗：去首尾空格、统一小写、去标点（"/" 也会被去掉，A/R → ar）。"""
    assert _clean("  A/R !! ") == "ar"  # "/" 和 "!" 都是标点，被去掉
    assert _clean("Accounts Receivable") == "accounts receivable"
    assert _clean("应收账款") == "应收账款"


def test_cleaning_enables_match(tmp_path):
    """清洗后能匹配到同义词（带空格/标点的输入）。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({
        "fields": [{"raw_name": "  A/R !! ", "value": 1}],
    })
    f = result["fields"][0]
    assert f["cleaned"] == "ar"
    assert f["best_match"] == "accounts_receivable"
    assert f["confidence"] == 1.0


# ----------------------------------------------------------------------
# 空输入 / 异常输入
# ----------------------------------------------------------------------
def test_empty_fields(tmp_path):
    """空字段列表返回空结果。"""
    eng = _make_engine(tmp_path)
    result = eng.execute({"fields": []})
    assert result["fields"] == []


def test_invalid_input_raises(tmp_path):
    """非 dict 输入抛 ValueError。"""
    eng = _make_engine(tmp_path)
    with pytest.raises(ValueError):
        eng.execute(["not", "a", "dict"])
