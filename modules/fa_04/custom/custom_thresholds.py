"""自定义阈值分级：基于状态的超时严重度 + 差异异常等级。

分级规则（可被 config.threshold 覆盖）：
  * 超时严重度 overdue_severity（针对 sent/delivered/timeout 状态）：
      - hours >= overdue_critical_hours(120) → critical
      - hours >= overdue_high_hours(72)       → high
      - hours >= overdue_medium_hours(48)     → medium
      - 其余已发函                                 → low
      - 未发函                                     → none
  * 差异异常等级 exception_level（按回函差异最大百分比）：
      - max|diff_pct| >= diff_high_pct(10)    → high
      - max|diff_pct| >= diff_medium_pct(1)   → medium
      - 有差异但低于中阈值                       → low
      - 无差异                                   → none
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

# 出厂默认阈值
_DEFAULT_OVERDUE_CRITICAL = 120.0
_DEFAULT_OVERDUE_HIGH = 72.0
_DEFAULT_OVERDUE_MEDIUM = 48.0
_DEFAULT_DIFF_HIGH_PCT = 10.0
_DEFAULT_DIFF_MEDIUM_PCT = 1.0

_PENDING_STATES = ("sent", "delivered", "timeout")


def _parse_dt(value: Any) -> datetime | None:
    """解析日期时间字符串（与 engine._parse_dt 同源逻辑）。"""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _overdue_severity(hours: float, critical: float, high: float,
                      medium: float) -> str:
    if hours >= critical:
        return "critical"
    if hours >= high:
        return "high"
    if hours >= medium:
        return "medium"
    return "low"


def _exception_level(max_pct: float, high_pct: float,
                     medium_pct: float) -> str:
    if max_pct >= high_pct:
        return "high"
    if max_pct >= medium_pct:
        return "medium"
    return "low"


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对每张函证进行超时严重度 + 差异异常等级分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    overdue_critical = float(threshold.get("overdue_critical_hours", _DEFAULT_OVERDUE_CRITICAL))
    overdue_high = float(threshold.get("overdue_high_hours", _DEFAULT_OVERDUE_HIGH))
    overdue_medium = float(threshold.get("overdue_medium_hours", _DEFAULT_OVERDUE_MEDIUM))
    diff_high_pct = float(threshold.get("diff_high_pct", _DEFAULT_DIFF_HIGH_PCT))
    diff_medium_pct = float(threshold.get("diff_medium_pct", _DEFAULT_DIFF_MEDIUM_PCT))

    now = datetime.now()
    severity_dist: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "none": 0}
    exception_dist: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "none": 0}

    for c in result.get("confirmations", []):
        # 超时严重度
        sev = "none"
        sent = _parse_dt(c.get("sent_at"))
        if sent is not None and c.get("status") in _PENDING_STATES:
            hours = (now - sent).total_seconds() / 3600.0
            sev = _overdue_severity(hours, overdue_critical, overdue_high, overdue_medium)
        c["overdue_severity"] = sev
        severity_dist[sev] = severity_dist.get(sev, 0) + 1

        # 差异异常等级（取该函证所有差异字段的最大绝对百分比）
        max_pct = 0.0
        for d in c.get("diff_records", []) or []:
            pct = d.get("diff_pct")
            if pct is not None:
                max_pct = max(max_pct, abs(float(pct)))
        exc = "none"
        if max_pct > 0 or c.get("diff_records"):
            if max_pct > 0:
                exc = _exception_level(max_pct, diff_high_pct, diff_medium_pct)
            else:
                # 有差异但无百分比（非数值差异）
                exc = "low"
        c["exception_level"] = exc
        exception_dist[exc] = exception_dist.get(exc, 0) + 1

    result["grading"] = {
        "severity_distribution": severity_dist,
        "exception_distribution": exception_dist,
        "thresholds": {
            "overdue_critical_hours": overdue_critical,
            "overdue_high_hours": overdue_high,
            "overdue_medium_hours": overdue_medium,
            "diff_high_pct": diff_high_pct,
            "diff_medium_pct": diff_medium_pct,
        },
    }
    return result
