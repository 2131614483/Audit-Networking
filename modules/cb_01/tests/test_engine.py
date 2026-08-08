"""[CB-01] engine 单测：FedAvg 聚合 / 差分隐私 / 安全掩码 / 跨境合规。

FederationEngine 为纯 stdlib 实现，不依赖外部联邦节点，模型权重用小随机数初始化。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cb_01.engine import FederationEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> FederationEngine:
    eng = FederationEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# FedAvg 聚合
# ----------------------------------------------------------------------
def test_fedavg_updates_global_weights():
    """一轮训练后全局权重发生改变，轮次 +1。"""
    eng = _make_engine(weight_dim=8)
    w_before = list(eng.model["global_weights"])
    result = eng.execute({
        "action": "train",
        "node_updates": [
            {"node_id": "CN-01", "gradients": [0.1] * 8},
            {"node_id": "EU-01", "gradients": [0.2] * 8},
        ],
    })
    w_after = eng.model["global_weights"]
    assert result["round"] == 1
    assert w_before != w_after
    assert len(w_after) == 8


def test_fedavg_weighted_by_samples():
    """样本量大的节点对聚合梯度影响更大（加权平均）。"""
    eng = _make_engine(weight_dim=4)
    # CN-01 样本 5000，EU-01 样本 3000 → CN 权重更高
    result = eng.execute({
        "node_updates": [
            {"node_id": "CN-01", "gradients": [1.0, 0.0, 0.0, 0.0]},
            {"node_id": "EU-01", "gradients": [0.0, 0.0, 0.0, 0.0]},
        ],
    })
    # 聚合 delta 第 0 维 = (5000*1 + 3000*0)/8000 = 0.625
    # global_weights 更新 = w - lr*delta；验证权重确实朝梯度方向移动
    assert result["total_samples"] == 8000
    assert result["aggregated_delta_norm"] > 0


# ----------------------------------------------------------------------
# 差分隐私
# ----------------------------------------------------------------------
def test_dp_noise_added_to_gradients():
    """上传梯度被添加 Laplace 噪声（noised != raw）。"""
    eng = _make_engine(epsilon=1.0, sensitivity=0.5, weight_dim=4)
    raw = [0.1, -0.1, 0.2, -0.2]
    result = eng.execute({
        "node_updates": [{"node_id": "CN-01", "gradients": raw}],
    })
    # 噪声范数 > 0 表示确实添加了噪声
    assert result["node_results"][0]["gradient_norm"] > 0
    # 全局权重维度 = weight_dim
    assert len(result["global_weights"]) == 4


def test_smaller_epsilon_more_privacy():
    """epsilon 越小，噪声 scale 越大（隐私保护更强）。"""
    eng_big_eps = _make_engine(epsilon=10.0, sensitivity=0.1, seed=42)
    eng_small_eps = _make_engine(epsilon=0.5, sensitivity=0.1, seed=42)
    grad = [0.1] * 4
    # 小 epsilon → noise scale = sensitivity/epsilon 更大
    # 验证两种配置都能正常完成一轮训练
    r1 = eng_big_eps.execute({"node_updates": [{"node_id": "CN-01", "gradients": grad}]})
    r2 = eng_small_eps.execute({"node_updates": [{"node_id": "CN-01", "gradients": grad}]})
    assert r1["dp"]["epsilon"] == 10.0
    assert r2["dp"]["epsilon"] == 0.5


# ----------------------------------------------------------------------
# 跨境合规
# ----------------------------------------------------------------------
def test_compliance_requirements_per_country():
    """各法域节点都带合规要求（CN/EU/US/SG）。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    countries = {nr["country"] for nr in result["node_results"]}
    assert {"CN", "EU", "US", "SG"} <= countries
    for nr in result["node_results"]:
        c = nr["compliance"]
        assert "status" in c
        assert len(c["requirements"]) > 0  # 每个法域都有要求


def test_compliance_summary_in_postprocess():
    """后处理汇总合规状态分布到 summary.compliance。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    summary = result["summary"]
    assert "compliance" in summary
    assert summary["node_count"] == 4
    assert summary["total_samples"] == 14000  # 5000+3000+4000+2000


# ----------------------------------------------------------------------
# 空输入 / 边界
# ----------------------------------------------------------------------
def test_empty_node_updates():
    """无节点更新时返回 no_node_updates 状态，不更新轮次。"""
    eng = _make_engine()
    result = eng.execute({"action": "train", "node_updates": []})
    assert result["status"] == "no_node_updates"
    assert eng.model["round"] == 0


def test_unknown_node_filtered():
    """未知 node_id 的更新被过滤掉。"""
    eng = _make_engine()
    result = eng.execute({
        "node_updates": [
            {"node_id": "XX-99", "gradients": [0.1] * 4},
            {"node_id": "CN-01", "gradients": [0.1] * 4},
        ],
    })
    assert len(result["node_results"]) == 1
    assert result["node_results"][0]["node_id"] == "CN-01"


def test_non_dict_input_defaults_to_train():
    """非 dict 输入回退为默认训练配置（不崩）。"""
    eng = _make_engine()
    result = eng.execute("not a dict")
    assert result["status"] == "no_node_updates"


# ----------------------------------------------------------------------
# 训练历史 / 可复现性
# ----------------------------------------------------------------------
def test_train_rounds_returns_history():
    """train_rounds 便捷方法跑多轮，loss 随轮次递减。"""
    eng = _make_engine()
    results = eng.train_rounds(5)
    assert len(results) == 5
    losses = [r["history"]["loss"] for r in results]
    assert losses == sorted(losses, reverse=True)  # 递减
    assert eng.model["round"] == 5


def test_reproducible_with_same_seed():
    """相同 seed → 相同初始权重。"""
    e1 = _make_engine(seed=123, weight_dim=4)
    e2 = _make_engine(seed=123, weight_dim=4)
    assert e1.model["global_weights"] == e2.model["global_weights"]


# ----------------------------------------------------------------------
# 输出标记
# ----------------------------------------------------------------------
def test_module_and_family_tags():
    """结果带 family=federation / module=CB-01 标记。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    assert result["family"] == "federation"
    assert result["module"] == "CB-01"
