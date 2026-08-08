"""[SC-05] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

pytest 风格：每个测试用 tmp_path 隔离 PortableDB，pipe fixture 在收尾时关闭
engine.db 句柄，避免 Windows 下 tmp_path 清理触发 PermissionError。
可复现性测试显式创建并关闭两个独立 pipeline。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.sc_05.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _expected() -> dict:
    return json.loads((_FIXTURES / "expected_output.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    config = {
        "threshold": {"acceptable_pct": 10.0, "marginal_pct": 25.0},
        "db_path": str(tmp_path / "sc_05_pipeline.db"),
    }
    config.update(overrides)
    return Pipeline(config=config)


@pytest.fixture
def pipe(tmp_path):
    """构造隔离 db 的 pipeline，收尾关闭 engine.db 句柄。"""
    p = _make_pipeline(tmp_path)
    yield p
    p.engine.close()


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample(pipe):
    """用 sample_input.json 端到端跑通，输出含品类基准 + 对标 + 趋势 + 建议。"""
    output = pipe.run(_sample())

    assert output["status"] == "ok"
    assert output["module"] == "SC-05"
    for key in ("category_benchmarks", "price_comparisons",
                "trend_analysis", "recommendations", "statistics"):
        assert key in output


def test_pipeline_statistics_complete(pipe):
    """统计含品类数/查询数/分级分布，各级之和 = 查询数。"""
    sample = _sample()
    output = pipe.run(sample)

    stats = output["statistics"]
    assert stats["category_count"] == 3
    assert stats["query_count"] == len(sample["benchmark_queries"])
    dist = stats["grade_distribution"]
    for lv in ("acceptable", "marginal", "expensive", "no_data"):
        assert lv in dist
    assert (dist["acceptable"] + dist["marginal"]
            + dist["expensive"] + dist["no_data"] == stats["query_count"])


def test_pipeline_detects_high_prices(pipe):
    """sample 含高价查询 → 对标结果含偏高标记（B-0001 钢材 6500）。"""
    output = pipe.run(_sample())

    by_id = {c["benchmark_id"]: c for c in output["price_comparisons"]}
    assert by_id["B-0001"]["position"] == "偏高"
    assert by_id["B-0001"]["deviation_pct"] > 25
    assert by_id["B-0001"]["grade"] == "expensive"


def test_pipeline_matches_expected_output(pipe):
    """pipeline 输出与 expected_output.json 关键字段一致。"""
    output = pipe.run(_sample())
    expected = _expected()

    assert output["status"] == expected["status"]
    assert output["module"] == expected["module"]
    assert (output["statistics"]["category_count"]
            == expected["statistics"]["category_count"])
    assert (output["statistics"]["query_count"]
            == expected["statistics"]["query_count"])
    assert (output["statistics"]["grade_distribution"]
            == expected["statistics"]["grade_distribution"])
    assert len(output["category_benchmarks"]) == len(expected["category_benchmarks"])
    assert len(output["price_comparisons"]) == len(expected["price_comparisons"])


def test_pipeline_custom_rules_applied(pipe):
    """业务规则：P90偏贵 / 下降趋势议价 / 数据缺口告警 三类标记生效。"""
    output = pipe.run(_sample())

    by_id = {c["benchmark_id"]: c for c in output["price_comparisons"]}
    # 规则2：B-0001(6500)高于钢材P90 → expensive_p90
    assert by_id["B-0001"]["expensive_p90"] is True
    # 规则3：电缆历史价下降 → B-0004 标记 renegotiate_opportunity
    assert by_id["B-0004"]["renegotiate_opportunity"] is True
    # 规则1：木材无基准导致覆盖率<60% → data_gap_alert
    assert output["statistics"]["data_gap_alert"] is True
    assert output["statistics"]["benchmark_coverage"] < 0.60
    # rule_flags 计数
    assert output["statistics"]["rule_flags"]["expensive_p90"] > 0
    assert output["statistics"]["rule_flags"]["renegotiate_opportunity"] > 0
    # 建议非空
    assert len(output["recommendations"]) > 0


# ----------------------------------------------------------------------
# 配置透传
# ----------------------------------------------------------------------
def test_pipeline_config_threshold_propagates(tmp_path):
    """Pipeline config 中的 threshold 透传到 apply_thresholds（统计 thresholds 反映）。"""
    pipe = _make_pipeline(
        tmp_path,
        threshold={"acceptable_pct": 15.0, "marginal_pct": 30.0},
    )
    try:
        output = pipe.run(_sample())
    finally:
        pipe.engine.close()

    thresholds = output["statistics"]["thresholds"]
    assert thresholds["acceptable_pct"] == 15.0
    assert thresholds["marginal_pct"] == 30.0


# ----------------------------------------------------------------------
# PortableDB 持久化
# ----------------------------------------------------------------------
def test_pipeline_persists_to_portable_db(tmp_path):
    """Pipeline 把历史价/品类基准/对标结果持久化到 PortableDB。"""
    db_path = tmp_path / "sc_05_pipeline.db"
    pipe = _make_pipeline(tmp_path)
    sample = _sample()
    try:
        pipe.run(sample)
    finally:
        pipe.engine.close()  # 释放 db 句柄后再以只读方式打开校验

    with PortableDB(db_path) as db:
        tables = set(db.tables())
        assert "price_histories" in tables
        assert "category_baselines" in tables
        assert "benchmark_results" in tables
        # 历史价全量写入（23 条，过滤掉非正价/非法价）
        assert db.count("price_histories") == len(sample["price_history"])
        # 品类基准：≥5 条历史价的 3 个品类（钢材/水泥/电缆），不含木材
        bl_rows = db.all("category_baselines")
        bl_cats = {r["category"] for r in bl_rows}
        assert len(bl_rows) == 3
        assert {"钢材", "水泥", "电缆"} == bl_cats
        assert "木材" not in bl_cats
        # JSON 软类型字段自动反序列化
        for r in bl_rows:
            assert isinstance(r["percentiles"], dict)
        # 对标结果全量写入（7 条查询）
        assert db.count("benchmark_results") == len(sample["benchmark_queries"])


# ----------------------------------------------------------------------
# 可复现性
# ----------------------------------------------------------------------
def test_pipeline_reproducible_same_input(tmp_path):
    """相同输入 → 两个独立 pipeline 产出相同的分级分布/基准数/对标数。"""
    sample = _sample()

    run1_dir = tmp_path / "run1"
    run2_dir = tmp_path / "run2"
    run1_dir.mkdir()
    run2_dir.mkdir()
    pipe1 = _make_pipeline(run1_dir)
    pipe2 = _make_pipeline(run2_dir)
    try:
        out1 = pipe1.run(sample)
        out2 = pipe2.run(sample)
    finally:
        pipe1.engine.close()
        pipe2.engine.close()

    assert (out1["statistics"]["grade_distribution"]
            == out2["statistics"]["grade_distribution"])
    assert len(out1["category_benchmarks"]) == len(out2["category_benchmarks"])
    assert len(out1["price_comparisons"]) == len(out2["price_comparisons"])


# ----------------------------------------------------------------------
# 空输入
# ----------------------------------------------------------------------
def test_pipeline_empty_input(pipe):
    """空输入 → status ok、category_count=0、query_count=0、无对标结果。"""
    output = pipe.run({"price_history": [], "benchmark_queries": []})
    assert output["status"] == "ok"
    assert output["statistics"]["category_count"] == 0
    assert output["statistics"]["query_count"] == 0
    assert output["price_comparisons"] == []
    assert output["category_benchmarks"] == []
