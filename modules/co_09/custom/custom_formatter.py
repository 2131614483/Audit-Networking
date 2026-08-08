"""统一输出格式化：隐私合规报告（违规清单 + 差距分析 + 整改计划）。

输出结构：
  {
    "status": "ok",
    "module": "CO-09",
    "policies": [ {policy_id, overall_score, grade, compliance_level,
                    violations, findings, ...}, ... ],
    "gap_analysis": { missing_categories, weak_categories, by_policy },
    "remediation_plan": [ {policy_id, category, priority, recommendation, ...} ],
    "summary": { ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    policies = result.get("policies", [])
    summary = result.get("summary", {})

    policy_reports = []
    gap_missing: list[str] = []
    gap_weak: list[str] = []
    gap_by_policy: list[dict] = []
    remediation_plan: list[dict] = []

    for p in policies:
        findings = p.get("findings", [])
        report = {
            "policy_id": p.get("policy_id"),
            "name": p.get("name"),
            "publisher": p.get("publisher"),
            "language": p.get("language"),
            "overall_score": p.get("overall_score"),
            "grade": p.get("grade"),
            "compliance_level": p.get("compliance_level"),
            "dimension_scores": p.get("dimension_scores", {}),
            "violations": p.get("violations", []),
            "violation_count": p.get("violation_count", 0),
            "findings": [
                {
                    "category_id": f.get("category_id"),
                    "category_name": f.get("category_name"),
                    "status": f.get("status"),
                    "score": f.get("score"),
                    "recommendation": f.get("recommendation"),
                    "legal_refs": f.get("legal_refs", {}),
                }
                for f in findings
            ],
        }
        policy_reports.append(report)

        # 差距分析：缺失/薄弱条款
        missing = [f["category_name"] for f in findings
                   if f.get("status") == "missing"]
        weak = [f["category_name"] for f in findings
                if f.get("status") == "weak"]
        gap_missing.extend(missing)
        gap_weak.extend(weak)
        gap_by_policy.append({
            "policy_id": p.get("policy_id"),
            "missing_count": len(missing),
            "weak_count": len(weak),
            "missing": missing,
            "weak": weak,
        })

        # 整改计划
        for f in findings:
            status = f.get("status")
            if status in ("missing", "weak", "partial"):
                remediation_plan.append({
                    "policy_id": p.get("policy_id"),
                    "category_id": f.get("category_id"),
                    "category_name": f.get("category_name"),
                    "priority": "high" if status == "missing" else (
                        "medium" if status == "weak" else "low"),
                    "recommendation": f.get("recommendation"),
                    "legal_refs": f.get("legal_refs", {}),
                })

    return {
        "status": "ok",
        "module": "CO-09",
        "policies": policy_reports,
        "gap_analysis": {
            "missing_categories": sorted(set(gap_missing)),
            "weak_categories": sorted(set(gap_weak)),
            "by_policy": gap_by_policy,
        },
        "remediation_plan": remediation_plan,
        "summary": {
            "total_policies": summary.get("total_policies", len(policies)),
            "total_findings": summary.get("total_findings", 0),
            "average_overall_score": summary.get("average_overall_score", 0.0),
            "by_status": summary.get("by_status", {}),
            "policies_by_grade": summary.get("policies_by_grade", {}),
            "compliance_levels": summary.get("compliance_levels", {}),
            "violations": summary.get("violations", {
                "total": 0, "critical": 0, "high": 0, "medium": 0,
            }),
        },
    }
