"""自定义输出格式化 —— 数据湖概览。

把内部结果转为对外统一输出结构：
  数据湖概览 = 三区统计 + 质量分布 + 血缘摘要 + 复用率 + 治理动作。
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为统一对外输出（数据湖概览）。"""
    if not isinstance(result, dict):
        return result

    zones = result.get("zones", {}) or {}
    ods = zones.get("ods", {}) or {}
    dwd = zones.get("dwd", {}) or {}
    ads = zones.get("ads", {}) or {}
    quality = result.get("quality", {}) or {}
    grades = result.get("quality_grades", {}) or {}
    lineage = result.get("lineage", {}) or {}
    governance = result.get("governance", {}) or {}

    # 三区统计
    zone_stats = {
        "ods": {
            "table": ods.get("table", "ods_raw"),
            "count": ods.get("count", 0),
            "sources": ods.get("sources", []),
        },
        "dwd": {
            "table": dwd.get("table", "dwd_standardized"),
            "count": dwd.get("count", 0),
        },
        "ads": {
            "table": ads.get("table", "ads_ready"),
            "count": ads.get("count", 0),
            "theme": ads.get("theme", "account_monthly_summary"),
        },
    }

    # 质量分布（评分 + 等级）
    quality_dist = {}
    for zone in ("ods", "dwd", "ads"):
        m = quality.get(zone, {}) or {}
        g = grades.get(zone, {}) or {}
        quality_dist[zone] = {
            "completeness": m.get("completeness"),
            "uniqueness": m.get("uniqueness"),
            "consistency": m.get("consistency"),
            "overall_score": m.get("overall_score"),
            "grade": g.get("grade_label", g.get("grade")),
            "meets_threshold": g.get("meets_threshold"),
        }

    # 血缘摘要
    lineage_summary = {
        "summary": lineage.get("summary", {}),
        "graph": lineage.get("graph", {}),
        "edge_count": len(lineage.get("edges", [])),
    }

    overview = {
        "module": "FA-03",
        "name": "审计数据湖建设",
        "status": "ok",
        "batch_id": result.get("batch_id"),
        "project_code": result.get("project_code"),
        "三区统计": zone_stats,
        "质量分布": quality_dist,
        "血缘摘要": lineage_summary,
        "复用率": result.get("reuse_rate"),
        "去重移除": result.get("dedup_removed", 0),
        "阈值": result.get("threshold", {}),
        "治理动作": governance.get("actions", []),
        "generated_at": result.get("generated_at"),
    }
    return overview
