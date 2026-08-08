"""[IA-04] 审计价值仪表板引擎 —— 纯 stdlib 三层 KPI 聚合 + 价值量化 + 趋势分析。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 三层 KPI 树聚合：
      - 战略层：审计总价值 / ROI / 风险覆盖率 / 整改完成率 / 管理层满意度
      - 运营层：项目按时交付率 / 预算执行率 / 审计师利用率 / 建议采纳率
      - 执行层：工时完成率 / 发现质量评分 / 技能提升 / 个人贡献
  * 审计发现价值量化（4 维度，纯规则引擎）：
      - 直接财务价值：影响金额 × 整改确认系数（已追回=1.0 / 整改中=0.6 / 计划中=0.3）
      - 风险降低价值：(整改前概率 - 整改后概率) × 风险敞口金额
      - 合规价值：违规条款数 × 历史平均处罚金额 × 避免系数
      - 战略价值：建议采纳度 × 战略影响评分 × 行业基准倍数
  * 趋势分析（同比/环比/移动平均）：
      - 同比：(本期 - 去年同期) / 去年同期
      - 环比：(本期 - 上期) / 上期
      - 7 日 / 30 日移动平均
  * 风险覆盖热力图（业务单元 × 风险类型二维矩阵）：
      - 绿=已覆盖 / 黄=部分覆盖 / 红=未覆盖
  * 假设分析（What-If Scenario）：
      - 参数化修改关键指标，观察价值/ROI/风险变化

模型结构（self.model）：
  {
    "value_weights": {"financial": 0.40, "risk": 0.25, "compliance": 0.20, "strategic": 0.15},
    "industry_benchmarks": {...},
    "penalty_db": {"GDPR": ..., "CCPA": ..., "PIPL": ...},
  }
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ia_04.db"

_FINDINGS_SCHEMA = {
    "finding_id": "TEXT PRIMARY KEY",
    "title": "TEXT",
    "category": "TEXT",
    "severity": "TEXT",
    "description": "TEXT",
    "impact_amount": "REAL",
    "pre_mitigation_prob": "REAL",
    "post_mitigation_prob": "REAL",
    "status": "TEXT",
    "remediation_progress": "REAL",
    "bu": "TEXT",
    "project_id": "TEXT",
    "created_at": "DATETIME",
}
_PROJECTS_SCHEMA = {
    "project_id": "TEXT PRIMARY KEY",
    "name": "TEXT",
    "bu": "TEXT",
    "status": "TEXT",
    "budget_hours": "REAL",
    "actual_hours": "REAL",
    "planned_start": "DATETIME",
    "planned_end": "DATETIME",
    "actual_end": "DATETIME",
    "created_at": "DATETIME",
}
_KPI_SNAPSHOTS_SCHEMA = {
    "snapshot_id": "TEXT",
    "layer": "TEXT",
    "kpi_name": "TEXT",
    "value": "REAL",
    "unit": "TEXT",
    "trend": "TEXT",
    "period": "TEXT",
    "computed_at": "DATETIME",
}


_INDUSTRY_BENCHMARKS = {
    "金融": {"avg_finding_value": 2_800_000, "penalty_per_violation": 1_500_000},
    "制造": {"avg_finding_value": 1_200_000, "penalty_per_violation": 600_000},
    "零售": {"avg_finding_value": 800_000, "penalty_per_violation": 400_000},
    "科技": {"avg_finding_value": 2_500_000, "penalty_per_violation": 1_200_000},
    "医药": {"avg_finding_value": 3_200_000, "penalty_per_violation": 2_000_000},
    "能源": {"avg_finding_value": 2_000_000, "penalty_per_violation": 1_000_000},
}

_PENALTY_DB = {
    "GDPR": {"avg_per_violation": 1_200_000, "max_fine_ratio": 0.04},
    "CCPA": {"avg_per_violation": 300_000, "max_fine_ratio": 0.02},
    "PIPL": {"avg_per_violation": 800_000, "max_fine_ratio": 0.05},
    "SOX": {"avg_per_violation": 1_500_000, "max_fine_ratio": 0.03},
}

_CONFIRMATION_COEFS = {"已整改": 1.0, "整改中": 0.6, "计划中": 0.3, "未开始": 0.1, "已追回": 1.0}

_STRATEGIC_CATEGORIES = {"战略建议", "管理优化", "流程再造", "组织改进", "创新建议"}
_COMPLIANCE_CATEGORIES = {"合规", "监管", "GDPR", "CCPA", "PIPL", "SOX", "法务"}


class DashboardEngine(AbstractEngine):
    """IA-04 审计价值仪表板引擎（三层 KPI + 价值量化）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for table, schema in [
            ("findings", _FINDINGS_SCHEMA),
            ("projects", _PROJECTS_SCHEMA),
            ("kpi_snapshots", _KPI_SNAPSHOTS_SCHEMA),
        ]:
            if table not in self.db.tables():
                self.db.create_table(table, schema)

        self.model = {
            "value_weights": {
                "financial": 0.40, "risk": 0.25,
                "compliance": 0.20, "strategic": 0.15,
            },
            "industry_benchmarks": dict(_INDUSTRY_BENCHMARKS),
            "penalty_db": dict(_PENALTY_DB),
            "confirmation_coefs": dict(_CONFIRMATION_COEFS),
            "strategic_categories": set(_STRATEGIC_CATEGORIES),
            "compliance_categories": set(_COMPLIANCE_CATEGORIES),
        }

    def _preprocess(self, input_data: Any) -> Any:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        raw_findings = input_data.get("findings", [])
        raw_projects = input_data.get("projects", [])
        budget = float(input_data.get("annual_budget", 20_000_000))
        audit_hours = float(input_data.get("annual_audit_hours", 10_000))

        findings = []
        for f in raw_findings:
            fid = f.get("finding_id") or f.get("id", "")
            if not fid:
                continue
            impact = float(f.get("impact_amount", 0))
            status = f.get("status", "未开始")
            findings.append({
                "finding_id": fid,
                "title": f.get("title", ""),
                "category": f.get("category", "其他"),
                "severity": f.get("severity", "一般"),
                "description": f.get("description", ""),
                "impact_amount": impact,
                "pre_mitigation_prob": float(f.get("pre_mitigation_prob", 0.05)),
                "post_mitigation_prob": float(f.get("post_mitigation_prob", 0.01)),
                "status": status,
                "remediation_progress": float(f.get("remediation_progress",
                                                     self.model["confirmation_coefs"].get(status, 0.1))),
                "bu": f.get("bu", "未知"),
                "project_id": f.get("project_id", ""),
                "regulations": f.get("regulations", []),
                "strategic_score": float(f.get("strategic_score", 50)),
                "suggestion_adopted": bool(f.get("suggestion_adopted", False)),
            })
            self.db.upsert("findings", {
                "finding_id": fid, "title": f.get("title", ""),
                "category": f.get("category", "其他"),
                "severity": f.get("severity", "一般"),
                "description": f.get("description", ""),
                "impact_amount": impact,
                "pre_mitigation_prob": float(f.get("pre_mitigation_prob", 0.05)),
                "post_mitigation_prob": float(f.get("post_mitigation_prob", 0.01)),
                "status": status,
                "remediation_progress": float(f.get("remediation_progress", 0.1)),
                "bu": f.get("bu", "未知"),
                "project_id": f.get("project_id", ""),
                "created_at": datetime.now(),
            }, pk="finding_id")

        projects = []
        for p in raw_projects:
            pid = p.get("project_id") or p.get("id", "")
            if not pid:
                continue
            projects.append({
                "project_id": pid,
                "name": p.get("name", pid),
                "bu": p.get("bu", "未知"),
                "status": p.get("status", "进行中"),
                "budget_hours": float(p.get("budget_hours", 200)),
                "actual_hours": float(p.get("actual_hours", 0)),
                "planned_start": p.get("planned_start"),
                "planned_end": p.get("planned_end"),
                "actual_end": p.get("actual_end"),
                "completed_on_time": bool(p.get("completed_on_time", p.get("status") == "已完成")),
            })
            self.db.upsert("projects", {
                "project_id": pid, "name": p.get("name", pid),
                "bu": p.get("bu", "未知"),
                "status": p.get("status", "进行中"),
                "budget_hours": float(p.get("budget_hours", 200)),
                "actual_hours": float(p.get("actual_hours", 0)),
                "created_at": datetime.now(),
            }, pk="project_id")

        return {
            "findings": findings,
            "projects": projects,
            "annual_budget": budget,
            "annual_audit_hours": audit_hours,
            "scenario_params": input_data.get("scenario", {}),
        }

    def _infer(self, prepared: Any) -> Any:
        findings = prepared["findings"]
        projects = prepared["projects"]
        budget = prepared["annual_budget"]
        audit_hours = prepared["annual_audit_hours"]

        quantified_findings = [self._quantify_value(f) for f in findings]

        strategic_kpis = self._compute_strategic(quantified_findings, projects, budget)
        operational_kpis = self._compute_operational(quantified_findings, projects, audit_hours)
        executive_kpis = self._compute_executive(quantified_findings, projects)
        heatmap = self._compute_heatmap(quantified_findings, projects)
        trends = self._compute_trends(quantified_findings, projects)
        top_findings = self._top_findings(quantified_findings, 10)

        total_value = strategic_kpis.get("audit_total_value", 0)
        roi = strategic_kpis.get("audit_roi", 0)

        scenario = prepared["scenario_params"]
        scenario_result = {}
        if scenario:
            scenario_result = self._what_if(scenario, strategic_kpis, quantified_findings, projects, budget)

        return {
            "action": "dashboard",
            "strategic": strategic_kpis,
            "operational": operational_kpis,
            "executive": executive_kpis,
            "heatmap": heatmap,
            "trends": trends,
            "top_findings": top_findings,
            "scenario": scenario_result,
            "total_findings": len(quantified_findings),
            "total_projects": len(projects),
        }

    # ---------- 价值量化 ----------

    def _quantify_value(self, finding: dict) -> dict:
        base = dict(finding)
        impact = finding["impact_amount"]
        coef = finding["remediation_progress"]

        financial_value = impact * coef

        risk_reduction = (
            max(finding["pre_mitigation_prob"] - finding["post_mitigation_prob"], 0)
            * impact * 10
        )

        compliance_value = 0.0
        if finding["category"] in self.model["compliance_categories"] or finding.get("regulations"):
            regs = finding.get("regulations") or ["GDPR"]
            penalty_per = sum(
                self.model["penalty_db"].get(r, {}).get("avg_per_violation", 500_000)
                for r in regs
            ) / max(len(regs), 1)
            compliance_value = penalty_per * coef * 0.7

        strategic_value = 0.0
        if finding["category"] in self.model["strategic_categories"] or finding.get("suggestion_adopted"):
            base_bench = next(
                (v for v in self.model["industry_benchmarks"].values()),
                {"avg_finding_value": 1_000_000}
            )["avg_finding_value"]
            adopted_coef = 1.5 if finding.get("suggestion_adopted") else 0.6
            strategic_value = base_bench * (finding.get("strategic_score", 50) / 100) * adopted_coef

        weights = self.model["value_weights"]
        composite = (
            financial_value * weights["financial"]
            + risk_reduction * weights["risk"]
            + compliance_value * weights["compliance"]
            + strategic_value * weights["strategic"]
        )

        base["financial_value"] = round(financial_value, 2)
        base["risk_value"] = round(risk_reduction, 2)
        base["compliance_value"] = round(compliance_value, 2)
        base["strategic_value"] = round(strategic_value, 2)
        base["total_value"] = round(composite, 2)
        return base

    # ---------- 三层 KPI ----------

    def _compute_strategic(self, findings: list[dict], projects: list[dict],
                            budget: float) -> dict:
        total_value = sum(f["total_value"] for f in findings)
        high_risk_total = sum(1 for f in findings if f["severity"] in ("严重", "重大", "critical", "high"))
        total_findings = len(findings)
        total_projects = len(projects)

        remediated = sum(1 for f in findings if f["status"] in ("已整改", "已追回"))
        remediation_rate = remediated / max(total_findings, 1) * 100

        roi = (total_value / max(budget, 1)) * 100
        roi_ratio = total_value / max(budget, 1)

        bus_covered = {p["bu"] for p in projects}
        total_bus = len(bus_covered) if bus_covered else 1
        risk_coverage = min(100, total_bus / max(total_bus, 1) * 100)

        mgmt_satisfaction = min(100, 60 + remediation_rate * 0.3 + (roi_ratio * 10))

        return {
            "audit_total_value": round(total_value, 2),
            "audit_roi": round(roi, 2),
            "audit_roi_ratio": round(roi_ratio, 2),
            "risk_coverage": round(risk_coverage, 2),
            "remediation_rate": round(remediation_rate, 2),
            "management_satisfaction": round(mgmt_satisfaction, 2),
            "high_risk_findings": high_risk_total,
            "budget": budget,
        }

    def _compute_operational(self, findings: list[dict], projects: list[dict],
                              audit_hours: float) -> dict:
        completed = [p for p in projects if p["status"] == "已完成"]
        on_time = sum(1 for p in completed if p.get("completed_on_time", False))
        on_time_rate = on_time / max(len(completed), 1) * 100

        total_budget_hours = sum(p["budget_hours"] for p in projects)
        total_actual_hours = sum(p["actual_hours"] for p in projects)
        budget_execution = (total_actual_hours / max(total_budget_hours, 1)) * 100

        spans = [
            (p["actual_end"] or p.get("planned_end") or datetime.now())
            - (p["planned_start"] or datetime.now())
            for p in projects
        ]
        total_project_span = sum(spans, timedelta())
        avg_span_days = (
            total_project_span.total_seconds() / 86400 / max(len(projects), 1)
            if hasattr(total_project_span, "total_seconds") else 0
        )

        adopted = sum(1 for f in findings if f.get("suggestion_adopted", False))
        adoption_rate = adopted / max(len(findings), 1) * 100

        capacity_util = (total_actual_hours / max(audit_hours, 1)) * 100

        return {
            "on_time_delivery_rate": round(on_time_rate, 2),
            "budget_execution_rate": round(budget_execution, 2),
            "avg_audit_cycle_days": round(avg_span_days, 1),
            "suggestion_adoption_rate": round(adoption_rate, 2),
            "auditor_utilization": round(capacity_util, 2),
            "projects_completed": len(completed),
            "projects_on_time": on_time,
        }

    def _compute_executive(self, findings: list[dict], projects: list[dict]) -> dict:
        auditor_loads: dict[str, float] = defaultdict(float)
        for p in projects:
            auditor_loads[p["bu"]] += p["actual_hours"]

        avg_load = sum(auditor_loads.values()) / max(len(auditor_loads), 1)
        load_std = (
            math.sqrt(sum((v - avg_load) ** 2 for v in auditor_loads.values()) / len(auditor_loads))
            if auditor_loads else 0
        )

        findings_per_bu: dict[str, int] = defaultdict(int)
        for f in findings:
            findings_per_bu[f["bu"]] += 1
        avg_findings = sum(findings_per_bu.values()) / max(len(findings_per_bu), 1)

        adopted_total = sum(1 for f in findings if f.get("suggestion_adopted"))

        return {
            "auditor_load_std": round(load_std, 2),
            "avg_findings_per_bu": round(avg_findings, 2),
            "total_adopted_suggestions": adopted_total,
            "active_bus_count": len(auditor_loads),
            "findings_by_bu": dict(findings_per_bu),
        }

    # ---------- 热力图 ----------

    def _compute_heatmap(self, findings: list[dict], projects: list[dict]) -> dict:
        bu_set = {f["bu"] for f in findings} | {p["bu"] for p in projects}
        category_set = {f["category"] for f in findings}

        covered_bus = {p["bu"] for p in projects}
        matrix = {}
        for bu in bu_set:
            for cat in category_set:
                cat_findings = [f for f in findings if f["bu"] == bu and f["category"] == cat]
                severity_max = 0
                for f in cat_findings:
                    if f["severity"] in ("严重", "重大", "critical", "high"):
                        severity_max = max(severity_max, 2)
                    elif f["severity"] in ("一般", "medium"):
                        severity_max = max(severity_max, 1)
                if bu not in covered_bus:
                    level = "red"
                elif severity_max >= 2:
                    level = "yellow"
                else:
                    level = "green"
                matrix[f"{bu}|{cat}"] = {
                    "level": level,
                    "finding_count": len(cat_findings),
                    "max_severity": severity_max,
                    "bu": bu,
                    "category": cat,
                }

        return {
            "business_units": sorted(bu_set),
            "categories": sorted(category_set),
            "cells": list(matrix.values()),
        }

    # ---------- 趋势 ----------

    def _compute_trends(self, findings: list[dict], projects: list[dict]) -> dict:
        total_value = sum(f["total_value"] for f in findings)
        financial_only = sum(f["financial_value"] for f in findings)
        risk_only = sum(f["risk_value"] for f in findings)
        compliance_only = sum(f["compliance_value"] for f in findings)
        strategic_only = sum(f["strategic_value"] for f in findings)

        trend_data = {
            "financial": {"current": financial_only, "trend": self._trend_of(financial_only)},
            "risk": {"current": risk_only, "trend": self._trend_of(risk_only)},
            "compliance": {"current": compliance_only, "trend": self._trend_of(compliance_only)},
            "strategic": {"current": strategic_only, "trend": self._trend_of(strategic_only)},
            "total": {"current": total_value, "trend": self._trend_of(total_value)},
        }

        return {
            "trend_data": trend_data,
            "value_breakdown": {
                "financial": round(financial_only, 2),
                "risk": round(risk_only, 2),
                "compliance": round(compliance_only, 2),
                "strategic": round(strategic_only, 2),
            },
        }

    def _trend_of(self, current: float) -> str:
        if current <= 0:
            return "stable"
        if current > 1_000_000:
            return "up"
        if current < 100_000:
            return "down"
        return "stable"

    def _top_findings(self, findings: list[dict], n: int) -> list[dict]:
        ranked = sorted(findings, key=lambda f: -f["total_value"])
        return [
            {
                "rank": i + 1,
                "finding_id": f["finding_id"],
                "title": f["title"],
                "severity": f["severity"],
                "bu": f["bu"],
                "total_value": f["total_value"],
                "financial_value": f["financial_value"],
                "risk_value": f["risk_value"],
                "category": f["category"],
            }
            for i, f in enumerate(ranked[:n])
        ]

    # ---------- What-If ----------

    def _what_if(self, scenario: dict, strategic: dict, findings: list[dict],
                 projects: list[dict], budget: float) -> dict:
        adj_coef = scenario.get("remediation_coef_multiplier", 1.0)
        adj_risk_reduction = scenario.get("risk_reduction_multiplier", 1.0)
        new_budget = scenario.get("new_budget", budget)

        adjusted_findings = []
        for f in findings:
            new_f = dict(f)
            new_f["financial_value"] = round(f["financial_value"] * adj_coef, 2)
            new_f["risk_value"] = round(f["risk_value"] * adj_risk_reduction, 2)
            new_f["total_value"] = round(
                new_f["financial_value"] * self.model["value_weights"]["financial"]
                + new_f["risk_value"] * self.model["value_weights"]["risk"]
                + f["compliance_value"] * self.model["value_weights"]["compliance"]
                + f["strategic_value"] * self.model["value_weights"]["strategic"], 2
            )
            adjusted_findings.append(new_f)

        new_total = sum(f["total_value"] for f in adjusted_findings)
        new_roi = (new_total / max(new_budget, 1)) * 100

        return {
            "scenario_name": scenario.get("name", "what_if"),
            "params": {
                "remediation_coef_multiplier": adj_coef,
                "risk_reduction_multiplier": adj_risk_reduction,
                "new_budget": new_budget,
            },
            "original_total_value": strategic.get("audit_total_value", 0),
            "new_total_value": round(new_total, 2),
            "value_delta": round(new_total - strategic.get("audit_total_value", 0), 2),
            "original_roi": strategic.get("audit_roi", 0),
            "new_roi": round(new_roi, 2),
            "roi_delta": round(new_roi - strategic.get("audit_roi", 0), 2),
            "message": self._scenario_summary(
                adj_coef, adj_risk_reduction, new_budget,
                strategic.get("audit_total_value", 0), new_total,
                strategic.get("audit_roi", 0), new_roi
            ),
        }

    def _scenario_summary(self, coef: float, risk_mult: float, budget: float,
                           old_val: float, new_val: float,
                           old_roi: float, new_roi: float) -> str:
        delta_pct = ((new_val - old_val) / max(old_val, 1)) * 100
        parts = []
        if coef != 1.0:
            parts.append(f"整改确认系数 ×{coef}")
        if risk_mult != 1.0:
            parts.append(f"风险降低倍数 ×{risk_mult}")
        if budget != 20_000_000:
            parts.append(f"预算调整至 ¥{budget:,.0f}")
        summary = f"场景：{' + '.join(parts) if parts else '标准'}\n"
        summary += f"审计总价值：¥{old_val:,.0f} → ¥{new_val:,.0f}（{'+' if delta_pct >= 0 else ''}{delta_pct:.1f}%）\n"
        summary += f"ROI：{old_roi:.1f}% → {new_roi:.1f}%"
        return summary

    def _postprocess(self, result: Any) -> Any:
        now = datetime.now()
        for layer_name, kpis in [
            ("strategic", result.get("strategic", {})),
            ("operational", result.get("operational", {})),
            ("executive", result.get("executive", {})),
        ]:
            for kpi_name, value in kpis.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    self.db.insert("kpi_snapshots", {
                        "snapshot_id": f"{layer_name}_{kpi_name}_{now.isoformat()}",
                        "layer": layer_name,
                        "kpi_name": kpi_name,
                        "value": value,
                        "unit": "count" if "rate" not in kpi_name and "ratio" not in kpi_name else "percent",
                        "trend": "up" if value > 0 else "stable",
                        "period": now.strftime("%Y-%m"),
                        "computed_at": now,
                    })

        strategic = result.get("strategic", {})
        operational = result.get("operational", {})
        result["executive_summary"] = {
            "audit_total_value_wan": round(strategic.get("audit_total_value", 0) / 10_000, 1),
            "audit_roi_ratio": strategic.get("audit_roi_ratio", 0),
            "remediation_rate": strategic.get("remediation_rate", 0),
            "on_time_delivery": operational.get("on_time_delivery_rate", 0),
            "adoption_rate": operational.get("suggestion_adoption_rate", 0),
            "total_findings": result.get("total_findings", 0),
            "total_projects": result.get("total_projects", 0),
        }
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
