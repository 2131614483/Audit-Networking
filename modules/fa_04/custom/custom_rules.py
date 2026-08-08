"""自定义业务规则：在 engine 之后执行，补充催函与差异处置策略。

规则：
  1) 超期 > N 天（默认 30 天）的待回函 → 标记 needs_escalation 并纳入催函升级清单
  2) 差异金额绝对值 > 阈值（默认 10000）→ 标记为重大差异 material=True
  3) 回函数 < 阈值（默认 80%）→ 触发集中催函行动 follow_up_campaign
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

_DEFAULT_OVERDUE_DAYS = 30
_DEFAULT_MATERIAL_DIFF = 10000.0
_DEFAULT_RESPONSE_RATE = 0.8

_PENDING_STATES = ("sent", "delivered", "timeout", "draft")
_RESPONDED_STATES = ("replied", "reconciled", "difference")


def _parse_dt(value: Any) -> datetime | None:
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


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：超期升级 / 重大差异标记 / 回函率催函。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    overdue_days = int(rules_cfg.get("overdue_escalate_days", _DEFAULT_OVERDUE_DAYS))
    material_diff = float(rules_cfg.get("material_diff_amount", _DEFAULT_MATERIAL_DIFF))
    response_rate_threshold = float(rules_cfg.get("response_rate_threshold", _DEFAULT_RESPONSE_RATE))

    now = datetime.now()
    confs = result.get("confirmations", [])
    escalated: list[dict] = []
    material_diffs: list[dict] = []
    follow_up_list: list[dict] = []

    for c in confs:
        # 规则 1：超期 > N 天 → 升级
        c["needs_escalation"] = False
        sent = _parse_dt(c.get("sent_at"))
        if sent is not None and c.get("status") in _PENDING_STATES:
            days = (now - sent).days
            if days > overdue_days:
                c["needs_escalation"] = True
                escalated.append({
                    "confirmation_id": c.get("confirmation_id"),
                    "bank": c.get("bank_or_counterparty"),
                    "status": c.get("status"),
                    "overdue_days": days,
                    "action": "escalate_to_partner",
                })

        # 规则 2：差异金额 > 阈值 → 重大差异
        for d in c.get("diff_records", []) or []:
            dv = d.get("diff_value")
            is_material = dv is not None and abs(float(dv)) > material_diff
            d["material"] = is_material
            if is_material:
                material_diffs.append({
                    "confirmation_id": c.get("confirmation_id"),
                    "bank": c.get("bank_or_counterparty"),
                    "field": d.get("field"),
                    "diff_value": d.get("diff_value"),
                    "diff_pct": d.get("diff_pct"),
                })

        # 待回函纳入催函清单
        if c.get("status") in _PENDING_STATES:
            follow_up_list.append({
                "confirmation_id": c.get("confirmation_id"),
                "bank": c.get("bank_or_counterparty"),
                "status": c.get("status"),
                "channel": c.get("channel", "email"),
                "needs_escalation": c.get("needs_escalation", False),
            })

    # 规则 3：回函率 < 阈值 → 集中催函
    total = len(confs)
    responded = sum(1 for c in confs if c.get("status") in _RESPONDED_STATES)
    response_rate = responded / total if total else 1.0
    follow_up_campaign = response_rate < response_rate_threshold

    result["custom_rules"] = {
        "escalated": escalated,
        "material_diffs": material_diffs,
        "response_rate": round(response_rate, 4),
        "response_rate_threshold": response_rate_threshold,
        "follow_up_campaign": follow_up_campaign,
        "follow_up_list": follow_up_list,
        "overdue_escalate_days": overdue_days,
        "material_diff_amount": material_diff,
    }
    return result
