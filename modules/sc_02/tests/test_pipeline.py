"""[SC-02] pipeline 端到端单测：Pipeline.run() 全流程 + PortableDB 持久化。

pytest 风格：每个测试用 tmp_path 隔离 PortableDB，pipe fixture 在收尾时关闭
engine.db 句柄，避免 Windows 下 tmp_path 清理触发 PermissionError。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.sc_02.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(tmp_path, **overrides) -> Pipeline:
    config = {
        "db_path": str(tmp_path / "sc_02_pipeline.db"),
        "fixtures_dir": str(_FIXTURES),
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
    """用 sample_input.json 端到端跑通，输出含网络 + 风险热点 + 统计。"""
    output = pipe.run(_sample())

    assert output["status"] == "ok"
    assert output["module"] == "SC-02"
    for key in ("network", "risk_hotspots", "dependency_analysis",
                "risk_paths", "recommendations", "statistics"):
        assert key in output


def test_pipeline_network_matches_input(pipe):
    """网络节点/边数与输入一致。"""
    sample = _sample()
    output = pipe.run(sample)

    assert len(output["network"]["nodes"]) == len(sample["suppliers"])
    assert len(output["network"]["edges"]) == len(sample["relations"])


def test_pipeline_statistics_and_risk_distribution(pipe):
    """统计字段完整，风险分布 critical+high+medium+low = node_count。"""
    sample = _sample()
    output = pipe.run(sample)

    stats = output["statistics"]
    assert stats["node_count"] == len(sample["suppliers"])
    assert stats["edge_count"] == len(sample["relations"])
    assert "community_count" in stats
    assert "avg_degree" in stats

    dist = stats["risk_distribution"]
    for lv in ("critical", "high", "medium", "low"):
        assert lv in dist
    assert (dist["critical"] + dist["high"] + dist["medium"] + dist["low"]
            == stats["node_count"])


def test_pipeline_dependency_analysis_and_recommendations(pipe):
    """依赖分析三类齐全，sample 含 6 层链 → deep_dependency 非空；建议非空。"""
    sample = _sample()
    output = pipe.run(sample)

    da = output["dependency_analysis"]
    assert "single_source_nodes" in da
    assert "monopoly_risk_nodes" in da
    assert "deep_dependency_nodes" in da
    assert len(da["deep_dependency_nodes"]) > 0
    # 单一来源：S-202 仅由 S-302 供应
    single_ids = {n["supplier_id"] for n in da["single_source_nodes"]}
    assert "S-202" in single_ids
    # 垄断：C-501 集中度 4/5=0.8 > 0.7
    monopoly_ids = {n["supplier_id"] for n in da["monopoly_risk_nodes"]}
    assert "C-501" in monopoly_ids
    # 深度：CORE-001 上游 6 层
    deep_ids = {n["supplier_id"] for n in da["deep_dependency_nodes"]}
    assert "CORE-001" in deep_ids

    assert len(output["recommendations"]) > 0


# ----------------------------------------------------------------------
# 配置透传
# ----------------------------------------------------------------------
def test_pipeline_config_threshold_propagates(tmp_path):
    """Pipeline config 中的 threshold 透传到 apply_thresholds（统计 thresholds 反映）。"""
    pipe = _make_pipeline(
        tmp_path,
        threshold={"critical": 0.9, "high": 0.6, "medium": 0.4, "concentration": 0.95},
    )
    try:
        output = pipe.run(_sample())
    finally:
        pipe.engine.close()

    thresholds = output["statistics"]["thresholds"]
    assert thresholds["critical"] == 0.9
    assert thresholds["high"] == 0.6
    assert thresholds["medium"] == 0.4
    assert thresholds["concentration"] == 0.95
    # concentration 阈值提高到 0.95 后，C-501 (0.8) 不再算垄断
    monopoly_ids = {
        n["supplier_id"]
        for n in output["dependency_analysis"]["monopoly_risk_nodes"]
    }
    assert "C-501" not in monopoly_ids


# ----------------------------------------------------------------------
# PortableDB 持久化
# ----------------------------------------------------------------------
def test_pipeline_persists_to_portable_db(tmp_path):
    """Pipeline 把 suppliers/relations/graph_analysis 持久化到 PortableDB。"""
    db_path = tmp_path / "sc_02_pipeline.db"
    pipe = _make_pipeline(tmp_path)
    sample = _sample()
    try:
        output = pipe.run(sample)
    finally:
        pipe.engine.close()  # 释放 db 句柄后再以只读方式打开校验

    with PortableDB(db_path) as db:
        assert db.count("suppliers") == len(sample["suppliers"])
        assert db.count("relations") == len(sample["relations"])
        rows = db.all("graph_analysis")

    assert len(rows) == len(output["network"]["nodes"])
    for r in rows:
        assert "pagerank" in r
        assert "community_id" in r
        assert "risk_score" in r


def test_pipeline_idempotent_rerun(pipe):
    """重复 run 不会累积数据（每次清空重写）。"""
    sample = _sample()
    pipe.run(sample)
    pipe.run(sample)

    # 第二次 run 后节点/边数仍与输入一致（未翻倍）
    db_path = Path(pipe.engine.config["db_path"])
    with PortableDB(db_path) as db:
        assert db.count("suppliers") == len(sample["suppliers"])
        assert db.count("relations") == len(sample["relations"])


# ----------------------------------------------------------------------
# 空输入
# ----------------------------------------------------------------------
def test_pipeline_empty_input(pipe):
    """空输入 → status ok、节点数 0。"""
    output = pipe.run({"suppliers": [], "relations": []})
    assert output["status"] == "ok"
    assert output["statistics"]["node_count"] == 0
    assert output["network"]["nodes"] == []
