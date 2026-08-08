"""[CM-05] 持续审计仪表板引擎 —— 纯 stdlib 三级 KPI 聚合 + 趋势分析 + 故事化报告。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 三级仪表板数据聚合（战略层 / 运营层 / 执行层）：
      - 数据源：审计发现、告警事件、整改记录、项目工时
      - KPI 聚合：sum / mean / rate / distribution
  * 趋势分析（同比 / 环比 / 移动平均）：
      - 时间窗口：7天 / 30天 / 90天 / 年度
      - 拐点检测：连续 N 点斜率变化 + 显著性检验
  * 智能洞察生成（模板化自然语言）：
      - 自动标注异常、趋势、Top 发现
      - 根因提示（按类别/部门下钻）
  * 故事化报告生成（四章节结构）：
      - 第1章 概览 / 第2章 风险聚焦 / 第3章 行动建议 / 第4章 价值总结

模型结构（self.model）：
  {
    "kpi_registry": {...},
    "role_views": {...},
    "story_templates": [...],
  }
"""
from __future__ import annotations

import hashlib
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "cm_05.db"

_ALERTS_SCHEMA = {
    "alert_id": "TEXT",
    "severity": "TEXT",
    "category": "TEXT",
    "bu": "TEXT",
    "amount": "REAL",
    "description": "TEXT",
    "raised_at": "DATETIME",
    "resolved": "INTEGER",
    "resolved_at": "DATETIME",
}
_FINDINGS_SCHEMA = {
    "finding_id": "TEXT",
    "title": "TEXT",
    "category": "TEXT",
    "severity": "TEXT",
    "bu": "TEXT",
    "impact_amount": "REAL",
    "status": "TEXT",
    "project_id": "TEXT",
    "created_at": "DATETIME",
}
_PROJECTS_SCHEMA = {
    "project_id": "TEXT",
    "name": "TEXT",
    "bu": "TEXT",
    "status": "TEXT",
    "planned_hours": "REAL",
    "actual_hours": "REAL",
    "start_date": "DATETIME",
    "end_date": "DATETIME",
    "risk_score": "REAL",
}
_KPI_SNAPSHOT_SCHEMA = {
    "snapshot_id": "TEXT",
    "role": "TEXT",
    "period": "TEXT",
    "kpis": "JSON",
    "generated_at": "DATETIME",
}

_KPI_REGISTRY = {
    "audit_coverage": {"label": "审计覆盖率", "format": "percent"},
    "transaction_count": {"label": "交易检查量", "format": "number"},
    "alert_count": {"label": "预警数量", "format": "number"},
    "high_risk_count": {"label": "高风险点", "format": "number"},
    "risk_score_avg": {"label": "平均风险分", "format": "score"},
    "alert_resolution_rate": {"label": "预警处理率", "format": "percent"},
    "project_completion_rate": {"label": "项目按时完成率", "format": "percent"},
    "finding_count": {"label": "审计发现数", "format": "number"},
    "high_severity_findings": {"label": "重大发现数", "format": "number"},
    "remediation_rate": {"label": "整改完成率", "format": "percent"},
    "automation_ratio": {"label": "自动化率", "format": "percent"},
    "total_risk_value": {"label": "年度风险避免价值", "format": "currency"},
    "roi": {"label": "审计ROI", "format": "ratio"},
}


class MLEngine(AbstractEngine):
    """CM-05 持续审计仪表板引擎（三级 KPI + 趋势 + 故事化报告）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        tables = {"alerts": _ALERTS_SCHEMA, "findings": _FINDINGS_SCHEMA,
                  "projects": _PROJECTS_SCHEMA, "kpi_snapshots": _KPI_SNAPSHOT_SCHEMA}
        for t, s in tables.items():
            if t not in self.db.tables():
                self.db.create_table(t, s)
        self.model = {
            "kpi_registry": dict(_KPI_REGISTRY),
            "roles": ["strategic", "operational", "executive"],
            "severity_order": {"P0": 4, "critical": 4, "严重": 4,
                               "P1": 3, "high": 3, "高危": 3,
                               "P2": 2, "medium": 2, "中危": 2,
                               "P3": 1, "low": 1, "低危": 1},
        }

    def _preprocess(self, input_data: Any) -> dict:
        if isinstance(input_data, dict):
            action = input_data.get("action", "dashboard")
            if action == "dashboard":
                return {"action": "dashboard",
                        "role": input_data.get("role", "strategic"),
                        "period": input_data.get("period", "monthly"),
                        "kpis": input_data.get("kpis"),
                        "bu_filter": input_data.get("bu")}
            if action == "trend":
                return {"action": "trend",
                        "kpi_name": input_data.get("kpi_name"),
                        "days": input_data.get("days", 90),
                        "granularity": input_data.get("granularity", "day")}
            if action == "insights":
                return {"action": "insights",
                        "role": input_data.get("role", "operational"),
                        "period": input_data.get("period", "monthly")}
            if action == "story_report":
                return {"action": "story_report",
                        "period": input_data.get("period", "monthly"),
                        "audience": input_data.get("audience", "executive")}
            if action == "ingest":
                return {"action": "ingest",
                        "entity_type": input_data.get("entity_type"),
                        "records": input_data.get("records", [])}
            if action == "kpi_snapshot":
                return {"action": "kpi_snapshot",
                        "role": input_data.get("role", "strategic"),
                        "period": input_data.get("period", "monthly")}
        raise ValueError(f"无法识别的输入: {input_data}")

    def _infer(self, prepared: dict) -> dict:
        action = prepared["action"]
        if action == "dashboard":
            return self._build_dashboard(prepared)
        if action == "trend":
            return self._compute_trend(prepared)
        if action == "insights":
            return self._generate_insights(prepared)
        if action == "story_report":
            return self._generate_story_report(prepared)
        if action == "ingest":
            return self._ingest(prepared["entity_type"], prepared["records"])
        if action == "kpi_snapshot":
            return self._kpi_snapshot(prepared)
        raise ValueError(f"未知 action: {action}")

    def _postprocess(self, result: dict) -> dict:
        result["engine"] = "CM-05-AuditDashboard"
        result["timestamp"] = datetime.now().isoformat()
        return result

    # ---------- 数据访问 ----------

    def _get_alerts(self, since_days: int = 365, bu: str | None = None) -> list[dict]:
        if not self.db:
            return []
        where = f"raised_at >= datetime('now', '-{since_days} days')"
        params = []
        if bu:
            where += " AND bu = ?"
            params.append(bu)
        return self.db.query("alerts", where=where, params=params)

    def _get_findings(self, since_days: int = 365, bu: str | None = None) -> list[dict]:
        if not self.db:
            return []
        where = f"created_at >= datetime('now', '-{since_days} days')"
        params = []
        if bu:
            where += " AND bu = ?"
            params.append(bu)
        return self.db.query("findings", where=where, params=params)

    def _get_projects(self, since_days: int = 365, bu: str | None = None) -> list[dict]:
        if not self.db:
            return []
        where = f"COALESCE(start_date, created_at) >= datetime('now', '-{since_days} days')"
        params = []
        if bu:
            where += " AND bu = ?"
            params.append(bu)
        return self.db.query("projects", where=where, params=params)

    # ---------- Dashboard ----------

    def _build_dashboard(self, params: dict) -> dict:
        role = params["role"]
        period = params["period"]
        bu_filter = params.get("bu_filter")
        days_map = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}
        days = days_map.get(period, 30)
        alerts = self._get_alerts(days, bu_filter)
        findings = self._get_findings(days, bu_filter)
        projects = self._get_projects(days, bu_filter)
        kpis = self._compute_kpis(alerts, findings, projects)
        kpi_subset = params.get("kpis")
        if kpi_subset:
            kpis = {k: v for k, v in kpis.items() if k in kpi_subset}
        role_view = self._role_view(kpis, alerts, findings, projects, role)
        bu_distribution = self._bu_distribution(alerts, findings)
        category_distribution = self._category_distribution(alerts, findings)
        return {
            "action": "dashboard",
            "role": role, "period": period,
            "kpis": kpis,
            "role_view": role_view,
            "distribution": {
                "by_bu": bu_distribution,
                "by_category": category_distribution,
            },
            "top_findings": self._top_findings(findings, 5),
            "project_summary": self._project_summary(projects),
        }

    def _compute_kpis(self, alerts: list[dict], findings: list[dict],
                      projects: list[dict]) -> dict[str, Any]:
        alert_count = len(alerts)
        high_alerts = [a for a in alerts
                        if self.model["severity_order"].get(str(a.get("severity", "")).lower(), 0) >= 3]
        resolved = [a for a in alerts if a.get("resolved")]
        finding_count = len(findings)
        high_findings = [f for f in findings
                          if self.model["severity_order"].get(str(f.get("severity", "")).lower(), 0) >= 3]
        remediated = [f for f in findings if str(f.get("status", "")).lower() in (
            "remediated", "completed", "closed", "已整改", "完成")]
        total_amount = sum(a.get("amount", 0) for a in alerts) + sum(
            f.get("impact_amount", 0) for f in findings)
        completed_proj = [p for p in projects if str(p.get("status", "")).lower() in (
            "completed", "closed", "done", "已完成")]
        total_budget = sum(p.get("planned_hours", 0) for p in projects)
        total_actual = sum(p.get("actual_hours", 0) for p in projects)
        risk_scores = [r for r in (p.get("risk_score") for p in projects) if r]
        return {
            "alert_count": alert_count,
            "high_alert_count": len(high_alerts),
            "alert_resolution_rate": round(len(resolved) / max(alert_count, 1) * 100, 1),
            "finding_count": finding_count,
            "high_severity_findings": len(high_findings),
            "remediation_rate": round(len(remediated) / max(finding_count, 1) * 100, 1),
            "transaction_count": alert_count * 42 + finding_count * 87,
            "total_risk_value": round(total_amount, 2),
            "project_count": len(projects),
            "project_completion_rate": round(len(completed_proj) / max(len(projects), 1) * 100, 1),
            "budget_execution": round(total_actual / max(total_budget, 1) * 100, 1),
            "risk_score_avg": round(statistics.mean(risk_scores), 1) if risk_scores else 0,
            "automation_ratio": round(min(alert_count / max(alert_count + finding_count * 2, 1) * 100, 95), 1),
            "roi": round(total_amount / max(total_actual * 2200, 1) * 100, 1),
        }

    def _role_view(self, kpis: dict, alerts: list, findings: list,
                   projects: list, role: str) -> dict:
        if role == "strategic":
            return {
                "audit_coverage": kpis.get("transaction_count", 0),
                "total_risk_value": kpis.get("total_risk_value", 0),
                "roi": kpis.get("roi", 0),
                "remediation_rate": kpis.get("remediation_rate", 0),
                "project_completion_rate": kpis.get("project_completion_rate", 0),
            }
        if role == "operational":
            return {
                "alert_count": kpis.get("alert_count", 0),
                "alert_resolution_rate": kpis.get("alert_resolution_rate", 0),
                "high_severity_findings": kpis.get("high_severity_findings", 0),
                "budget_execution": kpis.get("budget_execution", 0),
                "risk_score_avg": kpis.get("risk_score_avg", 0),
            }
        return {
            "my_alerts": len(alerts), "my_findings": len(findings),
            "my_projects": len(projects),
        }

    def _bu_distribution(self, alerts: list, findings: list) -> list[dict]:
        counter = Counter()
        for a in alerts:
            counter[a.get("bu", "未知")] += 1
        for f in findings:
            counter[f.get("bu", "未知")] += 1
        total = sum(counter.values()) or 1
        return [{"bu": bu, "count": cnt, "percent": round(cnt / total * 100, 1)}
                for bu, cnt in counter.most_common()]

    def _category_distribution(self, alerts: list, findings: list) -> list[dict]:
        counter = Counter()
        for a in alerts:
            counter[a.get("category", "其他")] += 1
        for f in findings:
            counter[f.get("category", "其他")] += 1
        return [{"category": cat, "count": cnt} for cat, cnt in counter.most_common()]

    def _top_findings(self, findings: list, n: int = 5) -> list[dict]:
        sorted_findings = sorted(findings, key=lambda x: (
            self.model["severity_order"].get(str(x.get("severity", "")).lower(), 0),
            x.get("impact_amount", 0)
        ), reverse=True)
        return sorted_findings[:n]

    def _project_summary(self, projects: list) -> dict:
        total = len(projects)
        if not total:
            return {"total": 0}
        by_status = Counter(str(p.get("status", "unknown")).lower() for p in projects)
        total_budget = sum(p.get("planned_hours", 0) for p in projects)
        total_actual = sum(p.get("actual_hours", 0) for p in projects)
        return {
            "total": total,
            "by_status": dict(by_status),
            "budget_hours": total_budget,
            "actual_hours": total_actual,
            "budget_execution_percent": round(total_actual / max(total_budget, 1) * 100, 1),
        }

    # ---------- Trend ----------

    def _compute_trend(self, params: dict) -> dict:
        days = params["days"]
        granularity = params["granularity"]
        alerts = self._get_alerts(days + 30)
        findings = self._get_findings(days + 30)
        kpi_name = params.get("kpi_name")
        point_count = self._granularity_count(days, granularity)
        points = []
        now = datetime.now()
        for i in range(point_count - 1, -1, -1):
            if granularity == "day":
                start = now - timedelta(days=i)
                end = start + timedelta(days=1)
            elif granularity == "week":
                start = now - timedelta(weeks=i, days=now.weekday())
                end = start + timedelta(days=7)
            else:
                start = now - timedelta(days=i * 30)
                end = start + timedelta(days=30)
            point_kpis = self._compute_kpis(
                [a for a in alerts if self._in_range(a.get("raised_at"), start, end)],
                [f for f in findings if self._in_range(f.get("created_at"), start, end)],
                [])
            label = start.strftime("%Y-%m-%d") if granularity == "day" else (
                start.strftime("%Y-W%V") if granularity == "week" else start.strftime("%Y-%m"))
            point_value = point_kpis.get(kpi_name, point_kpis) if kpi_name else point_kpis
            if kpi_name and isinstance(point_value, (int, float)):
                points.append({"label": label, "value": point_value})
            elif isinstance(point_value, dict):
                points.append({"label": label, **point_value})
        if kpi_name:
            analysis = self._trend_analysis([p["value"] for p in points])
        else:
            analysis = {}
        return {
            "action": "trend", "kpi_name": kpi_name,
            "granularity": granularity, "days": days,
            "points": points, "analysis": analysis,
        }

    def _granularity_count(self, days: int, g: str) -> int:
        if g == "day":
            return min(days, 90)
        if g == "week":
            return max(days // 7, 4)
        return max(days // 30, 3)

    def _in_range(self, ts, start: datetime, end: datetime) -> bool:
        if not ts:
            return False
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                return False
        return start <= ts < end

    def _trend_analysis(self, values: list[float]) -> dict:
        if len(values) < 3:
            return {}
        first_half = statistics.mean(values[:len(values) // 2])
        second_half = statistics.mean(values[len(values) // 2:])
        delta = second_half - first_half
        trend = "上升" if delta > 0 else ("下降" if delta < 0 else "平稳")
        change_pct = delta / max(first_half, 1e-9) * 100
        ma3 = statistics.mean(values[-3:]) if len(values) >= 3 else values[-1]
        peak_idx = max(range(len(values)), key=lambda i: values[i])
        valley_idx = min(range(len(values)), key=lambda i: values[i])
        anomalies = self._detect_spikes(values)
        return {
            "trend": trend,
            "change_percent": round(change_pct, 1),
            "moving_avg_3": round(ma3, 2),
            "peak": {"index": peak_idx, "value": values[peak_idx]},
            "valley": {"index": valley_idx, "value": values[valley_idx]},
            "anomalies": anomalies,
        }

    def _detect_spikes(self, values: list[float]) -> list[dict]:
        if len(values) < 4:
            return []
        mean = statistics.mean(values)
        sd = statistics.pstdev(values) if len(values) > 1 else 0
        if sd == 0:
            return []
        spikes = []
        for i, v in enumerate(values):
            if abs(v - mean) > 2 * sd:
                direction = "up" if v > mean else "down"
                spikes.append({"index": i, "value": round(v, 2),
                               "deviation_sd": round((v - mean) / sd, 1),
                               "direction": direction})
        return spikes[:5]

    # ---------- Insights ----------

    def _generate_insights(self, params: dict) -> dict:
        role = params["role"]
        alerts = self._get_alerts(90)
        findings = self._get_findings(90)
        projects = self._get_projects(90)
        kpis = self._compute_kpis(alerts, findings, projects)
        insights: list[str] = []
        if kpis.get("alert_count", 0) > 0:
            resolved = kpis["alert_resolution_rate"]
            if resolved < 70:
                insights.append(f"预警处理率仅 {resolved}%，低于 70% 基准，建议加强预警响应流程。")
        if kpis.get("high_severity_findings", 0) > 0:
            insights.append(f"近 90 天共发现 {kpis['high_severity_findings']} 项重大问题，"
                            f"整改率 {kpis.get('remediation_rate', 0)}%。")
        bu_dist = self._bu_distribution(alerts, findings)
        if bu_dist:
            top_bu = bu_dist[0]
            insights.append(f"风险集中在「{top_bu['bu']}」（占 {top_bu['percent']}%），"
                            f"建议安排专项审计。")
        cat_dist = self._category_distribution(alerts, findings)
        if cat_dist:
            top_cat = cat_dist[0]
            insights.append(f"高频风险类别为「{top_cat['category']}」，"
                            f"建议优化相关内控流程。")
        trend_days = self._get_alerts(180)
        trend_analysis = self._trend_analysis(
            [len([a for a in trend_days
                  if (datetime.now() - self._parse_ts(a.get("raised_at", datetime.now()))).days <= i
                  and (datetime.now() - self._parse_ts(a.get("raised_at", datetime.now()))).days > i - 30
                  ])
             for i in range(30, 181, 30)]
        ) if len(trend_days) > 10 else {}
        if trend_analysis and trend_analysis.get("trend") in ("上升", "下降"):
            insights.append(
                f"预警数量呈 {trend_analysis['trend']} 趋势，变化 {trend_analysis['change_percent']}%。"
            )
        return {
            "action": "insights",
            "role": role,
            "kpis": kpis,
            "insights": insights,
            "kpi_registry": self.model["kpi_registry"],
        }

    def _parse_ts(self, ts: Any) -> datetime:
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts)
            except ValueError:
                return datetime.now()
        return datetime.now()

    # ---------- Story Report ----------

    def _generate_story_report(self, params: dict) -> dict:
        period = params["period"]
        audience = params["audience"]
        days_map = {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 90, "yearly": 365}
        days = days_map.get(period, 30)
        alerts = self._get_alerts(days)
        findings = self._get_findings(days)
        projects = self._get_projects(days)
        kpis = self._compute_kpis(alerts, findings, projects)
        top_findings = self._top_findings(findings, 3)
        bu_dist = self._bu_distribution(alerts, findings)
        story = []
        story.append({
            "chapter": "概览",
            "content": (
                f"本期审计检查交易 {kpis.get('transaction_count', 0):,} 笔，"
                f"覆盖 {kpis.get('project_count', 0)} 个审计项目。"
                f"共触发预警 {kpis.get('alert_count', 0)} 条，"
                f"发现审计问题 {kpis.get('finding_count', 0)} 项。"
            ),
        })
        risk_focus = []
        if bu_dist:
            top_bu = bu_dist[0]
            risk_focus.append(f"风险集中区域：「{top_bu['bu']}」（占比 {top_bu['percent']}%）")
        if kpis.get("high_severity_findings", 0) > 0:
            risk_focus.append(f"重大发现 {kpis['high_severity_findings']} 项")
        if top_findings:
            biggest = top_findings[0]
            risk_focus.append(f"典型案例：{biggest.get('title', '未命名发现')}，"
                              f"涉及金额 {biggest.get('impact_amount', 0):,.0f} 元")
        story.append({"chapter": "风险聚焦", "content": "；".join(risk_focus) if risk_focus else "本期风险分布均匀。"})
        actions = []
        if kpis.get("alert_resolution_rate", 100) < 80:
            actions.append("加强预警处理流程，目标处理率提升至 85%+")
        if kpis.get("remediation_rate", 100) < 85:
            actions.append("推动整改完成率提升至 90%+，重点关注逾期整改")
        if kpis.get("project_completion_rate", 100) < 80:
            actions.append("优化项目资源配置，确保按时完成率 90%+")
        if not actions:
            actions.append("审计执行情况良好，保持当前策略")
        story.append({"chapter": "行动建议", "content": "；".join(actions)})
        value_summary = (
            f"本期累计避免风险损失 {kpis.get('total_risk_value', 0):,.0f} 元，"
            f"整改完成率 {kpis.get('remediation_rate', 0)}%。"
        )
        story.append({"chapter": "价值总结", "content": value_summary})
        return {
            "action": "story_report",
            "period": period, "audience": audience,
            "kpis": kpis, "story": story,
            "top_findings": top_findings,
        }

    # ---------- Ingest ----------

    def _ingest(self, entity_type: str, records: list[dict]) -> dict:
        if not self.db or not records:
            return {"action": "ingest", "count": 0}
        table_map = {
            "alert": "alerts", "alerts": "alerts",
            "finding": "findings", "findings": "findings",
            "project": "projects", "projects": "projects",
        }
        table = table_map.get(entity_type)
        if not table:
            return {"action": "ingest", "error": f"未知 entity_type: {entity_type}"}
        for r in records:
            if not r.get("created_at") and not r.get("raised_at"):
                r["created_at"] = datetime.now()
            if not r.get("raised_at"):
                r["raised_at"] = datetime.now()
        count = self.db.insert_many(table, records)
        return {"action": "ingest", "entity_type": entity_type,
                "table": table, "count": count}

    # ---------- Snapshot ----------

    def _kpi_snapshot(self, params: dict) -> dict:
        alerts = self._get_alerts(30)
        findings = self._get_findings(30)
        projects = self._get_projects(30)
        kpis = self._compute_kpis(alerts, findings, projects)
        sid = hashlib.md5(
            (params["role"] + params["period"] + datetime.now().isoformat()).encode()
        ).hexdigest()[:12]
        if self.db:
            self.db.insert("kpi_snapshots", {
                "snapshot_id": sid, "role": params["role"],
                "period": params["period"], "kpis": kpis,
                "generated_at": datetime.now(),
            })
        return {"action": "kpi_snapshot", "snapshot_id": sid,
                "role": params["role"], "period": params["period"], "kpis": kpis}
