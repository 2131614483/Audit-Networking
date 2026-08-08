"""自定义业务规则：在 engine 之后执行，可覆盖/补充审计发现分级与处置建议。

规则：
  1) SoD 冲突发现 → 标记为 critical_finding，自动升级严重性为「高」
  2) 闲置账号 (>90天) 发现 → 标记 auto_disable_recommended，建议立即禁用
  3) 特权账号相关发现 → 标记 mfa_required 与 security_risk，要求强制 MFA
  4) 高风险域 (身份与访问管理 / 数据安全) 的失败项 → require_immediate_action
"""
from __future__ import annotations

from typing import Any

# 触发关键词
_SOD_KEYWORDS = ("SoD", "职责分离", "冲突")
_DORMANT_KEYWORDS = ("闲置", "90天", "离职", "未启用", "生命周期")
_PRIVILEGED_KEYWORDS = ("特权", "DBA", "管理员", "root", "admin", "超级用户")

# 高风险域：发现项在此域内需立即处置
_HIGH_RISK_DOMAINS = ("身份与访问管理", "数据安全", "网络安全")


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用 IT 审计业务规则：发现项分类 / 严重性升级 / 处置标记。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    sod_critical = bool(rules_cfg.get("sod_critical_finding", True))
    dormant_disable = bool(rules_cfg.get("dormant_auto_disable", True))
    privileged_mfa = bool(rules_cfg.get("privileged_mfa_required", True))

    findings_block = result.get("findings", {})
    open_findings = findings_block.get("open", []) if isinstance(findings_block, dict) else []

    critical_count = 0
    disable_count = 0
    mfa_count = 0
    immediate_action_count = 0

    for f in open_findings:
        if not isinstance(f, dict):
            continue
        check_text = str(f.get("check", ""))
        domain = f.get("domain", "")
        adjustments = f.setdefault("rule_adjustments", [])

        # 规则 1：SoD 冲突 → critical_finding + 升级为高
        if sod_critical and any(kw in check_text for kw in _SOD_KEYWORDS):
            f["critical_finding"] = True
            if f.get("severity") != "高":
                f["severity"] = "高"
                adjustments.append("SoD冲突自动升级为高严重性")
            critical_count += 1
        else:
            f.setdefault("critical_finding", False)

        # 规则 2：闲置账号 → auto_disable_recommended
        if dormant_disable and any(kw in check_text for kw in _DORMANT_KEYWORDS):
            f["auto_disable_recommended"] = True
            if "建议立即禁用" not in f.get("recommendation", ""):
                f["recommendation"] = (
                    f.get("recommendation", "") + " 建议立即禁用该账号并归档审计记录。"
                ).strip()
            disable_count += 1
        else:
            f.setdefault("auto_disable_recommended", False)

        # 规则 3：特权账号 → mfa_required + security_risk
        if privileged_mfa and any(kw in check_text for kw in _PRIVILEGED_KEYWORDS):
            f["mfa_required"] = True
            f["security_risk"] = True
            if "强制MFA" not in f.get("recommendation", ""):
                f["recommendation"] = (
                    f.get("recommendation", "") + " 强制启用多因素认证(MFA)。"
                ).strip()
            mfa_count += 1
        else:
            f.setdefault("mfa_required", False)
            f.setdefault("security_risk", False)

        # 规则 4：高风险域的失败项 → require_immediate_action
        if domain in _HIGH_RISK_DOMAINS:
            f["require_immediate_action"] = True
            immediate_action_count += 1
        else:
            f.setdefault("require_immediate_action", False)

    # 重新分桶 by_severity（因为规则可能升级了严重性）
    if isinstance(findings_block, dict):
        findings_block["by_severity"] = {
            "high": [f for f in open_findings if f.get("severity") == "高"],
            "medium": [f for f in open_findings if f.get("severity") == "中"],
            "low": [f for f in open_findings if f.get("severity") == "低"],
        }

    # 同步结论统计
    conclusion = result.get("conclusion", {}) if isinstance(result.get("conclusion"), dict) else {}
    conclusion["rule_adjustments"] = {
        "critical_findings": critical_count,
        "auto_disable_recommended": disable_count,
        "mfa_required": mfa_count,
        "require_immediate_action": immediate_action_count,
    }
    result["conclusion"] = conclusion
    return result
