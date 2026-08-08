"""自定义业务规则：在 engine/threshold 之后执行，覆盖/补充供应商风险预警。

规则：
  1) 多指标上升趋势（trend_escalation）：≥2 个指标 trend_direction=上升
     → 预警等级升一档（趋势持续恶化）
  2) 财务类指标异常（financial_immediate_review）：payment_delay_days 出现
     Z-Score 异常或 anomaly_score ≥ 0.5 → 标记即时复核，预警升至「高」
  3) 高危异常信号（critical_alert）：存在 high 级别告警（z_score/ewma）
     → 触发关键告警，预警升至「紧急」
"""
from __future__ import annotations

from typing import Any

_DEFAULT_RISING_THRESHOLD = 2
_DEFAULT_FINANCIAL_ANOMALY = 0.5
_DEFAULT_FINANCIAL_METRICS = ("payment_delay_days",)

# 预警等级升级顺序（engine 中文等级）
_LEVEL_ORDER = ["低", "中", "高", "紧急"]


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用供应商监控业务规则：趋势升级 / 财务即时复核 / 关键告警。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    rising_threshold = int(
        rules_cfg.get("rising_metrics_threshold", _DEFAULT_RISING_THRESHOLD)
    )
    financial_anomaly = float(
        rules_cfg.get("financial_anomaly_threshold", _DEFAULT_FINANCIAL_ANOMALY)
    )
    financial_metrics = tuple(
        rules_cfg.get("financial_metrics", _DEFAULT_FINANCIAL_METRICS)
    )

    suppliers = result.get("suppliers", []) or []
    rule_summary = {
        "trend_escalated": 0,
        "immediate_review": 0,
        "critical_alert_triggered": 0,
    }

    for s in suppliers:
        analyses = s.get("metric_analyses", {}) or {}
        adjustments = s.setdefault("rule_adjustments", [])

        # 规则 1：多指标上升趋势 → 升级预警
        rising = [
            m for m, a in analyses.items()
            if isinstance(a, dict) and a.get("trend_direction") == "上升"
        ]
        if len(rising) >= rising_threshold:
            s["trend_escalated"] = True
            rule_summary["trend_escalated"] += 1
            adjustments.append(f"多指标上升趋势({len(rising)}个)升级预警")
            _escalate(s)
        else:
            s["trend_escalated"] = False

        # 规则 2：财务类指标异常 → 即时复核
        fin_hit = False
        for fm in financial_metrics:
            a = analyses.get(fm)
            if not isinstance(a, dict):
                continue
            if (a.get("anomaly_score", 0.0) >= financial_anomaly
                    or a.get("z_anomaly_count", 0) > 0):
                fin_hit = True
                break
        if fin_hit:
            s["needs_immediate_review"] = True
            rule_summary["immediate_review"] += 1
            adjustments.append("财务类指标异常触发即时复核")
            _escalate_to(s, "高")
        else:
            s.setdefault("needs_immediate_review", False)

        # 规则 3：高危异常信号 → 关键告警
        has_high_severity = any(
            alert.get("severity") == "high"
            for alert in s.get("alerts", []) or []
            if isinstance(alert, dict)
        )
        if has_high_severity:
            s["critical_alert"] = True
            rule_summary["critical_alert_triggered"] += 1
            adjustments.append("高危异常信号触发关键告警")
            _escalate_to(s, "紧急")
        else:
            s.setdefault("critical_alert", False)

    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    summary["rule_summary"] = rule_summary
    result["summary"] = summary
    return result


def _escalate(s: dict) -> None:
    """预警等级升一档。"""
    cur = s.get("alert_level", "低")
    if cur in _LEVEL_ORDER:
        idx = _LEVEL_ORDER.index(cur)
        s["alert_level"] = _LEVEL_ORDER[min(idx + 1, len(_LEVEL_ORDER) - 1)]


def _escalate_to(s: dict, target: str) -> None:
    """预警等级升级到至少 target 级别。"""
    cur = s.get("alert_level", "低")
    if cur not in _LEVEL_ORDER or target not in _LEVEL_ORDER:
        return
    if _LEVEL_ORDER.index(cur) < _LEVEL_ORDER.index(target):
        s["alert_level"] = target
