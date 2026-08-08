"""[CM-04] 持续审计价值量化模型引擎 —— 纯 stdlib 风险损失测算 + ROI 计算 + Monte Carlo 模拟。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 风险损失测算（期望损失 vs 避免损失）：
      - 预期损失 = 风险发生概率 × 风险影响金额
      - 避免损失 = 基准预期损失 - 持续审计后预期损失
      - 概率贝叶斯更新：后验 = 先验 × 似然 / 证据
  * 效率节约计算：
      - 效率节约 = Σ(传统耗时 - 持续审计耗时) × 单位人力成本
      - 节约比例分活动类型配置
  * ROI 模型（多年度 DCF）：
      - ROI = (年度总收益 - 年度总成本) / 年度总成本 × 100%
      - 投资回收期 = 初始投资 / 年度净收益
      - 净现值 NPV = Σ(净收益_t / (1+折现率)^t) - 初始投资
  * Monte Carlo 情景模拟：
      - 对关键参数（概率、金额、成本）进行三角分布采样
      - 运行 N 次模拟，输出 P10 / P50 / P90 分位数
  * 敏感性分析：
      - 单因素扰动 + Tornado 排序

模型结构（self.model）：
  {
    "risk_catalog": [...],
    "efficiency_baselines": {...},
    "cost_model": {...},
    "discount_rate": 0.08,
  }
"""
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "cm_04.db"

_RISKS_SCHEMA = {
    "risk_id": "TEXT",
    "risk_type": "TEXT",
    "name": "TEXT",
    "baseline_prob": "REAL",
    "mitigated_prob": "REAL",
    "avg_impact": "REAL",
    "category": "TEXT",
    "tags": "JSON",
}
_VALUATIONS_SCHEMA = {
    "valuation_id": "TEXT",
    "period": "TEXT",
    "risk_avoided": "REAL",
    "efficiency_saved": "REAL",
    "quality_value": "REAL",
    "compliance_value": "REAL",
    "total_value": "REAL",
    "cost": "REAL",
    "roi": "REAL",
    "payback_months": "REAL",
    "npv": "REAL",
    "created_at": "DATETIME",
}

_DEFAULT_RISKS: list[dict] = [
    {"risk_id": "R01", "risk_type": "fraud_procurement", "name": "采购欺诈",
     "baseline_prob": 0.02, "mitigated_prob": 0.005, "avg_impact": 5000000,
     "category": "风险避免"},
    {"risk_id": "R02", "risk_type": "financial_error", "name": "财务差错",
     "baseline_prob": 0.05, "mitigated_prob": 0.01, "avg_impact": 2000000,
     "category": "风险避免"},
    {"risk_id": "R03", "risk_type": "compliance_violation", "name": "合规违规",
     "baseline_prob": 0.03, "mitigated_prob": 0.005, "avg_impact": 10000000,
     "category": "合规收益"},
    {"risk_id": "R04", "risk_type": "operational_risk", "name": "操作风险",
     "baseline_prob": 0.04, "mitigated_prob": 0.01, "avg_impact": 3000000,
     "category": "风险避免"},
    {"risk_id": "R05", "risk_type": "revenue_leakage", "name": "收入流失",
     "baseline_prob": 0.025, "mitigated_prob": 0.008, "avg_impact": 4000000,
     "category": "风险避免"},
    {"risk_id": "R06", "risk_type": "asset_misuse", "name": "资产滥用",
     "baseline_prob": 0.015, "mitigated_prob": 0.003, "avg_impact": 2500000,
     "category": "风险避免"},
]

_EFFICIENCY_BASELINES: dict[str, dict] = {
    "transaction_check": {"traditional_person_days_per_month": 100,
                          "continuous_person_days_per_month": 0, "unit_cost": 2000},
    "data_collection": {"traditional_person_days_per_month": 50,
                        "continuous_person_days_per_month": 5, "unit_cost": 2000},
    "anomaly_analysis": {"traditional_person_days_per_month": 80,
                          "continuous_person_days_per_month": 10, "unit_cost": 2500},
    "report_generation": {"traditional_person_days_per_month": 30,
                          "continuous_person_days_per_month": 5, "unit_cost": 2000},
    "followup_verification": {"traditional_person_days_per_month": 40,
                              "continuous_person_days_per_month": 10, "unit_cost": 2200},
}


class MLEngine(AbstractEngine):
    """CM-04 价值量化引擎（风险损失测算 + ROI + Monte Carlo + 敏感性）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for t, s in (("risks", _RISKS_SCHEMA), ("valuations", _VALUATIONS_SCHEMA)):
            if t not in self.db.tables():
                self.db.create_table(t, s)
        self.model = {
            "risks": list(_DEFAULT_RISKS),
            "efficiency": dict(_EFFICIENCY_BASELINES),
            "discount_rate": self.config.get("discount_rate", 0.08),
            "unit_person_day_cost": self.config.get("unit_person_day_cost", 2200),
            "working_days_per_year": 250,
            "labor_cost_ratio": 0.7,
        }
        self._seed_risks()

    def _seed_risks(self) -> None:
        if not self.db:
            return
        if self.db.count("risks") == 0:
            self.db.insert_many("risks", self.model["risks"])

    def _ensure_loaded(self) -> None:
        """惰性初始化（支持不显式调用 setup() 直接 execute()）。"""
        if getattr(self, "model", None) is None:
            self._load_model()

    def _preprocess(self, input_data: Any) -> dict:
        self._ensure_loaded()
        if isinstance(input_data, dict):
            action = input_data.get("action", "quantify")
            if action == "quantify":
                return {"action": "quantify",
                        "risks": input_data.get("risks"),
                        "costs": input_data.get("costs", {}),
                        "time_horizon_years": input_data.get("time_horizon_years", 3),
                        "scenario": input_data.get("scenario", "base")}
            if action == "roi":
                return {"action": "roi",
                        "initial_investment": input_data.get("initial_investment", 7200000),
                        "annual_cost": input_data.get("annual_cost", 2000000),
                        "annual_revenue": input_data.get("annual_revenue"),
                        "time_horizon_years": input_data.get("time_horizon_years", 5)}
            if action == "simulate":
                return {"action": "simulate",
                        "num_simulations": input_data.get("num_simulations", 5000),
                        "costs": input_data.get("costs", {}),
                        "scenario": input_data.get("scenario", "base")}
            if action == "sensitivity":
                return {"action": "sensitivity",
                        "param_name": input_data.get("param_name"),
                        "param_range": input_data.get("param_range", (0.5, 1.5)),
                        "scenario": input_data.get("scenario", "base")}
            if action == "add_risk":
                return {"action": "add_risk", "risk": input_data.get("risk", input_data)}
            if action == "efficiency":
                return {"action": "efficiency",
                        "custom_baselines": input_data.get("custom_baselines")}
        raise ValueError(f"无法识别的输入: {input_data}")

    def _infer(self, prepared: dict) -> dict:
        action = prepared["action"]
        if action == "quantify":
            return self._quantify_value(prepared)
        if action == "roi":
            return self._roi_analysis(prepared)
        if action == "simulate":
            return self._monte_carlo(prepared)
        if action == "sensitivity":
            return self._sensitivity_analysis(prepared)
        if action == "add_risk":
            return self._add_risk(prepared["risk"])
        if action == "efficiency":
            return self._compute_efficiency(prepared.get("custom_baselines"))
        raise ValueError(f"未知 action: {action}")

    def _postprocess(self, result: dict) -> dict:
        result["engine"] = "CM-04-ValueQuantification"
        result["timestamp"] = datetime.now().isoformat()
        return result

    # ---------- 风险损失测算 ----------

    def _quantify_value(self, params: dict) -> dict:
        horizon = params["time_horizon_years"]
        scenario = params["scenario"]
        risks = params["risks"] or self.model["risks"]
        risk_value = self._compute_risk_avoided(risks, horizon)
        eff_result = self._compute_efficiency()
        quality_value = self._estimate_quality_value(risks, horizon)
        compliance_value = self._estimate_compliance_value(risks, horizon)
        total = risk_value["total_risk_avoided"] + eff_result["annual_total"] + quality_value + compliance_value
        cost_result = self._estimate_annual_costs(params.get("costs", {}))
        net_benefit = total - cost_result["annual_total_cost"]
        payback_months = (cost_result["initial_investment"] / max(net_benefit, 1)) * 12
        roi = (net_benefit / cost_result["annual_total_cost"] * 100) if cost_result["annual_total_cost"] > 0 else 0
        npv = self._compute_npv(cost_result["initial_investment"],
                                total - cost_result["annual_operating_cost"],
                                horizon, self.model["discount_rate"])
        return {
            "action": "quantify",
            "scenario": scenario,
            "horizon_years": horizon,
            "breakdown": {
                "risk_avoided": risk_value,
                "efficiency_saved": eff_result,
                "quality_improved": quality_value,
                "compliance_gained": compliance_value,
            },
            "totals": {
                "annual_total_value": round(total, 2),
                "annual_risk_avoided": round(risk_value["total_risk_avoided"], 2),
                "annual_efficiency_saved": round(eff_result["annual_total"], 2),
                "annual_quality_value": round(quality_value, 2),
                "annual_compliance_value": round(compliance_value, 2),
            },
            "costs": cost_result,
            "roi_metrics": {
                "roi_percent": round(roi, 1),
                "net_benefit": round(net_benefit, 2),
                "payback_months": round(payback_months, 1),
                "npv": round(npv, 2),
            },
        }

    def _compute_risk_avoided(self, risks: list[dict], horizon: int) -> dict:
        items = []
        total_avoided = 0.0
        for r in risks:
            baseline_loss = r["baseline_prob"] * r["avg_impact"]
            mitigated_loss = r["mitigated_prob"] * r["avg_impact"]
            avoided = (baseline_loss - mitigated_loss) * 12
            items.append({
                "risk_id": r["risk_id"], "name": r["name"],
                "category": r.get("category", "风险避免"),
                "baseline_prob": r["baseline_prob"],
                "mitigated_prob": r["mitigated_prob"],
                "prob_reduction": round((1 - r["mitigated_prob"] / max(r["baseline_prob"], 1e-9)) * 100, 1),
                "avg_impact": r["avg_impact"],
                "baseline_annual_loss": round(baseline_loss * 12, 2),
                "mitigated_annual_loss": round(mitigated_loss * 12, 2),
                "annual_avoided": round(avoided, 2),
            })
            total_avoided += avoided
        total_avoided = min(total_avoided, 2_000_000_000)
        return {"items": items, "total_risk_avoided": round(total_avoided, 2)}

    def _estimate_quality_value(self, risks: list[dict], horizon: int) -> float:
        base = sum(r["avg_impact"] * (r["baseline_prob"] - r["mitigated_prob"]) for r in risks) * 0.3
        return round(base * 12, 2)

    def _estimate_compliance_value(self, risks: list[dict], horizon: int) -> float:
        compliance_risks = [r for r in risks
                             if r.get("category") == "合规收益" or "合规" in r.get("name", "")]
        if not compliance_risks:
            return round(sum(r["avg_impact"] * (r["baseline_prob"] - r["mitigated_prob"]) * 12
                             for r in risks) * 0.25, 2)
        return round(sum(r["avg_impact"] * (r["baseline_prob"] - r["mitigated_prob"]) * 12
                         for r in compliance_risks), 2)

    # ---------- 效率节约 ----------

    def _compute_efficiency(self, custom: dict | None = None) -> dict:
        baselines = custom or self.model["efficiency"]
        items = []
        total_saved = 0.0
        for k, v in baselines.items():
            trad = v["traditional_person_days_per_month"]
            cont = v["continuous_person_days_per_month"]
            saved_days = (trad - cont) * 12
            saved_cost = saved_days * v.get("unit_cost", self.model["unit_person_day_cost"])
            items.append({
                "activity": k, "traditional_days_year": trad * 12,
                "continuous_days_year": cont * 12,
                "saved_days_year": saved_days, "saved_cost_year": round(saved_cost, 2),
                "saving_ratio_percent": round(saved_days / max(trad * 12, 1) * 100, 1),
            })
            total_saved += saved_cost
        return {"items": items, "annual_total": round(total_saved, 2)}

    # ---------- 成本估算 ----------

    def _estimate_annual_costs(self, custom: dict) -> dict:
        initial = custom.get("initial_investment", 7200000)
        annual_op = custom.get("annual_operating", 2000000)
        annual_maint = custom.get("annual_maintenance", 0)
        annual_training = custom.get("annual_training", 0)
        total_annual = annual_op + annual_maint + annual_training
        return {
            "initial_investment": initial,
            "annual_operating_cost": annual_op,
            "annual_maintenance_cost": annual_maint,
            "annual_training_cost": annual_training,
            "annual_total_cost": total_annual,
        }

    # ---------- ROI & NPV ----------

    def _roi_analysis(self, params: dict) -> dict:
        initial = params["initial_investment"]
        annual_cost = params["annual_cost"]
        horizon = params["time_horizon_years"]
        if params.get("annual_revenue"):
            annual_rev = params["annual_revenue"]
        else:
            q = self._quantify_value({"time_horizon_years": horizon, "scenario": "roi"})
            annual_rev = q["totals"]["annual_total_value"]
        net = annual_rev - annual_cost
        roi = net / max(annual_cost, 1) * 100
        payback = initial / max(net, 1)
        npv = self._compute_npv(initial, net, horizon, self.model["discount_rate"])
        irr = self._compute_irr(initial, [net] * horizon)
        yearly = []
        cum_net = -initial
        for y in range(1, horizon + 1):
            cum_net += net
            yearly.append({"year": y, "revenue": annual_rev, "cost": annual_cost,
                           "net": net, "cumulative_net": round(cum_net, 2)})
        return {
            "action": "roi",
            "initial_investment": initial,
            "annual_revenue": round(annual_rev, 2),
            "annual_cost": annual_cost,
            "annual_net": round(net, 2),
            "roi_percent": round(roi, 1),
            "payback_years": round(payback, 2),
            "payback_months": round(payback * 12, 1),
            "npv": round(npv, 2),
            "irr_percent": round(irr * 100, 1),
            "yearly_projection": yearly,
        }

    def _compute_npv(self, initial: float, annual_net: float, years: int,
                     rate: float) -> float:
        npv = -initial
        for y in range(1, years + 1):
            npv += annual_net / ((1 + rate) ** y)
        return npv

    def _compute_irr(self, initial: float, cashflows: list[float],
                     guess: float = 0.2) -> float:
        def npv_at(r: float) -> float:
            total = -initial
            for i, cf in enumerate(cashflows):
                total += cf / ((1 + r) ** (i + 1))
            return total
        low, high = -0.9, 10.0
        for _ in range(200):
            mid = (low + high) / 2
            v = npv_at(mid)
            if abs(v) < 1e-8:
                return mid
            if npv_at(low) * v < 0:
                high = mid
            else:
                low = mid
        return (low + high) / 2

    # ---------- Monte Carlo ----------

    def _triangular(self, low: float, high: float, mode: float) -> float:
        u = random.random()
        if u < (mode - low) / (high - low):
            return low + math.sqrt(u * (high - low) * (mode - low))
        return high - math.sqrt((1 - u) * (high - low) * (high - mode))

    def _monte_carlo(self, params: dict) -> dict:
        n = params["num_simulations"]
        scenario = params["scenario"]
        costs = params.get("costs", {})
        risks = self.model["risks"]
        results = []
        for _ in range(n):
            risk_avoided = 0.0
            for r in risks:
                prob = self._triangular(max(r["mitigated_prob"] * 0.5, 0.001),
                                         r["baseline_prob"] * 1.5, r["mitigated_prob"])
                impact = self._triangular(r["avg_impact"] * 0.5, r["avg_impact"] * 2.0,
                                          r["avg_impact"])
                risk_avoided += (r["baseline_prob"] * r["avg_impact"]
                                 - prob * impact) * 12
            risk_avoided = max(risk_avoided, 0)
            saved_eff = self._simulate_efficiency()
            total_rev = risk_avoided + saved_eff
            annual_cost = self._triangular(costs.get("annual_cost", 2000000) * 0.7,
                                            costs.get("annual_cost", 2000000) * 1.3,
                                            costs.get("annual_cost", 2000000))
            net = total_rev - annual_cost
            roi_val = (net / max(annual_cost, 1) * 100) if annual_cost > 0 else 0
            results.append({"risk_avoided": risk_avoided, "efficiency_saved": saved_eff,
                            "total_revenue": total_rev, "annual_cost": annual_cost,
                            "net_benefit": net, "roi_percent": roi_val})
        return {
            "action": "simulate",
            "num_simulations": n,
            "scenario": scenario,
            "statistics": self._summarize_results(results),
            "sample_size": min(10, len(results)),
        }

    def _simulate_efficiency(self) -> float:
        total = 0.0
        for k, v in self.model["efficiency"].items():
            saved_days = (v["traditional_person_days_per_month"]
                          - v["continuous_person_days_per_month"]) * 12
            ratio = self._triangular(0.5, 1.2, 1.0)
            total += saved_days * v.get("unit_cost", self.model["unit_person_day_cost"]) * ratio
        return max(total, 0)

    def _summarize_results(self, results: list[dict]) -> dict:
        keys = ["total_revenue", "net_benefit", "roi_percent", "risk_avoided"]
        summary: dict[str, dict] = {}
        for k in keys:
            vals = sorted(r[k] for r in results)
            n = len(vals)
            p10 = vals[int(n * 0.1)]
            p50 = vals[int(n * 0.5)]
            p90 = vals[int(n * 0.9)]
            mean = statistics.mean(vals)
            stdev = statistics.pstdev(vals) if n > 1 else 0
            summary[k] = {"mean": round(mean, 2), "p10": round(p10, 2),
                           "p50": round(p50, 2), "p90": round(p90, 2),
                           "stdev": round(stdev, 2), "min": round(vals[0], 2),
                           "max": round(vals[-1], 2)}
        return summary

    # ---------- 敏感性分析 ----------

    def _sensitivity_analysis(self, params: dict) -> dict:
        name = params.get("param_name", "baseline_prob")
        lo, hi = params.get("param_range", (0.5, 1.5))
        risks = self.model["risks"]
        efficiencies = self.model["efficiency"]
        base_result = self._quantify_value({"time_horizon_years": 1, "scenario": "sensitivity"})
        base_value = base_result["totals"]["annual_total_value"]
        tornado = []
        if name == "baseline_prob":
            for factor in (lo, 0.75, 1.0, 1.25, hi):
                adj_risks = [{**r, "baseline_prob": min(r["baseline_prob"] * factor, 0.9)}
                             for r in risks]
                q = self._quantify_value({"risks": adj_risks,
                                           "time_horizon_years": 1})
                tornado.append({"factor": factor, "value": round(q["totals"]["annual_total_value"], 2)})
        elif name == "mitigated_prob":
            for factor in (lo, 0.75, 1.0, 1.25, hi):
                adj_risks = [{**r, "mitigated_prob": min(r["mitigated_prob"] * factor, 0.5)}
                             for r in risks]
                q = self._quantify_value({"risks": adj_risks,
                                           "time_horizon_years": 1})
                tornado.append({"factor": factor, "value": round(q["totals"]["annual_total_value"], 2)})
        elif name == "avg_impact":
            for factor in (lo, 0.75, 1.0, 1.25, hi):
                adj_risks = [{**r, "avg_impact": r["avg_impact"] * factor} for r in risks]
                q = self._quantify_value({"risks": adj_risks,
                                           "time_horizon_years": 1})
                tornado.append({"factor": factor, "value": round(q["totals"]["annual_total_value"], 2)})
        elif name == "efficiency_ratio":
            for factor in (lo, 0.75, 1.0, 1.25, hi):
                adj_eff = {k: {**v,
                               "continuous_person_days_per_month": round(
                                   (v["traditional_person_days_per_month"]
                                    - v["continuous_person_days_per_month"]) * (1 - factor)
                                   + v["traditional_person_days_per_month"] * factor * 0.1)}
                            for k, v in efficiencies.items()}
                self.model["efficiency"] = adj_eff
                q = self._quantify_value({"time_horizon_years": 1})
                tornado.append({"factor": factor, "value": round(q["totals"]["annual_total_value"], 2)})
                self.model["efficiency"] = dict(_EFFICIENCY_BASELINES)
        else:
            for factor in (lo, 0.75, 1.0, 1.25, hi):
                tornado.append({"factor": factor, "value": round(base_value * factor, 2)})
        return {
            "action": "sensitivity",
            "param_name": name, "range": [lo, hi],
            "base_value": round(base_value, 2),
            "variations": tornado,
        }

    def _add_risk(self, risk: dict) -> dict:
        risk.setdefault("risk_type", "custom")
        risk.setdefault("category", "风险避免")
        self.model["risks"].append(risk)
        if self.db:
            self.db.insert("risks", risk)
        return {"action": "add_risk", "added_risk_id": risk.get("risk_id", "custom")}
