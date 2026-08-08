"""自定义阈值分级：基于风险评分的 SAR 优先级分级（critical/high/medium/low）。

分级规则（可被 config.threshold 覆盖）：
  * critical : risk_score >= 90  → 紧急提交（24 小时内）
  * high     : 70 <= risk_score < 90 → 优先提交（监管时限内）
  * medium   : 50 <= risk_score < 70 → 调查后提交
  * low      : risk_score < 50       → 监控观察
同时依据提交截止日计算 submission_urgency（是否临近超期）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# 出厂默认阈值
_DEFAULT_CRITICAL = 90.0
_DEFAULT_HIGH = 70.0
_DEFAULT_MEDIUM = 50.0
_DEFAULT_URGENT_DAYS = 2  # 距截止日 <= 2 天视为紧急


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对 SAR 报告进行优先级分级与提交紧急度标记。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    urgent_days = int(threshold.get("urgent_days", _DEFAULT_URGENT_DAYS))

    score = float(result.get("risk_score", 0) or 0)
    risk_level = result.get("risk_level", "")

    # SAR 优先级分级
    if score >= critical:
        sar_priority = "critical"
        priority_label = "紧急"
        priority_action = "24 小时内提交 FIU"
    elif score >= high:
        sar_priority = "high"
        priority_label = "优先"
        priority_action = "在监管提交时限内优先提交"
    elif score >= medium:
        sar_priority = "medium"
        priority_label = "常规"
        priority_action = "进一步调查后提交"
    else:
        sar_priority = "low"
        priority_label = "观察"
        priority_action = "纳入持续监控"

    result["sar_priority"] = sar_priority
    result["sar_priority_label"] = priority_label
    result["sar_priority_action"] = priority_action

    # 提交紧急度：依据 submission_deadline 与当前时间差
    deadline = result.get("submission_deadline")
    is_urgent = False
    days_remaining = None
    if deadline:
        try:
            dl = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            days_remaining = round((dl - now).total_seconds() / 86400.0, 1)
            is_urgent = days_remaining <= urgent_days
        except (ValueError, TypeError):
            pass
    result["submission_urgent"] = is_urgent
    if days_remaining is not None:
        result["days_remaining"] = days_remaining

    # 记录生效阈值（便于审计/测试）
    result["applied_thresholds"] = {
        "critical": critical,
        "high": high,
        "medium": medium,
        "urgent_days": urgent_days,
        "risk_level": risk_level,
    }
    return result
