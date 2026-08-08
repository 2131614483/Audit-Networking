"""自定义业务规则：在 engine 之后执行，标记隐私合规违规。

规则（基于 engine 产出的条款 findings 的 status：missing/weak/partial/compliant）：
  1) legal_basis 缺失/薄弱 → critical_violation（缺失同意/法律依据 → 严重违规）
  2) retention 缺失/薄弱 → data_breach（存储期限合规违规）
  3) cross_border 缺失/薄弱 → cross_border_escalation（跨境传输未获充分审批 → 升级）
  4) data_subject_rights 缺失 → rights_violation（数据主体权利保障缺失）
  5) security 缺失/薄弱 → security_gap（数据安全措施不足）
严重违规会强制将 compliance_level 降级为 non_compliant。
"""
from __future__ import annotations

from typing import Any

# category_id → (违规类型, 严重度, 描述)
_RULE_MAP = {
    "legal_basis": ("missing_consent", "critical", "缺失数据处理法律依据/同意机制"),
    "retention": ("retention_breach", "high", "数据存储期限合规违规"),
    "cross_border": ("cross_border_escalation", "high", "跨境数据传输未获充分审批"),
    "data_subject_rights": ("rights_violation", "high", "数据主体权利保障缺失"),
    "security": ("security_gap", "medium", "数据安全措施不足"),
}

_NON_COMPLIANT_STATUSES = {"missing", "weak"}


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：根据条款缺失/薄弱情况生成违规清单与降级。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    disabled = set(rules_cfg.get("disabled", []))

    policies = result.get("policies", [])
    total_violations = 0
    critical_count = 0
    high_count = 0
    medium_count = 0

    for p in policies:
        violations = []
        findings = p.get("findings", [])
        findings_by_cat = {f["category_id"]: f for f in findings}
        for cat_id, (vtype, severity, desc) in _RULE_MAP.items():
            if cat_id in disabled:
                continue
            f = findings_by_cat.get(cat_id)
            if f is None:
                continue
            status = f.get("status", "")
            if status in _NON_COMPLIANT_STATUSES:
                violations.append({
                    "violation_type": vtype,
                    "severity": severity,
                    "category_id": cat_id,
                    "category_name": f.get("category_name", ""),
                    "status": status,
                    "score": f.get("score", 0.0),
                    "description": desc,
                    "legal_refs": f.get("legal_refs", {}),
                })
                total_violations += 1
                if severity == "critical":
                    critical_count += 1
                elif severity == "high":
                    high_count += 1
                else:
                    medium_count += 1
        p["violations"] = violations
        p["violation_count"] = len(violations)
        # 严重违规 → 强制降级为 non_compliant
        if any(v["severity"] == "critical" for v in violations):
            p["compliance_level"] = "non_compliant"

    # 重新统计 compliance_levels（rules 可能降级了部分 policy）
    counts = {"compliant": 0, "partial": 0, "non_compliant": 0}
    for p in policies:
        counts[p.get("compliance_level", "non_compliant")] += 1

    summary = result.get("summary", {})
    summary["compliance_levels"] = counts
    summary["violations"] = {
        "total": total_violations,
        "critical": critical_count,
        "high": high_count,
        "medium": medium_count,
    }
    result["summary"] = summary
    return result
