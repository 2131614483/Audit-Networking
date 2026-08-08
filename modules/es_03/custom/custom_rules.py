"""自定义业务规则：在 engine + thresholds 之后执行，标记环境违规 / 升级严重度。

规则：
  1) 毁林检测：NDVI 下降超过阈值（category=deforestation 或 delta <= deforestation_delta）
     → 标记 environmental_violation=True（环境违规）
  2) 水质临界：NDWI 显著下降（category=pollution_drop 或 delta <= water_pollution_drop）
     或出现水体波动异常 → 标记 pollution_alert=True（污染告警）
  3) 保护区邻近退化：保护区内土地利用转为裸地/建设用地/火灾迹地
     → 强制升级 impact_level=critical（保护区升级）
"""
from __future__ import annotations

from typing import Any

_DEFORESTATION_DELTA = -0.15
_WATER_POLLUTION_DROP = -0.10
_DEGRADED_LAND_USE = ("裸地/建设用地", "火灾迹地")


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：毁林违规 / 水质告警 / 保护区升级。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    defor_delta = float(rules_cfg.get("deforestation_delta", _DEFORESTATION_DELTA))
    water_drop = float(rules_cfg.get("water_pollution_drop", _WATER_POLLUTION_DROP))
    protected_rois = set(rules_cfg.get("protected_rois", []) or [])

    roi_reports = result.get("roi_reports", [])
    violations = 0
    pollution_alerts = 0
    escalated = 0
    rule_flags = []

    for roi in roi_reports:
        roi_id = str(roi.get("roi_id", ""))
        roi_name = str(roi.get("roi_name", ""))
        flags = roi.setdefault("rule_flags", [])
        changes = roi.get("changes", [])

        # 规则 1：毁林 → 环境违规
        defor = [
            c for c in changes
            if c.get("index") == "NDVI"
            and (c.get("category") == "deforestation"
                 or float(c.get("delta", 0)) <= defor_delta)
        ]
        if defor:
            flags.append({
                "rule": "deforestation_violation",
                "severity": "高",
                "detail": f"检测到毁林，NDVI变化{defor[0].get('delta')}",
            })
            roi["environmental_violation"] = True
            violations += 1
            rule_flags.append({"roi": roi_name, "rule": "deforestation_violation"})
        else:
            roi.setdefault("environmental_violation", False)

        # 规则 2：水质临界 → 污染告警
        water = [
            c for c in changes
            if c.get("index") == "NDWI"
            and (c.get("category") == "pollution_drop"
                 or float(c.get("delta", 0)) <= water_drop)
        ]
        water_anom = [
            a for a in roi.get("anomalies", [])
            if "水体" in a.get("indicator", "") or "NDWI" in a.get("indicator", "")
        ]
        if water or water_anom:
            flags.append({
                "rule": "pollution_alert",
                "severity": "中",
                "detail": "水质指标异常，疑似排污或取水行为",
            })
            roi["pollution_alert"] = True
            pollution_alerts += 1
            rule_flags.append({"roi": roi_name, "rule": "pollution_alert"})
        else:
            roi.setdefault("pollution_alert", False)

        # 规则 3：保护区邻近退化 → 升级为 critical
        land_degrade = [
            c for c in changes
            if c.get("index") == "LandUse"
            and c.get("current") in _DEGRADED_LAND_USE
        ]
        is_protected = roi_id in protected_rois or roi_name in protected_rois
        if land_degrade and is_protected:
            flags.append({
                "rule": "protected_area_escalation",
                "severity": "高",
                "detail": "保护区内土地退化，强制升级为 critical",
            })
            roi["impact_level"] = "critical"
            roi["impact_score"] = 1.0
            escalated += 1
            rule_flags.append({"roi": roi_name, "rule": "protected_area_escalation"})

    # 规则触发后同步影响分布统计
    summary = result.get("summary", {})
    dist = {"normal": 0, "warning": 0, "critical": 0}
    for roi in roi_reports:
        lvl = roi.get("impact_level", "normal")
        dist[lvl] = dist.get(lvl, 0) + 1
    summary["impact_distribution"] = dist
    summary["rule_adjustments"] = {
        "deforestation_violations": violations,
        "pollution_alerts": pollution_alerts,
        "protected_area_escalations": escalated,
    }
    result["rule_flags"] = rule_flags
    result["summary"] = summary
    return result
