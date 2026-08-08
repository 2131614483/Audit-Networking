"""统一输出格式化：函证管理报告（状态摘要 + 异常清单 + 催函清单）。

输出结构：
  {
    "status": "ok",
    "module": "FA-04",
    "dashboard": { total, status_counts, replied_count, diff_count,
                   timeout_count, escalations, transition_count },
    "confirmations": [ {confirmation_id, type, status, bank, ...}, ... ],
    "exceptions": [ {confirmation_id, bank, diff_type, detail, assignee,
                     material}, ... ],
    "follow_up_list": [ {confirmation_id, bank, status, channel,
                         needs_escalation}, ... ],
    "escalations": [ {confirmation_id, bank, level, channel, hours_elapsed}, ... ],
    "transitions": [ {confirmation_id, from, to, reason}, ... ],
    "grading": { severity_distribution, exception_distribution, thresholds },
    "custom_rules": { response_rate, follow_up_campaign, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外函证管理报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    dashboard = result.get("dashboard", {})
    confirmations = result.get("confirmations", [])
    reconciliations = result.get("reconciliations", [])
    escalations = result.get("escalations", [])
    transitions = result.get("transitions", [])
    custom = result.get("custom_rules", {})
    grading = result.get("grading", {})

    # 函证明细表
    details = []
    for c in confirmations:
        details.append({
            "confirmation_id": c.get("confirmation_id"),
            "type": c.get("type"),
            "status": c.get("status"),
            "bank": c.get("bank_or_counterparty"),
            "account_number": c.get("account_number"),
            "channel": c.get("channel", "email"),
            "sent_at": c.get("sent_at"),
            "replied_at": c.get("replied_at"),
            "deadline": c.get("deadline"),
            "audit_values_hash": c.get("audit_values_hash"),
            "diff_count": len(c.get("diff_records", []) or []),
            "overdue_severity": c.get("overdue_severity", "none"),
            "exception_level": c.get("exception_level", "none"),
            "needs_escalation": c.get("needs_escalation", False),
        })

    # 异常清单：合并回函差异（含重大差异标记）
    material_ids = {
        (m.get("confirmation_id"), m.get("field"))
        for m in custom.get("material_diffs", [])
    }
    exceptions = []
    for r in reconciliations:
        cid = r.get("confirmation_id")
        field = None
        for d in _find_diff(confirmations, cid):
            if d.get("detail") == r.get("detail"):
                field = d.get("field")
                break
        exceptions.append({
            "confirmation_id": cid,
            "bank": r.get("bank"),
            "diff_type": r.get("diff_type"),
            "detail": r.get("detail"),
            "assignee": r.get("assignee"),
            "material": (cid, field) in material_ids,
        })

    # 催函清单
    follow_up_list = custom.get("follow_up_list", [])

    return {
        "status": "ok",
        "module": "FA-04",
        "dashboard": {
            "total": dashboard.get("total", len(confirmations)),
            "status_counts": dashboard.get("status_counts", {}),
            "replied_count": dashboard.get("replied_count", 0),
            "diff_count": dashboard.get("diff_count", 0),
            "timeout_count": dashboard.get("timeout_count", 0),
            "escalations": dashboard.get("escalations", len(escalations)),
            "transition_count": dashboard.get("transition_count", len(transitions)),
        },
        "confirmations": details,
        "exceptions": exceptions,
        "follow_up_list": follow_up_list,
        "escalations": escalations,
        "transitions": transitions,
        "grading": grading,
        "custom_rules": {
            "response_rate": custom.get("response_rate", 1.0),
            "follow_up_campaign": custom.get("follow_up_campaign", False),
            "escalated_count": len(custom.get("escalated", [])),
            "material_diff_count": len(custom.get("material_diffs", [])),
            "follow_up_count": len(follow_up_list),
        },
    }


def _find_diff(confirmations: list, cid: str) -> list:
    """根据 confirmation_id 查找其 diff_records。"""
    for c in confirmations:
        if c.get("confirmation_id") == cid:
            return c.get("diff_records", []) or []
    return []
