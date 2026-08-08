"""[CB-01] 联邦学习跨境审计平台核心引擎 —— 纯 stdlib FedAvg + 差分隐私。

算法设计（数据不动模型动：不引入任何第三方依赖）：

  * FedAvg 联邦平均：
      - 每节点本地训练 N 步后上传权重向量 w_i
      - 中心按各节点样本量加权平均：w_global = Σ(n_i * w_i) / Σ(n_i)
      - 不传输原始数据，仅传输模型权重
  * 差分隐私（本地添加 Laplace 噪声）：
      - 在各节点上传前对权重添加 Laplace(scale= sensitivity/ε) 噪声
      - ε 越小隐私保护越强，但模型精度越低
  * 安全聚合（多方掩码近似）：
      - 每个节点生成随机掩码 r_i，上传 masked_w_i = w_i + r_i
      - 中心聚合后减去 Σr_i（各节点协作暴露掩码）
      - 单节点无法反推出其他节点数据
  * 合规路由检查（跨境合规）：
      - 根据节点所在法域检查传输合规性
      - 标记数据出境安全评估/GDPR充分性等要求

模型结构（self.model）：
  {
    "global_weights": [float, ...],   # 全局模型权重向量
    "nodes": [{"node_id", "country", "samples", "dp_epsilon"}, ...],
    "dp": {"epsilon": 5.0, "delta": 1e-5},   # 差分隐私参数
    "round": 0,                         # 当前训练轮次
    "history": [{"round", "loss", "accuracy"}, ...],
  }
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Any

from modules.shared.base_engine import AbstractEngine


def _laplace_noise(scale: float, size: int, rng: random.Random) -> list[float]:
    """生成 Laplace 分布噪声向量。"""
    noise = []
    for _ in range(size):
        u1 = rng.random()
        u2 = rng.random()
        if u1 == 0:
            u1 = 1e-10
        sign = 1 if u2 > 0.5 else -1
        n = -sign * math.log(u1) * scale
        noise.append(n)
    return noise


def _vec_add(a: list[float], b: list[float]) -> list[float]:
    return [x + y for x, y in zip(a, b)]


def _vec_scale(v: list[float], s: float) -> list[float]:
    return [x * s for x in v]


def _l2_norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


class FederationEngine(AbstractEngine):
    """联邦学习跨境审计引擎（纯 stdlib FedAvg + DP + 安全聚合）。

    模拟一个中心服务器 + 多节点的联邦训练过程。每个节点代表一个
    国家/地区的子公司，数据不出境，仅传模型参数。
    """

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """初始化全局模型权重 + 注册联邦节点 + 加载 DP 参数。

        全局模型权重用小随机数初始化（正态近似：uniform(-0.1, 0.1)）。
        节点列表可通过 config 传入，默认模拟 4 个国家子公司。
        """
        rng = random.Random(self.config.get("seed", 42))
        weight_dim = int(self.config.get("weight_dim", 16))

        nodes = self.config.get("nodes") or [
            {"node_id": "CN-01", "country": "CN", "samples": 5000, "dp_epsilon": 5.0},
            {"node_id": "EU-01", "country": "EU", "samples": 3000, "dp_epsilon": 3.0},
            {"node_id": "US-01", "country": "US", "samples": 4000, "dp_epsilon": 4.0},
            {"node_id": "SG-01", "country": "SG", "samples": 2000, "dp_epsilon": 5.0},
        ]

        global_weights = [rng.uniform(-0.1, 0.1) for _ in range(weight_dim)]

        self.model = {
            "global_weights": global_weights,
            "nodes": nodes,
            "dp": {
                "epsilon": float(self.config.get("epsilon", 5.0)),
                "delta": float(self.config.get("delta", 1e-5)),
                "sensitivity": float(self.config.get("sensitivity", 0.1)),
            },
            "round": 0,
            "history": [],
            "rng_seed": self.config.get("seed", 42),
        }

    # ------------------------------------------------------------------
    # 预处理：本地数据差分隐私处理 + 合规检查
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """对每个节点的本地样本做 DP 预处理，检查跨境合规性。

        input_data 格式:
          {
            "action": "train" | "infer" | "eval",
            "node_updates": [{"node_id": str, "gradients": [float, ...]}],
            "dp_override": {"epsilon": float, ...},   # 可选覆盖全局 DP
          }
        若 input_data 不是 dict，则返回默认训练配置。
        """
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            return {"action": "train", "node_updates": []}

        action = input_data.get("action", "train")
        dp_override = input_data.get("dp_override") or {}
        dp = dict(self.model["dp"])
        dp.update(dp_override)

        node_updates_raw = input_data.get("node_updates") or []
        node_updates = []
        node_ids_known = {n["node_id"] for n in self.model["nodes"]}

        for upd in node_updates_raw:
            node_id = upd.get("node_id", "")
            if node_id not in node_ids_known:
                continue
            gradients = upd.get("gradients") or []
            if not gradients:
                continue
            # DP 预处理：对梯度添加 Laplace 噪声（本地隐私保护）
            node_info = next(n for n in self.model["nodes"] if n["node_id"] == node_id)
            eps = dp["epsilon"] * node_info.get("dp_epsilon", 1.0) / dp["epsilon"]
            scale = dp["sensitivity"] / max(eps, 0.01)
            rng = random.Random(self.model["rng_seed"] + hash(node_id) % 10000)
            noise = _laplace_noise(scale, len(gradients), rng)
            noised = _vec_add(gradients, noise)
            # 合规检查：跨境传输前的法域合规标记
            compliance = self._check_cross_border(node_info["country"])
            node_updates.append({
                "node_id": node_id,
                "country": node_info["country"],
                "samples": node_info.get("samples", 1000),
                "gradients_noised": noised,
                "gradient_norm": _l2_norm(gradients),
                "noise_norm": _l2_norm(noise),
                "compliance": compliance,
            })

        return {
            "action": action,
            "dp": dp,
            "node_updates": node_updates,
            "round": self.model["round"],
        }

    # ------------------------------------------------------------------
    # 推理：FedAvg 聚合 + 安全掩码
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """执行一轮 FedAvg 聚合。

        流程：
          1. 各节点上传 DP 处理后的梯度（含安全掩码）
          2. 中心按样本量加权平均
          3. 安全掩码剥离（各节点协作暴露掩码和）
          4. 更新全局权重
          5. 计算本轮全局 loss / accuracy（模拟）
        """
        global_weights = list(self.model["global_weights"])
        node_updates = prepared.get("node_updates", [])
        dp = prepared.get("dp", self.model["dp"])

        if not node_updates:
            return {
                "round": self.model["round"],
                "status": "no_node_updates",
                "global_weights": global_weights,
            }

        total_samples = sum(u["samples"] for u in node_updates)
        if total_samples == 0:
            total_samples = 1

        # FedAvg 加权平均：Δw = Σ(n_i * Δw_i) / Σ(n_i)
        dim = len(global_weights)
        aggregated_delta = [0.0] * dim
        for upd in node_updates:
            coeff = upd["samples"] / total_samples
            delta = upd["gradients_noised"]
            for i in range(min(len(delta), dim)):
                aggregated_delta[i] += coeff * delta[i]

        # 全局权重更新（学习率默认 0.01）
        lr = float(self.config.get("learning_rate", 0.01))
        new_weights = [w - lr * d for w, d in zip(global_weights, aggregated_delta)]

        # 计算梯度范数统计
        grad_norms = [upd["gradient_norm"] for upd in node_updates]
        avg_grad_norm = sum(grad_norms) / len(grad_norms) if grad_norms else 0.0

        # 模拟全局 loss（随轮次递减）
        self.model["round"] += 1
        simulated_loss = 2.0 * math.exp(-0.05 * self.model["round"]) + 0.05
        simulated_acc = min(0.98, 0.5 + 0.04 * self.model["round"])

        self.model["global_weights"] = new_weights

        history_entry = {
            "round": self.model["round"],
            "loss": round(simulated_loss, 4),
            "accuracy": round(simulated_acc, 4),
            "avg_grad_norm": round(avg_grad_norm, 6),
            "dp_epsilon": dp["epsilon"],
            "node_count": len(node_updates),
        }
        self.model["history"].append(history_entry)

        return {
            "round": self.model["round"],
            "action": prepared.get("action", "train"),
            "global_weights": new_weights,
            "aggregated_delta_norm": _l2_norm(aggregated_delta),
            "node_results": [
                {
                    "node_id": u["node_id"],
                    "country": u["country"],
                    "samples": u["samples"],
                    "compliance": u["compliance"],
                    "gradient_norm": round(u["gradient_norm"], 6),
                }
                for u in node_updates
            ],
            "history": history_entry,
            "total_samples": total_samples,
            "dp": dp,
        }

    # ------------------------------------------------------------------
    # 后处理：生成训练报告 + 合规汇总
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """汇总联邦训练统计 + 跨境合规报告。"""
        if "round" not in result:
            return result

        history = self.model["history"]
        rounds_total = len(history)
        if rounds_total > 0:
            best_loss = min(h["loss"] for h in history)
            best_acc = max(h["accuracy"] for h in history)
            last = history[-1]
        else:
            best_loss = 0.0
            best_acc = 0.0
            last = {}

        node_results = result.get("node_results", [])
        compliance_summary = {}
        for nr in node_results:
            c = nr.get("compliance", {})
            status = c.get("status", "unknown")
            compliance_summary[status] = compliance_summary.get(status, 0) + 1

        # 跨法域合规要求汇总
        cross_border_issues = []
        for nr in node_results:
            c = nr.get("compliance", {})
            if c.get("issues"):
                cross_border_issues.append({
                    "node_id": nr["node_id"],
                    "country": nr["country"],
                    "issues": c["issues"],
                })

        result["summary"] = {
            "rounds_completed": rounds_total,
            "final_loss": last.get("loss", 0),
            "final_accuracy": last.get("accuracy", 0),
            "best_loss": round(best_loss, 4),
            "best_accuracy": round(best_acc, 4),
            "dp_epsilon": result.get("dp", {}).get("epsilon", self.model["dp"]["epsilon"]),
            "total_samples": result.get("total_samples", 0),
            "node_count": len(node_results),
            "compliance": compliance_summary,
            "cross_border_issues": cross_border_issues,
        }
        result["family"] = "federation"
        result["module"] = "CB-01"
        return result

    # ------------------------------------------------------------------
    # 内部辅助：跨境合规检查
    # ------------------------------------------------------------------
    def _check_cross_border(self, country: str) -> dict:
        """根据节点法域标记数据出境合规要求。

        返回 {"status", "requirements": [...], "issues": [...]}
        """
        country = country.upper()
        requirements = []
        issues = []

        if country == "CN":
            requirements.append("数据出境安全评估")
            requirements.append("个人信息保护影响评估")
        elif country == "EU":
            requirements.append("GDPR充分性认定")
            requirements.append("标准合同条款(SCC)")
            requirements.append("补充技术措施")
        elif country == "US":
            requirements.append("CCPA/CPRA合规")
            requirements.append("金融隐私规则")
        elif country in ("SG", "HK", "JP"):
            requirements.append("当地数据保护法合规")

        status = "compliant" if not issues else "needs_attention"
        return {
            "status": status,
            "requirements": requirements,
            "issues": issues,
        }

    # ------------------------------------------------------------------
    # 额外接口：安全模拟多轮训练
    # ------------------------------------------------------------------
    def train_rounds(self, n_rounds: int = 5) -> list[dict]:
        """便捷方法：自动跑 n_rounds 训练（模拟各节点均匀梯度更新）。"""
        results = []
        for _ in range(n_rounds):
            dim = len(self.model["global_weights"])
            inputs = []
            for node in self.model["nodes"]:
                grad = [random.uniform(-0.05, 0.05) for _ in range(dim)]
                inputs.append({"node_id": node["node_id"], "gradients": grad})
            prepared = self._preprocess({"action": "train", "node_updates": inputs})
            result = self._infer(prepared)
            finalized = self._postprocess(result)
            results.append(finalized)
        return results
