"""自定义业务规则：在 engine 之后执行，标记配置合规违规与系统性问题。

规则（基于 engine 产出的 host_reports / rule_results，其中 passed=False 即偏差）：
  1) critical_config_deviation  —— 高严重度配置偏差 → 立即告警
     任意主机存在 severity="高" 的未通过规则，生成 critical_alert。
  2) password_policy_violation  —— 密码策略不合规 → 安全标记
     任意主机存在 cwe="CWE-521" 的未通过规则，生成 security_flag。
  3) systemic_deviation         —— 同一规则在多台主机失效 → 系统性问题
     同一 rule_id 在 >=2 台主机未通过，标记为 systemic_issue。

critical_alert 会将该主机 compliance_level 强制降级为 non_compliant。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

# 密码策略相关 CWE
_PASSWORD_CWE = "CWE-521"
# 触发系统性问题的最小主机数
_SYSTEMIC_MIN_HOSTS = 2


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：生成告警清单、安全标记与系统性问题列表。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    disabled = set(rules_cfg.get("disabled", []))

    host_reports = result.get("host_reports", [])
    critical_alerts: list[dict] = []
    security_flags: list[dict] = []
    rule_violation_hosts: dict[str, list[str]] = defaultdict(list)
    rule_meta: dict[str, dict] = {}

    for host in host_reports:
        hostname = host.get("hostname", "unknown")
        host_alerts: list[dict] = []
        host_flags: list[dict] = []
        for rr in host.get("rule_results", []):
            if rr.get("passed", True):
                continue
            rid = rr.get("rule_id", "")
            severity = rr.get("severity", "")
            cwe = rr.get("cwe", "")
            rule_meta[rid] = {
                "title": rr.get("title", ""),
                "severity": severity,
                "cwe": cwe,
                "remediation": rr.get("remediation", ""),
            }
            rule_violation_hosts[rid].append(hostname)

            # 规则1：高严重度偏差 → 立即告警
            if "critical_config_deviation" not in disabled and severity == "高":
                host_alerts.append({
                    "rule_id": rid,
                    "title": rr.get("title", ""),
                    "hostname": hostname,
                    "severity": severity,
                    "cwe": cwe,
                    "remediation": rr.get("remediation", ""),
                })

            # 规则2：密码策略不合规 → 安全标记
            if "password_policy_violation" not in disabled and cwe == _PASSWORD_CWE:
                host_flags.append({
                    "rule_id": rid,
                    "title": rr.get("title", ""),
                    "hostname": hostname,
                    "severity": severity,
                    "cwe": cwe,
                    "remediation": rr.get("remediation", ""),
                })

        critical_alerts.extend(host_alerts)
        security_flags.extend(host_flags)
        host["critical_alerts"] = host_alerts
        host["security_flags"] = host_flags
        # 立即告警 → 强制降级为 non_compliant
        if host_alerts:
            host["compliance_level"] = "non_compliant"

    # 规则3：同一规则多主机失效 → 系统性问题
    systemic_issues: list[dict] = []
    if "systemic_deviation" not in disabled:
        for rid, hosts in rule_violation_hosts.items():
            unique_hosts = sorted(set(hosts))
            if len(unique_hosts) >= _SYSTEMIC_MIN_HOSTS:
                meta = rule_meta.get(rid, {})
                systemic_issues.append({
                    "rule_id": rid,
                    "title": meta.get("title", ""),
                    "severity": meta.get("severity", ""),
                    "cwe": meta.get("cwe", ""),
                    "affected_hosts": unique_hosts,
                    "affected_count": len(unique_hosts),
                    "remediation": meta.get("remediation", ""),
                })

    # 重新统计 compliance_levels（rules 可能降级了部分主机）
    counts = {"compliant": 0, "warning": 0, "non_compliant": 0}
    for host in host_reports:
        counts[host.get("compliance_level", "non_compliant")] += 1

    summary = result.get("scan_summary", {})
    summary["compliance_levels"] = counts
    summary["alerts"] = {
        "critical_alerts": len(critical_alerts),
        "security_flags": len(security_flags),
        "systemic_issues": len(systemic_issues),
    }
    result["scan_summary"] = summary
    result["critical_alerts"] = critical_alerts
    result["security_flags"] = security_flags
    result["systemic_issues"] = systemic_issues
    return result
