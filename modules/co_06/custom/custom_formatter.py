"""统一输出格式化：SAR 报告对外结构（交易明细 + 叙事 + 证据链 + 监管字段）。

输出结构：
  {
    "status": "ok",
    "module": "CO-06",
    "report_id": ...,
    "regulator": {regulator, template, deadline, format},
    "risk": {level, score, sar_priority, priority_label, ...},
    "narrative_5w1h": ...,
    "evidence_chain": [关联账户/关联方/外部情报/可疑模式 ...],
    "suspicious_patterns": [...],
    "conclusion": {...},
    "transaction_details": [从 template_fields 中提取的交易相关字段 ...],
    "regulatory_fields": {必填字段填充情况、mandatory_fill_rate、auto_fill_rate},
    "report_quality": {...},
    "attachments_suggested": [...],
    "summary": {...}
  }
"""
from __future__ import annotations

from typing import Any

# 交易明细相关的模板字段
_TX_FIELD_KEYS = (
    "tx_time", "tx_amount", "tx_currency", "counterparty",
    "channel", "ip", "tx_pattern", "abnormal_feature",
    "suspicious_reason", "related_accounts", "related_parties", "related_txs",
)


def _build_evidence_chain(result: dict) -> list[str]:
    """从结果中提炼证据链（关联账户/关联方/外部情报/可疑模式/附件）。"""
    chain: list[str] = []
    summary = result.get("summary", {}) or {}
    if summary.get("related_accounts_count"):
        chain.append(f"关联账户 {summary['related_accounts_count']} 个")
    if summary.get("related_parties_count"):
        chain.append(f"关联方 {summary['related_parties_count']} 个")
    for p in result.get("suspicious_patterns", []) or []:
        if isinstance(p, dict):
            chain.append(f"可疑模式[{p.get('code')}]：{p.get('reason', '')}")
    # 规则标记也作为证据
    for flag in result.get("rule_flags", []) or []:
        if isinstance(flag, dict):
            chain.append(f"业务规则[{flag.get('rule')}]：{flag.get('detail', '')}")
    conclusion = result.get("conclusion", {}) or {}
    for reason in conclusion.get("reasons", []) or []:
        chain.append(f"结论依据：{reason}")
    if not chain:
        chain.append("无可疑证据链")
    return chain


def format_output(result: Any) -> Any:
    """把内部结果转为对外 SAR 报告输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    template_fields = result.get("template_fields", {}) or {}

    # 交易明细字段
    transaction_details = {}
    for k in _TX_FIELD_KEYS:
        if k in template_fields:
            transaction_details[k] = template_fields[k].get("value")

    # 监管必填字段填充情况
    mandatory_fields = {}
    for name, field in template_fields.items():
        if isinstance(field, dict) and field.get("is_mandatory"):
            mandatory_fields[name] = {
                "filled": bool(field.get("value")),
                "value": field.get("value"),
            }

    quality = result.get("report_quality", {}) or {}
    conclusion = result.get("conclusion", {}) or {}

    return {
        "status": "ok",
        "module": "CO-06",
        "report_id": result.get("report_id"),
        "alert_id": result.get("alert_id"),
        "regulator": {
            "name": result.get("template", {}).get("regulator"),
            "template": result.get("template", {}).get("name"),
            "submission_deadline": result.get("submission_deadline"),
            "format": result.get("template", {}).get("format"),
        },
        "risk": {
            "level": result.get("risk_level"),
            "score": result.get("risk_score"),
            "sar_priority": result.get("sar_priority"),
            "sar_priority_label": result.get("sar_priority_label"),
            "sar_priority_action": result.get("sar_priority_action"),
            "mandatory_filing": result.get("mandatory_filing", False),
            "cross_border_escalation": result.get("cross_border_escalation", False),
            "network_analysis_required": result.get("network_analysis_required", False),
            "enhanced_due_diligence": result.get("enhanced_due_diligence", False),
        },
        "narrative_5w1h": result.get("narrative_5w1h", ""),
        "evidence_chain": _build_evidence_chain(result),
        "suspicious_patterns": result.get("suspicious_patterns", []),
        "conclusion": {
            "verdict": conclusion.get("verdict"),
            "confidence": conclusion.get("confidence"),
            "reasons": conclusion.get("reasons", []),
            "suggested_actions": conclusion.get("suggested_actions", []),
        },
        "transaction_details": transaction_details,
        "regulatory_fields": {
            "mandatory_fields": mandatory_fields,
            "mandatory_fill_rate": quality.get("mandatory_fill_rate", 0),
            "auto_fill_rate": quality.get("auto_fill_rate", 0),
            "template_fields_count": len(template_fields),
        },
        "report_quality": {
            "total_score": quality.get("total_score", 0),
            "grade": quality.get("grade", ""),
            "breakdown": quality.get("breakdown", {}),
            "output_note": result.get("output_note", ""),
        },
        "rule_flags": result.get("rule_flags", []),
        "attachments_suggested": result.get("attachments_suggested", []),
        "summary": result.get("summary", {}),
    }
