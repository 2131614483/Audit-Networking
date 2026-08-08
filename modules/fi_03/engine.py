"""[FI-03] ML 贷款违约预测引擎 —— 纯 stdlib 逻辑回归。

用预训练权重实现逻辑回归推理（模拟训练好的模型），无需 sklearn/numpy。
覆盖方案文档中的贷款违约预测验证：
  * 特征：信用评分、收入负债比、贷款价值比、就业年限、历史违约次数
  * 模型：逻辑回归（sigmoid(w·x + b)）
  * 输出：违约概率 + 风险评级（A/B/C/D/E）

模型结构（self.model）：
  {
    "weights": {feature_name: coefficient},
    "bias": float,
    "scaler": {feature_name: {"mean": ..., "std": ...}},   # 标准化参数
    "ratings": [("A", 0.05), ("B", 0.15), ("C", 0.30), ("D", 0.50), ("E", 1.0)],
  }

权重来源：模拟在 10 万+历史贷款数据上训练的逻辑回归模型。
"""
from __future__ import annotations

import math
from typing import Any

from modules.shared.base_engine import AbstractEngine


class MLEngine(AbstractEngine):
    """贷款违约预测引擎（纯 stdlib 逻辑回归）。"""

    def _load_model(self) -> None:
        """加载预训练逻辑回归权重 + 标准化参数。"""
        self.model = {
            # 预训练权重（模拟训练结果）
            "weights": {
                "credit_score": -0.035,       # 信用分越高 → 违约概率越低
                "dti_ratio": 2.8,              # 收入负债比越高 → 违约概率越高
                "ltv_ratio": 1.9,              # 贷款价值比越高 → 违约概率越高
                "employment_years": -0.15,     # 就业年限越长 → 违约概率越低
                "default_history": 1.6,        # 历史违约次数越多 → 违约概率越高
                "loan_amount": 0.00002,        # 贷款金额（元）
            },
            "bias": -1.2,
            # 标准化参数（模拟训练集统计量）
            "scaler": {
                "credit_score": {"mean": 680, "std": 80},
                "dti_ratio": {"mean": 0.35, "std": 0.15},
                "ltv_ratio": {"mean": 0.75, "std": 0.20},
                "employment_years": {"mean": 8, "std": 5},
                "default_history": {"mean": 0.3, "std": 0.8},
                "loan_amount": {"mean": 300000, "std": 200000},
            },
            "ratings": [("A", 0.05), ("B", 0.15), ("C", 0.30), ("D", 0.50), ("E", 1.0)],
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取贷款申请人列表 + 标准化特征（懒加载模型）。"""
        if self.model is None:
            self._load_model()
        if isinstance(input_data, dict) and "applicants" in input_data:
            applicants = input_data["applicants"]
        elif isinstance(input_data, list):
            applicants = input_data
        else:
            return []

        scaler = self.model["scaler"]
        features = self.model["weights"].keys()
        prepared = []
        for a in applicants:
            scaled = {}
            for f in features:
                raw = a.get(f, 0)
                s = scaler.get(f, {"mean": 0, "std": 1})
                std = s["std"] if s["std"] != 0 else 1
                scaled[f] = (raw - s["mean"]) / std
            prepared.append({"applicant": a, "scaled_features": scaled})
        return prepared

    def _infer(self, prepared: Any) -> Any:
        """逻辑回归推理：sigmoid(w·x + b) → 违约概率。"""
        weights = self.model["weights"]
        bias = self.model["bias"]
        results = []
        for item in prepared:
            scaled = item["scaled_features"]
            # 线性组合: w·x + b
            z = bias + sum(weights.get(f, 0) * scaled.get(f, 0) for f in weights)
            # sigmoid → 违约概率
            prob = 1 / (1 + math.exp(-z)) if z < 500 else 1.0
            results.append({
                "applicant_id": item["applicant"].get("applicant_id", "?"),
                "name": item["applicant"].get("name", "?"),
                "default_probability": round(prob, 4),
                "logit": round(z, 4),
                "features": {k: v for k, v in item["applicant"].items()
                             if k in weights and k != "applicant_id"},
            })
        results.sort(key=lambda x: x["default_probability"], reverse=True)
        return results

    def _postprocess(self, result: Any) -> Any:
        """风险评级 A/B/C/D/E + 审批建议。"""
        ratings = self.model["ratings"]
        for r in result:
            p = r["default_probability"]
            for rating, threshold in ratings:
                if p <= threshold:
                    r["rating"] = rating
                    break
            # 审批建议
            if r["rating"] in ("A", "B"):
                r["decision"] = "通过"
            elif r["rating"] == "C":
                r["decision"] = "人工复核"
            else:
                r["decision"] = "拒绝"
        summary = {
            "total": len(result),
            "approved": sum(1 for r in result if r["decision"] == "通过"),
            "review": sum(1 for r in result if r["decision"] == "人工复核"),
            "rejected": sum(1 for r in result if r["decision"] == "拒绝"),
            "avg_probability": round(sum(r["default_probability"] for r in result) / max(len(result), 1), 4),
        }
        return {"applicants": result, "summary": summary}
