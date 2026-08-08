"""自定义业务规则 —— 数据治理动作。

在阈值分级之后执行，基于质量等级与分区状态产出治理动作：
  - 标记低质量分区需重新清洗（grade == unqualified）。
  - 标记可下架的过期/冗余数据（ODS 中被去重合并的、低质量原始记录）。
"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用数据治理规则，写回 governance（治理动作清单）。"""
    if not isinstance(result, dict):
        return result

    grades = result.get("quality_grades", {}) or {}
    dedup_removed = int(result.get("dedup_removed", 0))
    actions: list[dict[str, Any]] = []
    reclean_zones: list[str] = []

    # 规则①：不合格分区需重新清洗
    for zone, g in grades.items():
        if g.get("grade") == "unqualified":
            table = (result.get("zones", {}).get(zone) or {}).get("table", zone)
            actions.append({
                "action": "reclean",
                "zone": zone,
                "table": table,
                "reason": f"{zone} 区质量评分 {g.get('overall_score')} < 0.7，需重新清洗",
            })
            reclean_zones.append(zone)

    # 规则②：标记可下架的过期/冗余数据（去重合并产生的冗余 ODS 记录）
    expirable_count = 0
    if dedup_removed > 0:
        expirable_count = dedup_removed
        actions.append({
            "action": "archive_expired",
            "zone": "ods",
            "table": "ods_raw",
            "count": dedup_removed,
            "reason": "重复/被合并的原始记录，标记为可归档下架",
        })

    # 规则③：跨源复用率低于阈值时标记需扩充数据源
    reuse_rate = float(result.get("reuse_rate", 0.0))
    confidence = float((result.get("threshold", {}) or {}).get("confidence", 0.85))
    if reuse_rate < confidence:
        actions.append({
            "action": "expand_sources",
            "zone": "ads",
            "reason": f"跨源复用率 {reuse_rate} 低于阈值 {confidence}，建议扩充数据源接入",
        })

    result["governance"] = {
        "actions": actions,
        "reclean_zones": reclean_zones,
        "expirable_count": expirable_count,
    }
    return result
