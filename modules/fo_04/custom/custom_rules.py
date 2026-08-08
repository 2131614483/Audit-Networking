"""自定义业务规则：在 engine 之后执行，补充取证告警。

规则：
  1) 哈希不匹配 → 篡改告警（expected_hash vs content_hash）
  2) 缺失元数据 → 物证不完整标记（author/source/timestamp 缺失）
  3) 取证链时间间隙 → 完整性质疑（相邻物证时间间隔过大）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

_DEFAULT_GAP_HOURS = 72.0


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：哈希校验 / 元数据缺失 / 取证链间隙。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    gap_threshold_hours = float(
        rules_cfg.get("custody_gap_hours", _DEFAULT_GAP_HOURS)
    )

    items = result.get("items", [])
    alerts = []

    # 规则 1：哈希不匹配 → 篡改告警
    tamper_count = 0
    for item in items:
        expected = item.get("expected_hash")
        if expected and expected != item.get("content_hash"):
            item["tamper_alert"] = True
            tamper_count += 1
            alerts.append({
                "type": "hash_mismatch",
                "evidence_id": item.get("evidence_id"),
                "expected": expected,
                "actual": item.get("content_hash"),
                "message": "物证哈希与预期不符，疑似篡改",
            })
        else:
            item.setdefault("tamper_alert", False)

    # 规则 2：缺失元数据 → 物证不完整
    incomplete_count = 0
    for item in items:
        missing = []
        if not item.get("author"):
            missing.append("author")
        if not item.get("source"):
            missing.append("source")
        if not item.get("timestamp"):
            missing.append("timestamp")
        if missing:
            item["metadata_incomplete"] = True
            item["missing_fields"] = missing
            incomplete_count += 1
            alerts.append({
                "type": "missing_metadata",
                "evidence_id": item.get("evidence_id"),
                "missing": missing,
                "message": "物证元数据缺失，证据不完整",
            })
        else:
            item.setdefault("metadata_incomplete", False)
            item.setdefault("missing_fields", [])

    # 规则 3：取证链时间间隙 → 完整性质疑
    gap_count = 0
    for i in range(1, len(items)):
        prev_ts = items[i - 1].get("timestamp", "")
        curr_ts = items[i].get("timestamp", "")
        if not prev_ts or not curr_ts:
            continue
        gap_hours = _compute_gap_hours(prev_ts, curr_ts)
        if gap_hours is not None and gap_hours > gap_threshold_hours:
            gap_count += 1
            alerts.append({
                "type": "custody_gap",
                "evidence_id": items[i].get("evidence_id"),
                "gap_hours": round(gap_hours, 2),
                "message": f"取证链时间间隙 {gap_hours:.1f} 小时，完整性存疑",
            })

    result["alerts"] = alerts
    summary = result.get("summary", {})
    summary["alert_count"] = len(alerts)
    summary["tamper_alerts"] = tamper_count
    summary["incomplete_evidence"] = incomplete_count
    summary["custody_gaps"] = gap_count
    result["summary"] = summary
    return result


def _compute_gap_hours(ts1: str, ts2: str) -> float | None:
    """计算两个时间戳之间的小时差。"""
    t1 = _parse_ts(ts1)
    t2 = _parse_ts(ts2)
    if t1 is None or t2 is None:
        return None
    return abs((t2 - t1).total_seconds()) / 3600.0


def _parse_ts(ts: str) -> datetime | None:
    """解析时间戳字符串。"""
    if not ts:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None
