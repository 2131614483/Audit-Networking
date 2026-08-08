"""[FA-02] pipeline 端到端单测：Pipeline.run() 全流程跑通。"""
from __future__ import annotations

import json
from pathlib import Path

from modules.fa_02.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).parent / "fixtures"


def _make_pipeline(tmp_path) -> Pipeline:
    """构造隔离 db 的 pipeline。"""
    return Pipeline(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(tmp_path / "fa_02_pipeline.db"),
    })


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_mock_input(tmp_path):
    """用 fixtures/mock_input.json 端到端跑通，输出结构含 standardized_fields + statistics。"""
    pipe = _make_pipeline(tmp_path)
    mock_input = json.loads((_FIXTURES / "mock_input.json").read_text(encoding="utf-8"))
    output = pipe.run(mock_input)

    assert output["status"] == "ok"
    assert "standardized_fields" in output
    assert "statistics" in output

    stats = output["statistics"]
    assert stats["total"] == len(mock_input["fields"])
    assert stats["mapped"] + stats["unmapped"] == stats["total"]
    # mock_input 中 "Pending Settlement XYZQQ" 是未映射字段
    assert stats["unmapped"] >= 1
    assert stats["need_review"] >= 1


def test_pipeline_known_fields_auto_mapped(tmp_path):
    """已知字段全部自动映射到正确标准名，tier=auto。"""
    pipe = _make_pipeline(tmp_path)
    output = pipe.run({
        "source": "ERP-A",
        "fields": [
            {"raw_name": "应收账款", "value": 1},
            {"raw_name": "A/R", "value": 1},
            {"raw_name": "Accounts Receivable", "value": 1},
        ],
    })
    for f in output["standardized_fields"]:
        assert f["standard_name"] == "accounts_receivable"
        assert f["confidence"] == 1.0
        assert f["tier"] == "auto"
        assert f["need_review"] is False
        assert f["subject_code"] == "1122"


def test_pipeline_unmapped_field_marked(tmp_path):
    """未映射字段标记 unmapped + tier=manual，standard_name 回退为 raw_name。"""
    pipe = _make_pipeline(tmp_path)
    output = pipe.run({
        "fields": [{"raw_name": "Pending Settlement XYZQQ", "value": 1}],
    })
    f = output["standardized_fields"][0]
    assert f["unmapped"] is True
    assert f["tier"] == "manual"
    assert f["need_review"] is True
    # custom_rules：未映射时 standard_name 回退为 raw_name
    assert f["standard_name"] == "Pending Settlement XYZQQ"
    assert output["statistics"]["unmapped"] == 1


def test_pipeline_near_name_review_tier(tmp_path):
    """近似名匹配：tier=review（0.6 ≤ confidence < 0.85）。

    "应收款项" vs "应收账款" 相似度 0.75，落在 review 区间。
    """
    pipe = _make_pipeline(tmp_path)
    output = pipe.run({
        "fields": [{"raw_name": "应收款项", "value": 1}],
    })
    f = output["standardized_fields"][0]
    assert f["standard_name"] == "accounts_receivable"
    assert 0.6 <= f["confidence"] < 0.85
    assert f["tier"] == "review"
    assert f["need_review"] is True


# ----------------------------------------------------------------------
# PortableDB 持久化
# ----------------------------------------------------------------------
def test_pipeline_persists_results_to_db(tmp_path):
    """Pipeline 把标准化结果持久化到 PortableDB standardization_results 表。"""
    db_path = tmp_path / "fa_02_pipeline.db"
    pipe = Pipeline(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(db_path),
    })
    pipe.run({"fields": [
        {"raw_name": "应收账款", "value": 1},
        {"raw_name": "Pending Settlement XYZQQ", "value": 2},
    ]})

    # 用新连接读取，验证落盘
    with PortableDB(db_path) as db:
        rows = db.all("standardization_results")
    assert len(rows) == 2
    raw_names = {r["raw_name"] for r in rows}
    assert "应收账款" in raw_names
    assert "Pending Settlement XYZQQ" in raw_names
    # payload 字段是 JSON 软类型，应自动反序列化为 dict
    for r in rows:
        assert isinstance(r["payload"], dict)
        assert "top3_candidates" in r["payload"]


def test_pipeline_db_has_seed_tables(tmp_path):
    """Pipeline 初始化后 PortableDB 含 field_mappings / subject_codes / increment_learnings 表。"""
    db_path = tmp_path / "fa_02_pipeline.db"
    pipe = Pipeline(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(db_path),
    })
    with PortableDB(db_path) as db:
        tables = set(db.tables())
    assert "field_mappings" in tables
    assert "subject_codes" in tables
    assert "increment_learnings" in tables
    assert "standardization_results" in tables
    # 种子数据已导入
    assert pipe.engine.db.count("field_mappings") >= 20
    assert pipe.engine.db.count("subject_codes") >= 15


# ----------------------------------------------------------------------
# 增量学习（Pipeline 内的 engine）
# ----------------------------------------------------------------------
def test_pipeline_incremental_learning(tmp_path):
    """Pipeline 内的 engine 支持增量学习，确认后下次 run 映射生效。"""
    pipe = _make_pipeline(tmp_path)

    # 学习前：未映射
    out1 = pipe.run({"fields": [{"raw_name": "递延收益", "value": 1}]})
    assert out1["standardized_fields"][0]["unmapped"] is True

    # 人工确认
    pipe.engine.learn("递延收益", "deferred_income", subject_code="2401")

    # 学习后：精确命中
    out2 = pipe.run({"fields": [{"raw_name": "递延收益", "value": 1}]})
    f = out2["standardized_fields"][0]
    assert f["standard_name"] == "deferred_income"
    assert f["confidence"] == 1.0
    assert f["subject_code"] == "2401"
    assert f["tier"] == "auto"
