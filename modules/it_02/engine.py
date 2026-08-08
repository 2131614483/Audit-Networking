"""[ml_nlp] IT-02 AI配置合规扫描引擎。

纯 stdlib 实现的配置合规扫描引擎：
  - _load_model  : 加载配置基线规则库（CIS Benchmark等）+ 合规标准映射表 + 偏差评分权重
  - _preprocess  : 输入多系统配置快照（Linux/Windows/网络设备/数据库/应用），标准化解析
  - _infer       : 规则匹配 → 偏差分类 → 风险评分 → 聚合报告
  - _postprocess : 输出合规性报告（合规率+偏差明细+风险热力图+整改优先级）
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import datetime

from modules.shared.base_engine import AbstractEngine


_BASELINE_RULES = {
    "Linux": [
        {"id": "LIN-001", "title": "SSH禁用root登录", "check": "PermitRootLogin no", "severity": "高",
         "cwe": "CWE-732", "remediation": "修改sshd_config中PermitRootLogin为no并重启sshd"},
        {"id": "LIN-002", "title": "SSH启用密码认证", "check": "PasswordAuthentication yes", "negate": True, "severity": "中",
         "cwe": "CWE-521", "remediation": "PasswordAuthentication no，启用密钥认证"},
        {"id": "LIN-003", "title": "密码过期策略", "check": "PASS_MAX_DAYS", "op": "<=", "value": 90, "severity": "中",
         "cwe": "CWE-262", "remediation": "在/etc/login.defs设置PASS_MAX_DAYS 90"},
        {"id": "LIN-004", "title": "防火墙启用", "check": "firewall_active", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-284", "remediation": "启用firewalld/ufw并设置默认deny规则"},
        {"id": "LIN-005", "title": "不必要服务禁用", "check": "unnecessary_services", "op": "==", "value": 0, "severity": "中",
         "cwe": "CWE-1004", "remediation": "停用不需要的系统服务"},
        {"id": "LIN-006", "title": "审计日志启用", "check": "auditd_active", "op": "==", "value": True, "severity": "中",
         "cwe": "CWE-778", "remediation": "安装并启用auditd服务"},
    ],
    "Windows": [
        {"id": "WIN-001", "title": "密码复杂度策略", "check": "PasswordComplexity", "op": ">=", "value": 1, "severity": "高",
         "cwe": "CWE-521", "remediation": "GPO启用密码复杂度要求"},
        {"id": "WIN-002", "title": "账户锁定阈值", "check": "LockoutThreshold", "op": ">=", "value": 5, "severity": "高",
         "cwe": "CWE-307", "remediation": "设置5次无效登录后锁定账户30分钟"},
        {"id": "WIN-003", "title": "自动更新启用", "check": "AutoUpdateEnabled", "op": "==", "value": True, "severity": "中",
         "cwe": "CWE-1059", "remediation": "启用Windows Update自动更新"},
        {"id": "WIN-004", "title": "防火墙启用", "check": "FirewallEnabled", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-284", "remediation": "启用Windows Defender防火墙"},
        {"id": "WIN-005", "title": "防病毒启用", "check": "AntivirusEnabled", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-1059", "remediation": "确保Windows Defender或第三方AV启用"},
    ],
    "Network": [
        {"id": "NET-001", "title": "SSH禁用Telnet", "check": "telnet_enabled", "op": "==", "value": False, "severity": "高",
         "cwe": "CWE-319", "remediation": "禁用Telnet，仅允许SSH"},
        {"id": "NET-002", "title": "SNMPv2禁用", "check": "snmp_version", "op": "==", "value": "v3", "severity": "高",
         "cwe": "CWE-319", "remediation": "升级SNMPv3，禁用v1/v2c"},
        {"id": "NET-003", "title": "默认密码修改", "check": "default_password_changed", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-521", "remediation": "所有网络设备首次部署必须修改默认密码"},
    ],
    "Database": [
        {"id": "DB-001", "title": "数据库审计启用", "check": "audit_enabled", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-778", "remediation": "启用数据库原生审计功能"},
        {"id": "DB-002", "title": "默认账号密码修改", "check": "default_secure", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-521", "remediation": "修改所有默认账号密码"},
        {"id": "DB-003", "title": "SSL/TLS加密连接", "check": "ssl_enabled", "op": "==", "value": True, "severity": "高",
         "cwe": "CWE-319", "remediation": "启用数据库连接SSL/TLS加密"},
        {"id": "DB-004", "title": "公开访问禁用", "check": "public_access", "op": "==", "value": False, "severity": "高",
         "cwe": "CWE-284", "remediation": "限制数据库仅内网访问"},
    ],
}


class MLEngine(AbstractEngine):
    """IT-02 AI配置合规扫描引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.baseline = {}
        self.severity_weights = {"高": 10, "中": 5, "低": 2}

    def _load_model(self):
        self.baseline = dict(_BASELINE_RULES)
        self.severity_weights = self.config.get("severity_weights", self.severity_weights)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        parsed = []
        for it in items:
            platform = it.get("platform", "Linux")
            hostname = it.get("hostname", it.get("device", "unknown"))
            raw_config = it.get("config") or it.get("snapshot", {})
            if isinstance(raw_config, str):
                raw_config = self._parse_kv_config(raw_config)
            parsed.append({
                "hostname": hostname,
                "platform": platform,
                "config": raw_config,
                "ip": it.get("ip", ""),
                "group": it.get("group", "default"),
                "scanned_at": it.get("scanned_at", datetime.now().isoformat()),
            })
        return parsed

    def _parse_kv_config(self, text: str) -> dict:
        config = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = self._convert_value(v.strip())
            elif " " in line:
                parts = line.split(None, 1)
                config[parts[0]] = self._convert_value(parts[1])
        return config

    @staticmethod
    def _convert_value(v: str):
        if v.lower() in ("true", "yes", "on", "enabled"):
            return True
        if v.lower() in ("false", "no", "off", "disabled"):
            return False
        try:
            if "." in v:
                return float(v)
            return int(v)
        except ValueError:
            return v.strip('"').strip("'")

    def _infer(self, prepared):
        results = []
        for host in prepared:
            platform = host["platform"]
            rules = self.baseline.get(platform, [])
            rule_results = []
            violations = 0
            for rule in rules:
                passed = self._evaluate_rule(rule, host["config"])
                if not passed:
                    violations += 1
                rule_results.append({
                    "rule_id": rule["id"],
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "passed": passed,
                    "cwe": rule.get("cwe", ""),
                    "remediation": rule.get("remediation", ""),
                    "evidence": self._collect_evidence(rule, host["config"]),
                })
            compliance_rate = (len(rules) - violations) / max(1, len(rules))
            risk_score = sum(
                self.severity_weights.get(r["severity"], 2) for r in rule_results if not r["passed"]
            )
            results.append({
                "hostname": host["hostname"],
                "platform": platform,
                "ip": host["ip"],
                "group": host["group"],
                "total_rules": len(rules),
                "violations": violations,
                "compliance_rate": round(compliance_rate, 3),
                "risk_score": risk_score,
                "risk_level": self._risk_label(risk_score, len(rules)),
                "rule_results": rule_results,
                "scanned_at": host["scanned_at"],
            })
        summary = self._aggregate(results)
        return {"host_results": results, "summary": summary, "generated_at": datetime.now().isoformat()}

    def _evaluate_rule(self, rule: dict, config: dict) -> bool:
        check_key = rule["check"]
        negate = rule.get("negate", False)
        if "op" in rule:
            actual = config.get(check_key)
            if actual is None:
                return False
            target = rule.get("value")
            op = rule["op"]
            passed = self._compare(actual, op, target)
        else:
            expected = rule["check"]
            actual = self._resolve_check(config, check_key)
            if isinstance(expected, str) and actual is not None:
                passed = expected.lower() in str(actual).lower()
            else:
                passed = actual == expected
        if negate:
            passed = not passed
        return passed

    @staticmethod
    def _resolve_check(config: dict, check_key: str):
        if check_key in config:
            return config[check_key]
        ck_lower = check_key.lower()
        for k, v in config.items():
            if k.lower() == ck_lower:
                return v
        return None

    @staticmethod
    def _compare(actual, op: str, target) -> bool:
        if actual is None:
            return False
        if op == ">=":
            return actual >= target
        if op == "<=":
            return actual <= target
        if op == ">":
            return actual > target
        if op == "<":
            return actual < target
        if op == "==":
            return actual == target
        if op == "!=":
            return actual != target
        return False

    def _collect_evidence(self, rule: dict, config: dict) -> str:
        check = rule["check"]
        actual = self._resolve_check(config, check)
        target = rule.get("value") or rule.get("check", "")
        return f"实际值: {actual}, 期望值: {target}"

    def _risk_label(self, risk_score: float, n_rules: int) -> str:
        expected_max = n_rules * 10
        ratio = risk_score / max(1, expected_max)
        if ratio > 0.3:
            return "高风险"
        if ratio > 0.15:
            return "中风险"
        return "低风险"

    def _aggregate(self, results: list) -> dict:
        total_hosts = len(results)
        total_rules = sum(r["total_rules"] for r in results)
        total_violations = sum(r["violations"] for r in results)
        avg_compliance = sum(r["compliance_rate"] for r in results) / max(1, total_hosts)
        severity_dist = {"高": 0, "中": 0, "低": 0}
        for r in results:
            for rr in r["rule_results"]:
                if not rr["passed"]:
                    severity_dist[rr["severity"]] += 1
        platform_breakdown = defaultdict(lambda: {"hosts": 0, "violations": 0, "total_rules": 0})
        for r in results:
            p = r["platform"]
            platform_breakdown[p]["hosts"] += 1
            platform_breakdown[p]["violations"] += r["violations"]
            platform_breakdown[p]["total_rules"] += r["total_rules"]
        return {
            "total_hosts": total_hosts,
            "total_rules": total_rules,
            "total_violations": total_violations,
            "overall_compliance_rate": round(1 - total_violations / max(1, total_rules), 3),
            "avg_host_compliance": round(avg_compliance, 3),
            "severity_distribution": severity_dist,
            "platform_summary": dict(platform_breakdown),
            "high_risk_hosts": [r["hostname"] for r in results if r["risk_level"] == "高风险"],
        }

    def _postprocess(self, result):
        hot_rules = defaultdict(lambda: {"violations": 0, "severity": "", "remediation": ""})
        for host in result["host_results"]:
            for rr in host["rule_results"]:
                if not rr["passed"]:
                    rid = rr["rule_id"]
                    hot_rules[rid]["violations"] += 1
                    hot_rules[rid]["severity"] = rr["severity"]
                    hot_rules[rid]["remediation"] = rr["remediation"]
        priority_fixes = sorted(
            hot_rules.items(), key=lambda x: x[1]["violations"], reverse=True
        )[:10]
        return {
            "scan_summary": result["summary"],
            "host_reports": result["host_results"],
            "priority_fixes": [
                {"rule_id": rid, **info, "priority": i + 1}
                for i, (rid, info) in enumerate(priority_fixes)
            ],
            "generated_at": result["generated_at"],
        }
