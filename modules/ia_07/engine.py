"""[rpa] IA-07 智能整改跟踪平台。

纯 stdlib 实现的整改跟踪引擎：
  - _load_model  : 初始化整改任务表、历史整改样本表（PortableDB 持久化）
  - _preprocess  : 解析输入整改任务（审计发现+责任人+截止日期），计算当前阶段
  - _infer       : 整改生命周期状态机流转 + 超时升级级别判定 + 失败风险预测 + 推荐整改方案
  - _postprocess : 输出结构化整改跟踪项（状态/级别/风险/推荐方案/下一步动作）
"""
from __future__ import annotations

import math
import random
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB


_STATES = ("待分配", "整改中", "待验证", "已关闭", "归档", "争议中")
_SEVERITY = {"严重": 4, "重要": 3, "一般": 2, "建议": 1}


def _days_between(a: str | datetime, b: str | datetime) -> float:
    def to_dt(x):
        if isinstance(x, datetime):
            return x
        if isinstance(x, date):
            return datetime.combine(x, datetime.min.time())
        return datetime.fromisoformat(str(x))
    return (to_dt(b) - to_dt(a)).total_seconds() / 86400.0


class RPAEngine(AbstractEngine):
    """IA-07 智能整改跟踪引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.tasks: list[dict] = []
        self.history: list[dict] = []

    def _load_model(self):
        db_path = self.config.get("db_path", "modules/ia_07/data/ia07.db")
        self.db = PortableDB(db_path)
        self.db.create_table("remediation_tasks", {
            "task_id": "TEXT", "finding_id": "TEXT", "issue_type": "TEXT",
            "severity": "INTEGER", "assignee": "TEXT", "department": "TEXT",
            "created_at": "DATETIME", "deadline": "DATETIME", "status": "TEXT",
            "progress": "REAL", "complexity": "REAL", "cross_dept": "INTEGER",
        }, drop_if_exists=False)
        self.db.create_table("remediation_history", {
            "issue_type": "TEXT", "severity": "INTEGER",
            "complexity": "REAL", "cross_dept": "INTEGER",
            "completed": "INTEGER", "duration_days": "REAL",
        }, drop_if_exists=False)
        hist = self.db.all("remediation_history")
        self.history = hist if hist else self._seed_history()
        tasks = self.db.all("remediation_tasks")
        self.tasks = tasks if tasks else []

    def _seed_history(self) -> list[dict]:
        seed = [
            {"issue_type": "流程缺陷", "severity": 3, "complexity": 0.5, "cross_dept": 1,
             "completed": 1, "duration_days": 42},
            {"issue_type": "控制缺失", "severity": 4, "complexity": 0.7, "cross_dept": 0,
             "completed": 1, "duration_days": 28},
            {"issue_type": "合规违规", "severity": 4, "complexity": 0.4, "cross_dept": 0,
             "completed": 1, "duration_days": 21},
            {"issue_type": "效率低下", "severity": 2, "complexity": 0.3, "cross_dept": 1,
             "completed": 0, "duration_days": 95},
            {"issue_type": "控制缺失", "severity": 3, "complexity": 0.6, "cross_dept": 1,
             "completed": 1, "duration_days": 60},
            {"issue_type": "流程缺陷", "severity": 2, "complexity": 0.4, "cross_dept": 0,
             "completed": 1, "duration_days": 30},
        ]
        if self.db:
            self.db.insert_many("remediation_history", seed)
        return seed

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        parsed = []
        now = datetime.now()
        for it in items:
            created = it.get("created_at", now.isoformat())
            deadline = it.get("deadline")
            if not deadline:
                dl_dt = now + timedelta(days=30)
                deadline = dl_dt.isoformat()
            severity = it.get("severity", "一般")
            sev_int = _SEVERITY.get(severity, 2) if isinstance(severity, str) else severity
            complexity = it.get("complexity", 0.5)
            cross_dept = 1 if it.get("cross_department") else 0
            days_passed = _days_between(created, now.isoformat())
            days_remaining = _days_between(now.isoformat(), deadline)
            parsed.append({
                "task_id": it.get("task_id") or f"T-{abs(hash(it.get('finding_id') or str(created))) % 100000:05d}",
                "finding_id": it.get("finding_id", ""),
                "issue_type": it.get("issue_type", "通用"),
                "severity": severity if isinstance(severity, str) else {v: k for k, v in _SEVERITY.items()}.get(sev_int, "一般"),
                "severity_int": sev_int,
                "assignee": it.get("assignee", "未分配"),
                "department": it.get("department", ""),
                "created_at": created,
                "deadline": deadline,
                "now": now.isoformat(),
                "days_passed": round(days_passed, 1),
                "days_remaining": round(days_remaining, 1),
                "planned_total_days": max(1.0, _days_between(created, deadline)),
                "complexity": complexity,
                "cross_dept": cross_dept,
                "has_history": it.get("history_count", 3),
            })
        return {"tasks": parsed, "now": now.isoformat()}

    def _infer(self, prepared):
        results = []
        for t in prepared["tasks"]:
            state = self._compute_state(t)
            escal = self._escalation_level(t, state)
            risk = self._failure_risk(t)
            recommendation = self._recommend(t)
            progress = self._progress_estimate(t, risk)
            results.append({
                "task_id": t["task_id"],
                "finding_id": t["finding_id"],
                "state": state,
                "escalation": escal,
                "failure_risk": round(risk, 3),
                "risk_level": self._risk_label(risk),
                "progress_estimate": progress,
                "next_action": self._next_action(state, escal, risk),
                "recommended_plan": recommendation,
                "days_passed": t["days_passed"],
                "days_remaining": t["days_remaining"],
                "severity": t["severity"],
                "issue_type": t["issue_type"],
            })
        return results

    def _compute_state(self, t: dict) -> str:
        if t["days_passed"] <= 0.5:
            return "待分配"
        if t["days_remaining"] < -30:
            return "已关闭"
        if t["days_remaining"] < 0 and t["severity_int"] >= 4:
            return "争议中"
        if t["days_remaining"] < -7:
            return "待验证"
        if t["days_remaining"] < 0:
            return "整改中"
        return "整改中"

    def _escalation_level(self, t: dict, state: str) -> int:
        if state in ("已关闭", "归档"):
            return 0
        over_days = max(0, -t["days_remaining"])
        severity_mult = 1.0 + 0.5 * (t["severity_int"] - 2)
        threshold_days = [3, 7, 15, 30, 90]
        level = 0
        for i, th in enumerate(threshold_days):
            if over_days >= th * severity_mult:
                level = max(level, i + 1)
        days_to_deadline = t["days_remaining"]
        if level == 0 and days_to_deadline > 0 and days_to_deadline <= 14 and t["severity_int"] >= 3:
            level = 1
        return min(level, 5)

    def _failure_risk(self, t: dict) -> float:
        sev_w = {1: 0.05, 2: 0.10, 3: 0.18, 4: 0.28}[t["severity_int"]]
        complex_w = t["complexity"] * 0.25
        cross_w = t["cross_dept"] * 0.15
        progress_ratio = t["days_passed"] / max(1.0, t["planned_total_days"])
        if t["days_remaining"] < 0:
            overdue_penalty = min(0.30, abs(t["days_remaining"]) / 100)
        elif progress_ratio > 0.7 and t["days_remaining"] > 0:
            overdue_penalty = 0.05
        else:
            overdue_penalty = 0.0
        hist_hit = [h for h in self.history
                    if h["issue_type"] == t["issue_type"] and h["severity"] == t["severity_int"]]
        hist_fail_rate = 0.5
        if hist_hit:
            failed = sum(1 for h in hist_hit if not h["completed"])
            hist_fail_rate = failed / len(hist_hit)
        hist_w = hist_fail_rate * 0.17
        risk = sev_w + complex_w + cross_w + overdue_penalty + hist_w
        return round(min(1.0, risk), 3)

    def _risk_label(self, risk: float) -> str:
        if risk > 0.6:
            return "高"
        if risk > 0.3:
            return "中"
        return "低"

    def _progress_estimate(self, t: dict, risk: float) -> float:
        planned = t["planned_total_days"]
        elapsed = t["days_passed"]
        base = min(1.0, elapsed / max(1.0, planned))
        if risk > 0.6:
            base *= 0.7
        elif risk > 0.3:
            base *= 0.88
        return round(base, 3)

    def _recommend(self, t: dict) -> list[dict]:
        type_strategies = {
            "流程缺陷": ["分级审批机制", "自动化流程编排", "节点责任矩阵"],
            "控制缺失": ["最小权限原则", "权限定期轮换", "权限自动回收"],
            "合规违规": ["合规检查清单", "定期合规培训", "合规仪表盘"],
            "效率低下": ["RPA自动化", "数据驱动决策", "流程再造"],
            "战略偏离": ["战略对齐工作坊", "OKR重新校准", "资源重新分配"],
            "通用": ["根因分析", "专项治理小组", "分阶段落地方案"],
        }
        strategies = type_strategies.get(t["issue_type"], type_strategies["通用"])
        hist_hit = [h for h in self.history if h["issue_type"] == t["issue_type"]]
        if hist_hit:
            avg_duration = sum(h["duration_days"] for h in hist_hit) / len(hist_hit)
        else:
            avg_duration = 30.0
        return [
            {"id": f"R{i+1}", "strategy": s, "expected_effectiveness": round(0.6 + i * 0.1, 2),
             "typical_duration_days": round(avg_duration * (1 + 0.2 * i), 1)}
            for i, s in enumerate(strategies[:3])
        ]

    def _next_action(self, state: str, escal: int, risk: float) -> str:
        if escal >= 4:
            return "提交审计委员会审议，启动管理层月度跟踪"
        if escal == 3:
            return "通知部门总经理+审计总监，要求3日内提交加速方案"
        if escal == 2:
            return "通知部门经理，要求48小时内提交整改加速方案"
        if escal == 1:
            return "发送提醒至责任人，要求3日内回复进度"
        if risk > 0.6:
            return "标记为重点关注，增加跟踪频率至每日"
        if state == "待分配":
            return "自动分配整改责任人，24小时内确认"
        return "按标准流程跟踪，每周更新进度"

    def _postprocess(self, result):
        escal_labels = {
            0: ("正常", "无升级，标准跟踪"),
            1: ("黄色预警", "截止前14天未完成或滞后>20%"),
            2: ("橙色预警", "截止前7天或滞后>50%"),
            3: ("红色预警", "超期7天或风险>80%"),
            4: ("升级至总经理", "超期15天/重大发现超期15天"),
            5: ("升级至审计委员会", "超期30天或超重大发现超期15天"),
        }
        for item in result:
            lbl, desc = escal_labels.get(item["escalation"], ("未知", ""))
            item["escalation_label"] = lbl
            item["escalation_desc"] = desc
            item["timestamp"] = datetime.now().isoformat()
        return {"tasks": result, "total": len(result), "generated_at": datetime.now().isoformat()}
