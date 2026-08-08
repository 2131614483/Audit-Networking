"""统一输出格式化：IT 审计执行报告。

输出结构：
  {
    "status": "ok",
    "module": "IT-01",
    "audit_plan": { total_programs, domains_covered, systems_scoped },
    "execution_summary": { completion_rate, total_programs, completed, partial, blocked },
    "findings": [ { program_id, check, severity, priority, recommendation,
                     critical_finding, auto_disable_recommended, mfa_required, ... }, ... ],
    "findings_summary": { total, by_severity, by_domain, critical_count },
    "evidence_chain": [ { program_id, evidence_hash, collected_at, systems_checked }, ... ],
    "recommendations": [ { priority, recommendation, target_programs }, ... ],
    "conclusion": { audit_status, risk_level, risk_score, recommendation, thresholds },
    "generated_at": "..."
  }
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# 严重性 → 英文键
_SEVERITY_MAP = {"高": "high", "中": "medium", "低": "low"}


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    audit_plan = result.get("audit_plan", {}) or {}
    exec_status = result.get("execution_status", {}) or {}
    programs = exec_status.get("programs", []) or []
    findings_block = result.get("findings", {}) or {}
    open_findings = findings_block.get("open", []) if isinstance(findings_block, dict) else []
    by_severity = findings_block.get("by_severity", {}) if isinstance(findings_block, dict) else {}
    evidence_chain = result.get("evidence", []) or []
    conclusion = result.get("conclusion", {}) or {}
    generated_at = result.get("generated_at", "")

    # 执行统计
    completed = sum(1 for p in programs if p.get("status") == "completed")
    partial = sum(1 for p in programs if p.get("status") == "partial")
    blocked = sum(1 for p in programs if p.get("status") == "blocked")

    execution_summary = {
        "total_programs": exec_status.get("total_programs", len(programs)),
        "completion_rate": exec_status.get("completion_rate", 0.0),
        "completed": completed,
        "partial": partial,
        "blocked": blocked,
        "domains_covered": audit_plan.get("domains_covered", []),
        "systems_scoped": _collect_systems(programs),
    }

    # 发现项明细（含规则与阈值标记）
    finding_details = []
    for f in open_findings:
        finding_details.append({
            "program_id": f.get("program_id"),
            "program_name": f.get("program_name"),
            "domain": f.get("domain"),
            "check": f.get("check"),
            "severity": f.get("severity"),
            "priority": f.get("priority"),
            "status": f.get("status"),
            "recommendation": f.get("recommendation"),
            "critical_finding": f.get("critical_finding", False),
            "auto_disable_recommended": f.get("auto_disable_recommended", False),
            "mfa_required": f.get("mfa_required", False),
            "security_risk": f.get("security_risk", False),
            "require_immediate_action": f.get("require_immediate_action", False),
            "rule_adjustments": f.get("rule_adjustments", []),
        })

    # 发现项汇总
    by_domain: dict[str, int] = defaultdict(int)
    for f in open_findings:
        by_domain[f.get("domain", "未分类")] += 1
    findings_summary = {
        "total": len(open_findings),
        "by_severity": {
            "high": len(by_severity.get("high", []) if isinstance(by_severity.get("high", []), list) else []),
            "medium": len(by_severity.get("medium", []) if isinstance(by_severity.get("medium", []), list) else []),
            "low": len(by_severity.get("low", []) if isinstance(by_severity.get("low", []), list) else []),
        },
        "by_domain": dict(by_domain),
        "critical_count": sum(1 for f in open_findings if f.get("critical_finding")),
    }

    # 整改建议（按优先级排序）
    recommendations = []
    sorted_findings = sorted(
        open_findings, key=lambda f: (f.get("priority", 99), f.get("severity", "低"))
    )
    seen_recs: set[str] = set()
    for f in sorted_findings:
        rec = f.get("recommendation", "")
        if not rec or rec in seen_recs:
            continue
        seen_recs.add(rec)
        recommendations.append({
            "priority": f.get("priority"),
            "recommendation": rec,
            "target_program": f.get("program_id"),
            "severity": f.get("severity"),
        })

    return {
        "status": "ok",
        "module": "IT-01",
        "audit_plan": {
            "total_programs": audit_plan.get("total_programs", len(programs)),
            "domains_covered": audit_plan.get("domains_covered", []),
            "systems_scoped": execution_summary["systems_scoped"],
        },
        "execution_summary": execution_summary,
        "findings": finding_details,
        "findings_summary": findings_summary,
        "evidence_chain": [
            {
                "program_id": e.get("program_id"),
                "program_name": e.get("program_name"),
                "evidence_hash": e.get("evidence_hash"),
                "collected_at": e.get("collected_at"),
                "systems_checked": e.get("systems_checked", []),
            }
            for e in evidence_chain
        ],
        "recommendations": recommendations,
        "conclusion": {
            "audit_status": conclusion.get("audit_status"),
            "risk_level": conclusion.get("risk_level"),
            "risk_score": conclusion.get("risk_score"),
            "recommendation": conclusion.get("recommendation"),
            "severity_counts": conclusion.get("severity_counts", {}),
            "thresholds": conclusion.get("thresholds", {}),
            "rule_adjustments": conclusion.get("rule_adjustments", {}),
        },
        "generated_at": generated_at,
    }


def _collect_systems(programs: list) -> list:
    """从 programs 中收集去重后的系统列表。"""
    seen: set = set()
    out: list = []
    for p in programs:
        for s in p.get("systems", []) or []:
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out
