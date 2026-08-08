"""统一输出格式化：ESG 多源数据采集报告。

输出结构：
  {
    "status": "ok",
    "module": "ES-01",
    "data_catalog": [ {metric_key, metric_name, dimension, consolidated_value,
                       unit, source_count, source_list, confidence,
                       confidence_grade, verification_flag, conflict_alert, ...}, ... ],
    "dimension_summary": { E/S/G: {count, metrics} },
    "quality_assessment": { source_count, metric_count, coverage, accuracy,
                            completeness, overall, confidence_level, issues, ... },
    "data_gaps": [ {metric_key, metric_name, dimension}, ... ],
    "rule_alerts": { verification_flags, conflict_alerts, counts, ... },
    "collection_log": { total_records, errors, generated_at }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外 ESG 采集报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    catalog = result.get("data_catalog", [])
    details = []
    for m in catalog:
        details.append({
            "metric_key": m.get("metric_key"),
            "metric_name": m.get("metric_name"),
            "dimension": m.get("dimension"),
            "subcategory": m.get("subcategory"),
            "consolidated_value": m.get("consolidated_value"),
            "unit": m.get("unit"),
            "source_count": m.get("source_count"),
            "source_list": m.get("source_list", []),
            "range": m.get("range", [0, 0]),
            "std_dev": m.get("std_dev"),
            "cv": m.get("cv"),
            "confidence": m.get("confidence"),
            "confidence_grade": m.get("confidence_grade"),
            "verification_flag": m.get("verification_flag", False),
            "low_credibility_sources": m.get("low_credibility_sources", []),
            "conflict_alert": m.get("conflict_alert", False),
        })

    quality = result.get("quality_report", {}) if isinstance(result.get("quality_report"), dict) else {}
    quality_assessment = {
        "source_count": quality.get("source_count", 0),
        "metric_count": quality.get("metric_count", 0),
        "coverage": quality.get("coverage", 0),
        "accuracy": quality.get("accuracy", 0),
        "completeness": quality.get("completeness", 0),
        "overall": quality.get("overall", 0),
        "confidence_level": quality.get("confidence_level", result.get("confidence_level")),
        "issues": quality.get("issues", []),
        "metric_grade_distribution": quality.get(
            "metric_grade_distribution",
            {"high": 0, "medium": 0, "low": 0},
        ),
        "thresholds": quality.get("thresholds", {}),
    }

    rule_alerts = result.get("rule_alerts", {
        "verification_flags": [],
        "conflict_alerts": [],
        "data_gap_count": 0,
        "verification_flag_count": 0,
        "conflict_alert_count": 0,
        "flagged_metric_keys": [],
    })

    # 维度摘要规整为可序列化结构
    raw_dim = result.get("dimension_summary", {})
    dimension_summary = {}
    for dim, info in raw_dim.items():
        if isinstance(info, dict):
            dimension_summary[dim] = {
                "count": info.get("count", 0),
                "metrics": info.get("metrics", []),
            }
        else:
            dimension_summary[dim] = {"count": 0, "metrics": []}

    collection_log = result.get("collection_log", {})

    return {
        "status": "ok",
        "module": "ES-01",
        "data_catalog": details,
        "dimension_summary": dimension_summary,
        "quality_assessment": quality_assessment,
        "data_gaps": result.get("data_gaps", []),
        "rule_alerts": rule_alerts,
        "collection_log": collection_log,
    }
