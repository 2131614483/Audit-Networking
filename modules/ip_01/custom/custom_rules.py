"""自定义业务规则：在 engine 之后执行，覆盖/补充结果。

规则：
  1) 财务异常发现强制人工复核：source=ml / category=financial_anomaly 的发现
     → need_manual_review=True，且关联任务降级为 manual_review。
  2) 关联交易 > 阈值标记重点核查：related_transaction 发现
     → 标 key_check=True，关联任务 FIN-05 标 manual_review。
  3) 内控缺陷升级处理：category=internal_control 或 source 含内控缺陷
     → severity 升级为 high（若原本 low/medium），关联任务 IC-03 标 manual_review。
"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """对核查发现应用业务规则：财务异常强制复核 / 关联交易重点核查 / 内控缺陷升级。"""
    if not isinstance(result, dict):
        return result

    tasks_by_id = {t.get("task_id"): t for t in result.get("tasks", [])}
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    related_tx_thr = float(threshold.get("related_tx_amount", 5_000_000))

    for f in result.get("findings", []):
        category = f.get("category", "")
        source = f.get("source", "")
        related_task = f.get("related_task_id")

        # 规则 1：财务异常发现强制人工复核
        if category == "financial_anomaly" or source == "ml":
            f["need_manual_review"] = True
            f["rule_applied"] = "financial_anomaly_force_review"
            if related_task in tasks_by_id:
                _downgrade_to_review(tasks_by_id[related_task])

        # 规则 2：关联交易 > 阈值标记重点核查
        if category == "related_transaction":
            payload = f.get("payload") or {}
            amount = payload.get("amount", 0)
            if amount and amount > related_tx_thr:
                f["key_check"] = True
                f["rule_applied"] = "related_transaction_key_check"
                if "FIN-05" in tasks_by_id:
                    _downgrade_to_review(tasks_by_id["FIN-05"])

        # 规则 3：内控缺陷升级处理
        if category == "internal_control" or "内控" in f.get("description", ""):
            if f.get("severity") in (None, "low", "medium"):
                f["severity"] = "high"
            f["need_manual_review"] = True
            f["escalated"] = True
            f["rule_applied"] = "internal_control_escalation"
            if "IC-03" in tasks_by_id:
                _downgrade_to_review(tasks_by_id["IC-03"])

    return result


def _downgrade_to_review(task: dict) -> None:
    """把任务降级为 manual_review（保证缺陷对应任务必经人工复核）。"""
    # auto_done / pending → manual_review；已是 manual_review / manual 保持
    if task.get("status") in ("auto_done", "pending"):
        task["status"] = "manual_review"
        task["manual_review_reason"] = "finding_triggered"
