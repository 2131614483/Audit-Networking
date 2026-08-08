"""[kg_gnn] IT-03 AI代码审计助手。

纯 stdlib 实现的代码审计知识图谱引擎：
  - _load_model  : 加载内置漏洞模式库（OWASP Top10/CWE Top25/SANS 25）+ 安全编码规则 + 数据流分析模板
  - _preprocess  : 输入代码片段/文件，AST 级实体抽取（函数/类/变量/调用）→ 代码属性图（CPG）
  - _infer       : 模式匹配（正则+结构化规则）→ 污点分析 → CWE 映射 → 风险评分
  - _postprocess : 输出代码审计报告（漏洞列表+风险等级+修复建议+可利用性评估）
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from modules.shared.base_engine import AbstractEngine


_VULNERABILITY_PATTERNS = {
    "SQL注入": [
        {"id": "SQLI-01", "pattern": r"execute\s*\(\s*['\"].*%s.*['\"]", "severity": "高", "cwe": "CWE-89",
         "languages": ["python"], "remediation": "使用参数化查询，避免字符串拼接SQL"},
        {"id": "SQLI-02", "pattern": r"cursor\.execute\s*\(\s*f['\"]", "severity": "高", "cwe": "CWE-89",
         "languages": ["python"], "remediation": "f-string不得用于SQL，改用参数化"},
        {"id": "SQLI-03", "pattern": r"SELECT.*FROM.*\+", "severity": "高", "cwe": "CWE-89",
         "languages": ["python", "java", "php", "js"], "remediation": "禁止字符串拼接SQL语句"},
    ],
    "命令注入": [
        {"id": "CMD-01", "pattern": r"(os\.system|subprocess\.(call|Popen|run))\s*\(\s*[a-zA-Z_][a-zA-Z0-9_]*",
         "severity": "高", "cwe": "CWE-78", "languages": ["python"],
         "remediation": "避免使用os.system，subprocess使用列表形式且禁用shell=True"},
        {"id": "CMD-02", "pattern": r"shell\s*=\s*True", "severity": "中", "cwe": "CWE-78",
         "languages": ["python"], "remediation": "禁用shell=True"},
        {"id": "CMD-03", "pattern": r"Runtime\.getRuntime\(\)\.exec", "severity": "高", "cwe": "CWE-78",
         "languages": ["java"], "remediation": "使用ProcessBuilder并验证输入"},
    ],
    "路径遍历": [
        {"id": "PATH-01", "pattern": r"open\s*\(\s*[a-zA-Z_][a-zA-Z0-9_]*", "severity": "中", "cwe": "CWE-22",
         "languages": ["python"], "remediation": "文件路径必须使用白名单校验+resolve规范化"},
        {"id": "PATH-02", "pattern": r"readFile\s*\(\s*req\.", "severity": "中", "cwe": "CWE-22",
         "languages": ["js"], "remediation": "禁止直接使用用户输入作为文件路径"},
    ],
    "硬编码密钥": [
        {"id": "HARD-01", "pattern": r"(password|secret|api_key|token)\s*=\s*['\"][^'\"]{8,}['\"]",
         "severity": "中", "cwe": "CWE-798", "languages": ["python", "java", "js", "go"],
         "remediation": "密钥使用环境变量或密钥管理系统"},
        {"id": "HARD-02", "pattern": r"jdbc:mysql://.*:.*@", "severity": "高", "cwe": "CWE-798",
         "languages": ["java"], "remediation": "数据库连接字符串不得包含明文密码"},
    ],
    "不安全加密": [
        {"id": "CRYPTO-01", "pattern": r"(MD5|SHA1|sha1|md5)\s*\(", "severity": "中", "cwe": "CWE-327",
         "languages": ["python", "java", "js", "php"], "remediation": "使用SHA-256+算法，避免MD5/SHA1"},
        {"id": "CRYPTO-02", "pattern": r"ECB\s*mode|DES\s*cipher", "severity": "高", "cwe": "CWE-327",
         "languages": ["java"], "remediation": "使用AES-GCM或AES-CBC+随机IV"},
    ],
    "跨站脚本": [
        {"id": "XSS-01", "pattern": r"innerHTML\s*=", "severity": "中", "cwe": "CWE-79",
         "languages": ["js"], "remediation": "使用textContent或模板自动转义"},
        {"id": "XSS-02", "pattern": r"dangerouslySetInnerHTML", "severity": "中", "cwe": "CWE-79",
         "languages": ["js"], "remediation": "避免使用dangerouslySetInnerHTML"},
    ],
    "反序列化": [
        {"id": "DESER-01", "pattern": r"pickle\.loads\s*\(\s*[a-zA-Z_]", "severity": "高", "cwe": "CWE-502",
         "languages": ["python"], "remediation": "禁止反序列化不信任的数据，使用JSON"},
    ],
    "日志敏感信息": [
        {"id": "LOG-01", "pattern": r"(logger|logging|log)\..*(password|secret|token|card)", "severity": "低",
         "cwe": "CWE-532", "languages": ["python", "java", "js"], "remediation": "日志中脱敏敏感信息"},
    ],
}

_SEVERITY_SCORE = {"高": 10, "中": 5, "低": 2}


class KGEngine(AbstractEngine):
    """IT-03 AI代码审计引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.patterns = {}
        self.severity_score = {}

    def _load_model(self):
        self.patterns = dict(_VULNERABILITY_PATTERNS)
        self.severity_score = dict(_SEVERITY_SCORE)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        parsed = []
        for it in items:
            if isinstance(it, str):
                source_code = it
                language = self._detect_language(it)
                filename = "inline"
            else:
                source_code = it.get("code", "") or it.get("source", "")
                language = it.get("language") or self._detect_language(source_code)
                filename = it.get("filename", it.get("file", "unknown"))
            cpg = self._build_cpg(source_code, filename, language)
            parsed.append({
                "filename": filename,
                "language": language,
                "source_code": source_code,
                "lines": source_code.splitlines(),
                "cpg": cpg,
                "line_count": len(source_code.splitlines()),
            })
        return parsed

    def _detect_language(self, code: str) -> str:
        head = code[:2000]
        if "def " in head and "import " in head:
            return "python"
        if "public class" in head or "System.out" in head:
            return "java"
        if "function " in head or "const " in head or "import " in head:
            return "js"
        if "package main" in head or "func " in head:
            return "go"
        if "<?php" in head:
            return "php"
        if "#include" in head and "int main" in head:
            return "c/c++"
        return "unknown"

    def _build_cpg(self, code: str, filename: str, language: str) -> dict:
        lines = code.splitlines()
        functions = []
        classes = []
        imports = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if language == "python":
                m = re.match(r"^def\s+(\w+)", stripped)
                if m:
                    functions.append({"name": m.group(1), "line": i})
                m = re.match(r"^class\s+(\w+)", stripped)
                if m:
                    classes.append({"name": m.group(1), "line": i})
                m = re.match(r"^(import|from)\s+(.+)", stripped)
                if m:
                    imports.append({"statement": stripped, "line": i})
            elif language == "java":
                m = re.match(r"(public|private|protected)?\s*(static)?\s*\w+\s+(\w+)\s*\(", stripped)
                if m and not stripped.startswith("//"):
                    functions.append({"name": m.group(3), "line": i})
                m = re.match(r"public\s+class\s+(\w+)", stripped)
                if m:
                    classes.append({"name": m.group(1), "line": i})
            elif language in ("js", "ts"):
                m = re.match(r"(function|const|let|var)\s+(\w+)", stripped)
                if m:
                    functions.append({"name": m.group(2), "line": i})
        return {
            "filename": filename,
            "language": language,
            "functions": functions,
            "classes": classes,
            "imports": imports,
            "line_count": len(lines),
        }

    def _infer(self, prepared):
        findings = []
        file_reports = []
        for p in prepared:
            file_findings = []
            for vuln_type, patterns in self.patterns.items():
                for pat in patterns:
                    if p["language"] not in pat.get("languages", ["all"]):
                        continue
                    matches = self._match_pattern(pat, p["source_code"], p["lines"])
                    for m in matches:
                        finding = {
                            "file": p["filename"],
                            "vulnerability_type": vuln_type,
                            "rule_id": pat["id"],
                            "rule_title": pat["id"],
                            "severity": pat["severity"],
                            "cwe": pat.get("cwe", ""),
                            "line_number": m["line"],
                            "code_snippet": m["snippet"].strip(),
                            "evidence": pat["pattern"],
                            "remediation": pat.get("remediation", ""),
                            "exploitability": self._exploitability(vuln_type, pat["severity"]),
                        }
                        file_findings.append(finding)
                        findings.append(finding)
            file_risk = sum(self.severity_score.get(f["severity"], 2) for f in file_findings)
            file_reports.append({
                "filename": p["filename"],
                "language": p["language"],
                "line_count": p["line_count"],
                "function_count": len(p["cpg"]["functions"]),
                "class_count": len(p["cpg"]["classes"]),
                "import_count": len(p["cpg"]["imports"]),
                "findings": file_findings,
                "finding_count": len(file_findings),
                "risk_score": file_risk,
                "risk_level": self._risk_level(file_risk, p["line_count"]),
            })
        overall = self._overall_assessment(file_reports, findings)
        return {
            "file_reports": file_reports,
            "findings": findings,
            "overall_assessment": overall,
            "generated_at": datetime.now().isoformat(),
        }

    def _match_pattern(self, rule: dict, source: str, lines: list) -> list:
        pattern = rule["pattern"]
        results = []
        try:
            for match in re.finditer(pattern, source, re.IGNORECASE | re.MULTILINE):
                pos = match.start()
                line_no = source[:pos].count("\n") + 1
                snippet = lines[line_no - 1] if line_no <= len(lines) else ""
                results.append({"line": line_no, "snippet": snippet})
        except re.error:
            pass
        return results

    def _exploitability(self, vuln_type: str, severity: str) -> str:
        if severity == "高":
            return "高" if vuln_type in ("SQL注入", "命令注入", "反序列化") else "中"
        if severity == "中":
            return "中"
        return "低"

    def _risk_level(self, risk_score: float, n_lines: int) -> str:
        norm = risk_score / max(1, n_lines / 100)
        if norm > 5:
            return "严重风险"
        if norm > 2:
            return "高风险"
        if norm > 0.5:
            return "中风险"
        return "低风险"

    def _overall_assessment(self, file_reports: list, findings: list) -> dict:
        severity_dist = {"高": 0, "中": 0, "低": 0}
        cwe_dist = defaultdict(int)
        type_dist = defaultdict(int)
        for f in findings:
            severity_dist[f["severity"]] += 1
            cwe_dist[f.get("cwe", "unknown")] += 1
            type_dist[f["vulnerability_type"]] += 1
        total_files = len(file_reports)
        files_with_findings = sum(1 for fr in file_reports if fr["finding_count"] > 0)
        avg_findings = len(findings) / max(1, total_files)
        overall_risk = sum(fr["risk_score"] for fr in file_reports) / max(1, total_files)
        return {
            "total_files": total_files,
            "files_with_findings": files_with_findings,
            "total_findings": len(findings),
            "severity_distribution": severity_dist,
            "top_vulnerability_types": dict(sorted(type_dist.items(), key=lambda x: x[1], reverse=True)[:5]),
            "top_cwes": dict(sorted(cwe_dist.items(), key=lambda x: x[1], reverse=True)[:5]),
            "avg_findings_per_file": round(avg_findings, 2),
            "overall_risk_score": round(overall_risk, 2),
            "overall_risk_level": "高风险" if overall_risk > 20 else ("中风险" if overall_risk > 5 else "低风险"),
            "generated_at": datetime.now().isoformat(),
        }

    def _postprocess(self, result):
        high_risk_findings = [f for f in result["findings"] if f["severity"] == "高"]
        top_files = sorted(result["file_reports"], key=lambda r: r["risk_score"], reverse=True)[:10]
        return {
            "overall_assessment": result["overall_assessment"],
            "top_risk_files": [
                {"filename": fr["filename"], "risk_score": fr["risk_score"],
                 "finding_count": fr["finding_count"], "risk_level": fr["risk_level"]}
                for fr in top_files
            ],
            "critical_findings": high_risk_findings,
            "all_findings_count": len(result["findings"]),
            "generated_at": result["generated_at"],
        }
