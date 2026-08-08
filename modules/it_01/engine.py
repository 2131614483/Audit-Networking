"""[rpa] IT-01 IT审计自动化平台。

纯 stdlib 实现的 IT 审计自动化引擎：
  - _load_model  : 加载内置 IT 审计程序库（按领域×风险类型）+ RPA 动作模板 + 证据采集规则
  - _preprocess  : 输入 IT 审计范围（系统/区域/风险域），展开审计程序清单 → RPA 执行计划
  - _infer       : 模拟 RPA 执行（动作链编排+失败重试+凭证校验）→ 自动取证 + 合规检查
  - _postprocess : 输出审计执行报告（程序状态+发现项+证据链+执行日志+审计结论）
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta

from modules.shared.base_engine import AbstractEngine


_IT_DOMAINS = {
    "身份与访问管理": {
        "programs": [
            {"id": "IAM-01", "name": "账号生命周期检查", "risk_level": "高",
             "actions": ["导出用户清单", "检查离职账号", "检查闲置账号(>90天)", "检查特权账号", "生成差异报告"],
             "checks": ["离职账号必须禁用", "闲置账号(>90天)必须禁用", "特权账号需双人审批"],
             "duration_min": 45},
            {"id": "IAM-02", "name": "权限矩阵审计", "risk_level": "高",
             "actions": ["导出角色-权限-用户矩阵", "检查 SoD 冲突", "检查过度授权", "检查默认账号"],
             "checks": ["SoD 冲突数量≤阈值", "过度授权账号≤5%", "无默认启用账号"],
             "duration_min": 60},
            {"id": "IAM-03", "name": "审计日志检查", "risk_level": "中",
             "actions": ["导出登录日志", "检查异常登录(时间/地点)", "检查批量创建/删除操作", "检查特权操作"],
             "checks": ["异常登录告警已触发", "批量操作有审批记录", "日志保留≥180天"],
             "duration_min": 30},
        ],
    },
    "网络安全": {
        "programs": [
            {"id": "NET-01", "name": "防火墙规则审计", "risk_level": "高",
             "actions": ["导出防火墙规则", "检查冗余规则", "检查开放端口", "检查规则变更记录"],
             "checks": ["无全开放规则(any-any)", "开放端口列表合规", "规则变更有审批"],
             "duration_min": 50},
            {"id": "NET-02", "name": "网络分割检查", "risk_level": "中",
             "actions": ["检查 VLAN 配置", "检查 ACL 规则", "检查 DMZ 隔离", "检查 VPN 策略"],
             "checks": ["生产/办公/DMZ 网络隔离", "ACL 规则最小权限", "VPN 强认证"],
             "duration_min": 40},
        ],
    },
    "数据安全": {
        "programs": [
            {"id": "DS-01", "name": "敏感数据识别与分类", "risk_level": "高",
             "actions": ["扫描数据库表结构", "识别 PII/财务/健康数据", "检查分类标签", "检查加密状态"],
             "checks": ["敏感数据已分类", "PII 字段加密/脱敏", "访问日志完整"],
             "duration_min": 55},
            {"id": "DS-02", "name": "数据库权限审计", "risk_level": "高",
             "actions": ["导出 DB 用户列表", "检查 DBA 权限分配", "检查生产库远程访问", "检查审计功能"],
             "checks": ["DBA 账号双人复核", "生产库禁止直连", "审计功能启用"],
             "duration_min": 35},
        ],
    },
    "系统运维": {
        "programs": [
            {"id": "OPS-01", "name": "补丁管理检查", "risk_level": "中",
             "actions": ["导出服务器清单", "检查补丁级别", "检查补丁管理系统", "检查紧急补丁处置"],
             "checks": ["关键补丁30天内安装", "补丁有测试记录", "过期系统支持明确"],
             "duration_min": 40},
            {"id": "OPS-02", "name": "备份恢复审计", "risk_level": "中",
             "actions": ["检查备份配置", "检查最近备份成功率", "检查恢复演练记录", "检查备份介质"],
             "checks": ["备份成功率≥99%", "季度恢复演练", "备份介质异地存放"],
             "duration_min": 30},
        ],
    },
}


class RPAEngine(AbstractEngine):
    """IT-01 IT审计自动化引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.domains = {}
        self.rpa_success_rate = 0.92

    def _load_model(self):
        self.domains = dict(_IT_DOMAINS)
        self.rpa_success_rate = self.config.get("rpa_success_rate", 0.92)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        plans = []
        for it in items:
            selected_domains = it.get("domains", list(self.domains.keys()))
            systems = it.get("systems", ["主业务系统", "OA系统"])
            risk_focus = it.get("risk_focus", ["高", "中"])
            programs = []
            for domain in selected_domains:
                if domain not in self.domains:
                    continue
                for prog in self.domains[domain]["programs"]:
                    if prog["risk_level"] in risk_focus:
                        programs.append({**prog, "domain": domain})
            for prog in programs:
                prog_copy = dict(prog)
                prog_copy["systems"] = systems
                prog_copy["estimated_duration"] = prog.get("duration_min", 30)
                prog_copy["priority"] = {"高": 1, "中": 2, "低": 3}.get(prog["risk_level"], 3)
                plans.append(prog_copy)
            plans.sort(key=lambda p: p["priority"])
        return plans

    def _infer(self, prepared):
        executions = []
        findings = []
        evidence_chain = []
        now = datetime.now()
        for prog in prepared:
            exec_result = self._execute_program(prog)
            executions.append(exec_result)
            for check in prog["checks"]:
                finding = self._evaluate_check(check, exec_result, prog)
                if finding:
                    findings.append(finding)
            evidence_item = {
                "program_id": prog["id"],
                "program_name": prog["name"],
                "evidence_hash": hashlib.sha256(
                    f"{prog['id']}|{exec_result['status']}|{now.isoformat()}".encode()
                ).hexdigest()[:16],
                "collected_at": (now - timedelta(minutes=prog["estimated_duration"])).isoformat(),
                "systems_checked": prog.get("systems", []),
            }
            evidence_chain.append(evidence_item)
        summary = self._summarize(executions, findings)
        return {
            "executions": executions,
            "findings": findings,
            "evidence_chain": evidence_chain,
            "summary": summary,
            "generated_at": now.isoformat(),
        }

    def _execute_program(self, prog: dict) -> dict:
        actions = prog.get("actions", [])
        action_results = []
        failed_actions = 0
        for act in actions:
            import random
            success = random.random() < self.rpa_success_rate
            if not success:
                failed_actions += 1
            action_results.append({
                "action": act,
                "status": "success" if success else "failed",
                "retry_count": 1 if not success else 0,
                "duration_sec": round(15 + 45 * random.random(), 1),
            })
        total = len(actions)
        success_count = total - failed_actions
        if failed_actions == 0:
            status = "completed"
        elif failed_actions <= 2 and success_count / total >= 0.7:
            status = "partial"
        else:
            status = "blocked"
        return {
            "program_id": prog["id"],
            "program_name": prog["name"],
            "domain": prog["domain"],
            "status": status,
            "risk_level": prog["risk_level"],
            "total_actions": total,
            "success_actions": success_count,
            "failed_actions": failed_actions,
            "action_results": action_results,
            "duration_min": prog["estimated_duration"],
        }

    def _evaluate_check(self, check: str, exec_result: dict, prog: dict) -> dict | None:
        violations = 0
        critical_keywords = ["必须", "禁止", "不得", "应"]
        has_critical = any(kw in check for kw in critical_keywords)
        import random
        pass_rate = {"高": 0.75, "中": 0.85, "低": 0.95}.get(prog["risk_level"], 0.85)
        passed = random.random() < pass_rate
        if not passed:
            severity = "高" if has_critical and prog["risk_level"] == "高" else ("中" if prog["risk_level"] == "高" else "低")
            return {
                "program_id": prog["id"],
                "program_name": prog["name"],
                "domain": prog["domain"],
                "check": check,
                "severity": severity,
                "status": "failed",
                "recommendation": self._recommend_fix(check, prog),
            }
        return None

    def _recommend_fix(self, check: str, prog: dict) -> str:
        if "离职账号" in check:
            return "建立 HR-IT 账号自动停用流程，离职当日禁用账号并30天后删除"
        if "SoD" in check:
            return "执行 SoD 冲突分析，对冲突账号进行角色拆分或审批豁免"
        if "防火墙" in check or "开放端口" in check:
            return "执行防火墙规则清理，关闭不必要端口，保留规则变更审批流程"
        if "补丁" in check:
            return "建立补丁管理流程，关键漏洞30天内修复，非关键90天内修复"
        if "备份" in check:
            return "恢复备份策略，确保月度恢复演练，异地备份保留"
        if "敏感数据" in check or "加密" in check:
            return "部署数据分类分级系统，敏感字段强制加密，访问脱敏展示"
        return f"针对「{check}」建议制定专项整改计划"

    def _summarize(self, executions: list, findings: list) -> dict:
        by_domain = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        for e in executions:
            d = e["domain"]
            by_domain[d]["total"] += 1
            if e["status"] == "completed":
                by_domain[d]["passed"] += 1
            else:
                by_domain[d]["failed"] += 1
        high_sev = sum(1 for f in findings if f["severity"] == "高")
        medium_sev = sum(1 for f in findings if f["severity"] == "中")
        low_sev = sum(1 for f in findings if f["severity"] == "低")
        completion_rate = sum(1 for e in executions if e["status"] == "completed") / max(1, len(executions))
        risk_score = (high_sev * 10 + medium_sev * 5 + low_sev * 2) / max(1, len(executions))
        return {
            "total_programs": len(executions),
            "completion_rate": round(completion_rate, 3),
            "findings_count": len(findings),
            "high_severity": high_sev,
            "medium_severity": medium_sev,
            "low_severity": low_sev,
            "domain_summary": dict(by_domain),
            "overall_risk_score": round(min(100, risk_score), 1),
            "risk_level": "高风险" if risk_score > 30 else ("中风险" if risk_score > 15 else "低风险"),
        }

    def _postprocess(self, result):
        open_findings = [f for f in result["findings"]]
        return {
            "audit_plan": {
                "total_programs": result["summary"]["total_programs"],
                "domains_covered": list(result["summary"]["domain_summary"].keys()),
            },
            "execution_status": {
                "completion_rate": result["summary"]["completion_rate"],
                "programs": result["executions"],
            },
            "findings": {
                "open": open_findings,
                "by_severity": {
                    "high": [f for f in open_findings if f["severity"] == "高"],
                    "medium": [f for f in open_findings if f["severity"] == "中"],
                    "low": [f for f in open_findings if f["severity"] == "低"],
                },
            },
            "evidence": result["evidence_chain"],
            "conclusion": {
                "risk_level": result["summary"]["risk_level"],
                "risk_score": result["summary"]["overall_risk_score"],
                "recommendation": self._final_recommendation(result["summary"]),
            },
            "generated_at": result["generated_at"],
        }

    @staticmethod
    def _final_recommendation(summary: dict) -> str:
        if summary["risk_level"] == "高风险":
            return "建议立即启动 IT 安全专项整改，优先处理高严重性发现项，暂停相关系统变更"
        if summary["risk_level"] == "中风险":
            return "建议制定季度整改计划，高优先项纳入下月迭代，建立风险闭环机制"
        return "IT 控制整体有效，建议持续优化，关注低严重性发现项的趋势性变化"
