"""统一输出格式化：数据资产目录 + 分类摘要 + 敏感度摘要 + 告警。

输出结构：
  {
    "status": "ok",
    "module": "CO-07",
    "asset_catalog": [ {asset_id, name, sensitive_types, sensitivity_level,
                        sensitivity_grade, sensitivity_score, compliance_tags, ...}, ... ],
    "classification_summary": { by_level, by_sensitive_type, grade_distribution, l3_l4_count },
    "sensitivity_summary": { total_sensitive_assets, restricted/confidential_count, thresholds },
    "alerts": [ {asset_id, rule, severity, message}, ... ],
    "statistics": { total_assets, total_fields, l3_l4_count, rule_summary }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    assets = result.get("assets", [])
    stats = result.get("statistics", {})
    alerts = result.get("alerts", [])

    # 资产目录
    catalog = []
    for a in assets:
        catalog.append({
            "asset_id": a.get("asset_id"),
            "name": a.get("name"),
            "location": a.get("location"),
            "source_type": a.get("source_type"),
            "format_type": a.get("format_type"),
            "sensitive_types": a.get("sensitive_types", []),
            "sensitivity_level": a.get("sensitivity_level"),
            "sensitivity_grade": a.get("sensitivity_grade"),
            "sensitivity_score": a.get("sensitivity_score"),
            "field_count": a.get("field_count"),
            "compliance_tags": a.get("compliance_tags", []),
            "owner": a.get("owner"),
            "needs_encryption": a.get("needs_encryption", False),
            "auto_classified": a.get("auto_classified", False),
            "public_zone_exposure": a.get("public_zone_exposure", False),
            "rule_flags": a.get("rule_flags", []),
        })

    # 分类摘要
    by_level = stats.get("by_level", {})
    by_type = stats.get("by_sensitive_type", {})
    grade_dist = stats.get("grade_distribution", {})
    classification_summary = {
        "by_level": by_level,
        "by_sensitive_type": by_type,
        "grade_distribution": grade_dist,
        "l3_l4_count": stats.get("l3_l4_count", 0),
    }

    # 敏感度摘要
    sensitivity_summary = {
        "total_sensitive_assets": sum(
            1 for a in assets if a.get("sensitive_types")
        ),
        "restricted_count": grade_dist.get("restricted", 0),
        "confidential_count": grade_dist.get("confidential", 0),
        "internal_count": grade_dist.get("internal", 0),
        "public_count": grade_dist.get("public", 0),
        "thresholds": stats.get("thresholds", {}),
    }

    output_stats = {
        "total_assets": stats.get("total_assets", len(assets)),
        "total_fields": stats.get("total_fields", 0),
        "l3_l4_count": stats.get("l3_l4_count", 0),
        "rule_summary": stats.get("rule_summary", {}),
    }

    return {
        "status": "ok",
        "module": "CO-07",
        "asset_catalog": catalog,
        "classification_summary": classification_summary,
        "sensitivity_summary": sensitivity_summary,
        "alerts": alerts,
        "statistics": output_stats,
    }
