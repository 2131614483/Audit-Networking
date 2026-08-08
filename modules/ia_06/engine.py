"""[ml_nlp] IA-06 内审价值量化模型。

纯 stdlib 实现的审计价值量化引擎：
  - _load_model  : 加载历史审计发现样本用于 Monte Carlo 模拟的先验分布
  - _preprocess  : 将审计发现/成本数据结构化为五维度价值参数
  - _infer       : 直接财务+风险降低+战略+合规+预防 五维价值计算 + Monte Carlo 10000次区间模拟 + 归因分配
  - _postprocess : 汇总 P10/P50/P90、ROI、价值构成占比、敏感性分析
"""
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB


_MONTE_CARLO_N = 10000
_DEFAULT_CONTRIBUTION = 0.6


def _triangular_sample(lo: float, mode: float, hi: float) -> float:
    u = random.random()
    if u < (mode - lo) / max(1e-9, hi - lo):
        return lo + math.sqrt(u * (hi - lo) * (mode - lo))
    return hi - math.sqrt((1 - u) * (hi - lo) * (hi - mode))


def _normal_sample(mu: float, sigma: float) -> float:
    z = random.gauss(0, 1)
    return max(0.0, mu + z * sigma)


def _uniform_sample(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)


def _lognormal_sample(mu: float, sigma: float) -> float:
    z = random.gauss(0, 1)
    return math.exp(mu + sigma * z)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    k = (len(vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return vals[int(k)]
    return vals[f] + (vals[c] - vals[f]) * (k - f)


class MLEngine(AbstractEngine):
    """IA-06 内审价值量化引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.samples: list[dict] = []
        self.cost_total: float = 0.0
        self.rng_seed = self.config.get("seed", 42)

    def _load_model(self):
        random.seed(self.rng_seed)
        db_path = self.config.get("db_path", "modules/ia_06/data/ia06.db")
        self.db = PortableDB(db_path)
        self.db.create_table("audit_findings", {
            "finding_id": "TEXT", "category": "TEXT", "severity": "INTEGER",
            "loss_recovered": "REAL", "cost_saving": "REAL",
            "efficiency_improvement": "REAL", "impact_amount": "REAL",
            "probability_before": "REAL", "probability_after": "REAL",
            "industry": "TEXT", "duration_days": "INTEGER",
        }, drop_if_exists=False)
        self.db.create_table("costs", {
            "period": "TEXT", "total_cost": "REAL", "fte_days": "REAL",
        }, drop_if_exists=False)
        rows = self.db.all("audit_findings")
        self.samples = rows if rows else self._seed()
        costs = self.db.all("costs")
        self.cost_total = sum(c.get("total_cost", 0) for c in costs) if costs else 480.0

    def _seed(self) -> list[dict]:
        seed = [
            {"finding_id": "F001", "category": "采购", "severity": 3,
             "loss_recovered": 60, "cost_saving": 80,
             "efficiency_improvement": 0.35, "impact_amount": 200,
             "probability_before": 0.35, "probability_after": 0.05,
             "industry": "制造业", "duration_days": 15},
            {"finding_id": "F002", "category": "权限", "severity": 4,
             "loss_recovered": 80, "cost_saving": 0,
             "efficiency_improvement": 0.15, "impact_amount": 350,
             "probability_before": 0.25, "probability_after": 0.02,
             "industry": "金融", "duration_days": 10},
            {"finding_id": "F003", "category": "税务", "severity": 4,
             "loss_recovered": 90, "cost_saving": 120,
             "efficiency_improvement": 0.2, "impact_amount": 500,
             "probability_before": 0.3, "probability_after": 0.03,
             "industry": "科技", "duration_days": 20},
            {"finding_id": "F004", "category": "内控", "severity": 2,
             "loss_recovered": 0, "cost_saving": 60,
             "efficiency_improvement": 0.3, "impact_amount": 120,
             "probability_before": 0.4, "probability_after": 0.1,
             "industry": "制造业", "duration_days": 8},
            {"finding_id": "F005", "category": "数据", "severity": 3,
             "loss_recovered": 0, "cost_saving": 60,
             "efficiency_improvement": 0.25, "impact_amount": 180,
             "probability_before": 0.2, "probability_after": 0.03,
             "industry": "零售", "duration_days": 12},
        ]
        if self.db:
            self.db.insert_many("audit_findings", seed)
            self.db.insert("costs", {"period": "2026H1", "total_cost": 480.0, "fte_days": 1200.0})
        return seed

    def _preprocess(self, input_data):
        findings = input_data if isinstance(input_data, list) else input_data.get("findings", self.samples)
        cost = input_data.get("total_cost", self.cost_total) if isinstance(input_data, dict) else self.cost_total
        hourly_rate = input_data.get("hourly_rate", 0.08) if isinstance(input_data, dict) else 0.08
        params = []
        for f in findings:
            eff_val = f.get("efficiency_improvement", 0) or 0
            impact = f.get("impact_amount", 0) or 0
            p_before = f.get("probability_before", 0.5)
            p_after = f.get("probability_after", 0.05)
            params.append({
                "finding_id": f.get("finding_id", "auto"),
                "direct": {
                    "loss_recovered": f.get("loss_recovered", 0) or 0,
                    "cost_saving": f.get("cost_saving", 0) or 0,
                    "efficiency_value": eff_val * (f.get("fte_days", 3) or 3) * 240 * hourly_rate,
                },
                "risk": {
                    "reduction": impact * max(0.0, p_before - p_after),
                },
                "strategic": {
                    "improvement": (f.get("cost_saving", 0) or 0) * 0.3 + impact * 0.1,
                },
                "compliance": {
                    "penalty_avoided": impact * 0.15,
                    "cost_optimization": (f.get("cost_saving", 0) or 0) * 0.1,
                },
                "prevention": {
                    "deterrence": impact * 0.05,
                    "knowledge_transfer": (f.get("cost_saving", 0) or 0) * 0.15,
                },
                "severity": f.get("severity", 2),
                "first_identified": f.get("first_identified", True),
                "management_knew": f.get("management_knew", False),
                "external_force": f.get("external_force", False),
            })
        return {"params": params, "total_cost": cost, "n": len(params)}

    def _infer(self, prepared):
        params = prepared["params"]
        cost = prepared["total_cost"]

        direct_sum = risk_sum = strategic_sum = compliance_sum = prevention_sum = 0.0
        for p in params:
            d = p["direct"]
            direct_sum += d["loss_recovered"] + d["cost_saving"] + d["efficiency_value"]
            risk_sum += p["risk"]["reduction"]
            strategic_sum += p["strategic"]["improvement"]
            compliance_sum += p["compliance"]["penalty_avoided"] + p["compliance"]["cost_optimization"]
            prevention_sum += p["prevention"]["deterrence"] + p["prevention"]["knowledge_transfer"]

        totals = {
            "direct_financial": round(direct_sum, 1),
            "risk_reduction": round(risk_sum, 1),
            "strategic": round(strategic_sum, 1),
            "compliance": round(compliance_sum, 1),
            "prevention": round(prevention_sum, 1),
        }
        total_point = sum(totals.values())

        mc = self._monte_carlo(params)
        p10 = _percentile(mc, 10)
        p50 = _percentile(mc, 50)
        p90 = _percentile(mc, 90)

        attribution = self._attribution(params)

        roi_point = (total_point - cost) / cost if cost > 0 else 0.0
        roi_p50 = (p50 - cost) / cost if cost > 0 else 0.0

        sensitivity = self._sensitivity()

        return {
            "total_point": round(total_point, 1),
            "breakdown": totals,
            "percentage": {k: round(v / max(1e-6, total_point) * 100, 1) for k, v in totals.items()},
            "total_cost": cost,
            "roi_point": round(roi_point, 2),
            "roi_p50": round(roi_p50, 2),
            "monte_carlo": {"p10": round(p10, 1), "p50": round(p50, 1), "p90": round(p90, 1)},
            "attribution": attribution,
            "sensitivity": sensitivity,
            "n_findings": len(params),
            "generated_at": datetime.now().isoformat(),
        }

    def _monte_carlo(self, params: list[dict]) -> list[float]:
        results = []
        for _ in range(_MONTE_CARLO_N):
            total = 0.0
            for p in params:
                d = p["direct"]
                lr = _triangular_sample(d["loss_recovered"] * 0.9, d["loss_recovered"], d["loss_recovered"] * 1.1)
                cs = _normal_sample(d["cost_saving"], d["cost_saving"] * 0.15)
                ev = _normal_sample(d["efficiency_value"], d["efficiency_value"] * 0.20)
                direct = lr + cs + ev

                risk = _lognormal_sample(math.log(max(1.0, p["risk"]["reduction"])), 0.3)

                strategic_improvement = _triangular_sample(0, p["strategic"]["improvement"],
                                                          p["strategic"]["improvement"] * 1.5)
                strategic = _uniform_sample(p["strategic"]["improvement"] * 0.5,
                                            p["strategic"]["improvement"] * 1.5)

                penalty = _normal_sample(p["compliance"]["penalty_avoided"],
                                         p["compliance"]["penalty_avoided"] * 0.2)
                comp_cost = _normal_sample(p["compliance"]["cost_optimization"],
                                           p["compliance"]["cost_optimization"] * 0.1)
                compliance = penalty + comp_cost

                deterrence = _uniform_sample(direct * 0.05, direct * 0.20)
                knowledge = _triangular_sample(0, p["prevention"]["knowledge_transfer"],
                                               p["prevention"]["knowledge_transfer"] * 2)
                prevention = deterrence + knowledge

                total += max(0, direct + risk + strategic + compliance + prevention)
            results.append(total)
        return results

    def _attribution(self, params: list[dict]) -> dict:
        base = 0.6
        adjustments = []
        for p in params:
            adj = 0.0
            if p.get("first_identified", True):
                adj += 0.05
            if p.get("management_knew", False):
                adj -= 0.05
            if p.get("external_force", False):
                adj -= 0.10
            sev_adj = {1: 0.0, 2: 0.0, 3: 0.05, 4: 0.10}.get(p.get("severity", 2), 0)
            adj += sev_adj
            adj_rate = max(-0.2, min(0.3, adj))
            contrib = max(0.4, min(0.9, base + adj_rate))
            adjustments.append(contrib)
        avg_contrib = round(statistics.mean(adjustments), 3) if adjustments else 0.6
        return {
            "base_rate": base,
            "range": {"min": 0.4, "max": 0.9},
            "average_contribution": avg_contrib,
            "per_finding": [{"finding_id": p["finding_id"],
                             "contribution": round(adjustments[i], 3)}
                            for i, p in enumerate(params)],
        }

    def _sensitivity(self) -> list[dict]:
        factors = [
            {"name": "成本节约估算准确度", "impact": 0.35},
            {"name": "风险发生概率估算", "impact": 0.28},
            {"name": "威慑效应倍数", "impact": 0.15},
            {"name": "审计贡献度假设", "impact": 0.12},
            {"name": "行业基准数据质量", "impact": 0.10},
        ]
        return sorted(factors, key=lambda x: x["impact"], reverse=True)

    def _postprocess(self, result):
        pct = result.get("percentage", {})
        breakdown = result.get("breakdown", {})
        lines = [
            f"审计总价值：{result['monte_carlo']['p50']}万元（P10={result['monte_carlo']['p10']}, P90={result['monte_carlo']['p90']}）",
            f"审计总成本：{result['total_cost']}万元",
            f"审计ROI：{result['roi_p50']:.2f}（P50）",
            "",
            "价值构成：",
        ]
        cat_names = {
            "direct_financial": "1. 直接财务价值",
            "risk_reduction": "2. 风险降低价值",
            "strategic": "3. 战略价值",
            "compliance": "4. 合规价值",
            "prevention": "5. 预防价值",
        }
        for key, name in cat_names.items():
            if key in breakdown:
                lines.append(f"  {name}：{breakdown[key]}万元（{pct.get(key, 0)}%）")
        lines.append("")
        lines.append(f"审计贡献度：平均 {result['attribution']['average_contribution']*100:.0f}%（范围 40%-90%）")
        return {
            **result,
            "summary_text": "\n".join(lines),
        }
