"""统一输出格式化：IPO审计加速看板 + 任务清单 + 核查发现 + 周期缩短统计。

输出结构：
  {
    "status": "ok",
    "dashboard": {                          # IPO审计加速看板
      "project_id", "enterprise_name",
      "overview": {总任务/已完成/加速比例/发现数/周期缩短},
      "by_category": {financial/legal/business/internal_control: {...}},
      "tech_stack": {rpa/ml/llm/kg: 贡献统计},
    },
    "task_list": [                          # 任务清单
      {"task_id","category","task_name","status","acceleration_ratio",
       "acceleration_tier","is_bottleneck","estimated_hours","after_hours","saved_hours"}, ...
    ],
    "findings": [                           # 核查发现
      {"finding_id","category","severity","source","description",
       "related_task_id","need_manual_review","key_check"}, ...
    ],
    "cycle_statistics": {                   # 周期缩短统计
      "total_tasks","completed_tasks","auto_done_tasks","manual_review_tasks",
      "overall_acceleration_ratio","findings_count","bottleneck_count",
      "estimated_cycle_reduction_pct","cycle_before_days","cycle_after_days",
      "total_saved_hours",
    },
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构（看板 + 任务清单 + 发现 + 周期统计）。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    project = result.get("project", {}) or {}
    enterprise = project.get("enterprise", {}) or {}
    tasks = result.get("tasks", []) or []
    findings = result.get("findings", []) or []
    stats = result.get("statistics", {}) or {}
    rpa = result.get("rpa_results", {}) or {}
    ml = result.get("ml_results", {}) or {}
    llm = result.get("llm_results", {}) or {}
    kg = result.get("kg_results", {}) or {}
    accel = result.get("acceleration", {}) or {}

    # ---- 任务清单 ----
    task_list = []
    for t in tasks:
        task_list.append({
            "task_id": t.get("task_id"),
            "category": t.get("category"),
            "task_name": t.get("task_name"),
            "status": t.get("status"),
            "acceleration_ratio": t.get("acceleration_ratio", 0.0),
            "acceleration_tier": t.get("acceleration_tier"),
            "is_bottleneck": bool(t.get("is_bottleneck", False)),
            "estimated_hours": t.get("estimated_hours", 0.0),
            "after_hours": t.get("after_hours", 0.0),
            "saved_hours": round(t.get("estimated_hours", 0.0) - t.get("after_hours", 0.0), 2),
        })

    # ---- 核查发现 ----
    finding_list = []
    for f in findings:
        finding_list.append({
            "finding_id": f.get("finding_id"),
            "category": f.get("category"),
            "severity": f.get("severity"),
            "source": f.get("source"),
            "description": f.get("description"),
            "related_task_id": f.get("related_task_id"),
            "need_manual_review": bool(f.get("need_manual_review", False)),
            "key_check": bool(f.get("key_check", False)),
        })

    # ---- 按类别统计任务 ----
    by_category: dict[str, dict] = {}
    for t in tasks:
        cat = t.get("category", "unknown")
        d = by_category.setdefault(cat, {
            "total": 0, "auto_done": 0, "manual_review": 0, "manual": 0,
            "saved_hours": 0.0,
        })
        d["total"] += 1
        s = t.get("status", "pending")
        if s in d:
            d[s] += 1
        d["saved_hours"] = round(d["saved_hours"] + (t.get("estimated_hours", 0.0) - t.get("after_hours", 0.0)), 2)

    # ---- 技术栈贡献 ----
    tech_stack = {
        "rpa": {
            "automated_count": rpa.get("automated_count", 0),
            "actions": len(rpa.get("actions", [])),
        },
        "ml": {
            "anomaly_count": ml.get("anomaly_count", 0),
            "outliers": len(ml.get("outliers", [])),
            "trend_signals": len(ml.get("trend", [])),
            "benford_deviation": (ml.get("benford", {}) or {}).get("deviation", 0.0),
        },
        "llm": {
            "doc_count": llm.get("doc_count", 0),
            "summaries": len(llm.get("summaries", [])),
        },
        "kg": {
            "equity_penetration": len(kg.get("equity_penetration", [])),
            "related_transactions": len(kg.get("related_transactions", [])),
            "fund_flow_paths": len(kg.get("fund_flow", [])),
        },
    }

    # ---- 看板 ----
    dashboard = {
        "project_id": project.get("project_id", "IPO-UNKNOWN"),
        "enterprise_name": enterprise.get("name", "未知企业"),
        "overview": {
            "total_tasks": stats.get("total_tasks", len(tasks)),
            "completed_tasks": stats.get("completed_tasks", 0),
            "auto_done_tasks": stats.get("auto_done_tasks", 0),
            "overall_acceleration_ratio": stats.get("overall_acceleration_ratio", 0.0),
            "findings_count": stats.get("findings_count", len(findings)),
            "bottleneck_count": stats.get("bottleneck_count", 0),
            "estimated_cycle_reduction_pct": stats.get("estimated_cycle_reduction_pct", 0.0),
        },
        "by_category": by_category,
        "tech_stack": tech_stack,
    }

    # ---- 周期缩短统计 ----
    cycle_statistics = {
        "total_tasks": stats.get("total_tasks", len(tasks)),
        "completed_tasks": stats.get("completed_tasks", 0),
        "auto_done_tasks": stats.get("auto_done_tasks", 0),
        "manual_review_tasks": stats.get("manual_review_tasks", 0),
        "manual_tasks": stats.get("manual_tasks", 0),
        "overall_acceleration_ratio": stats.get("overall_acceleration_ratio", 0.0),
        "findings_count": stats.get("findings_count", len(findings)),
        "bottleneck_count": stats.get("bottleneck_count", 0),
        "estimated_cycle_reduction_pct": stats.get("estimated_cycle_reduction_pct", 0.0),
        "cycle_before_days": stats.get("cycle_before_days", 0.0),
        "cycle_after_days": stats.get("cycle_after_days", 0.0),
        "total_saved_hours": accel.get("total_saved_hours", 0.0),
    }

    return {
        "status": "ok",
        "dashboard": dashboard,
        "task_list": task_list,
        "findings": finding_list,
        "cycle_statistics": cycle_statistics,
    }
