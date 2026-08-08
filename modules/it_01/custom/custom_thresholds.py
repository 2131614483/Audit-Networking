"""自定义阈值分级：根据发现项数量与严重性进行整体审计风险分级。

分级规则（可被 config.threshold 覆盖）：
  * critical : high_severity ≥ critical_threshold (默认 3) → 审计失败，需立即整改
  * high     : high_severity ≥ high_threshold (默认 1) → 高风险，限期整改
  * medium   : medium_severity ≥ medium_threshold (默认 3) → 中风险，季度整改
  * low      : 其余情况 → 低风险，持续优化

同时为每个发现项赋予处置优先级 (priority 1-5)：
  1 = 最紧急（critical_finding 或 高严重性 + 高风险域）
  2 = 紧急（高严重性）
  3 = 重要（中严重性 + 高风险域）
  4 = 一般（中严重性）
  5 = 低（低严重性）
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_CRITICAL = 3
_DEFAULT_HIGH = 1
_DEFAULT_MEDIUM = 3

# 优先级常量
_PRIORITY_IMMEDIATE = 1
_PRIORITY_URGENT = 2
_PRIORITY_IMPORTANT = 3
_PRIORITY_NORMAL = 4
_PRIORITY_LOW = 5

# 高风险域
_HIGH_RISK_DOMAINS = ("身份与访问管理", "数据安全", "网络安全")


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对审计结果进行整体风险分级，并为每个发现项赋优先级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical_t = int(threshold.get("critical_high_count", _DEFAULT_CRITICAL))
    high_t = int(threshold.get("high_count", _DEFAULT_HIGH))
    medium_t = int(threshold.get("medium_count", _DEFAULT_MEDIUM))

    findings_block = result.get("findings", {})
    open_findings = findings_block.get("open", []) if isinstance(findings_block, dict) else []

    high_count = sum(1 for f in open_findings if f.get("severity") == "高")
    medium_count = sum(1 for f in open_findings if f.get("severity") == "中")
    low_count = sum(1 for f in open_findings if f.get("severity") == "低")

    # 整体审计状态分级
    if high_count >= critical_t:
        audit_status = "critical"
    elif high_count >= high_t:
        audit_status = "high"
    elif medium_count >= medium_t:
        audit_status = "medium"
    else:
        audit_status = "low"

    # 为每个发现项赋处置优先级
    for f in open_findings:
        sev = f.get("severity", "低")
        domain = f.get("domain", "")
        is_critical = bool(f.get("critical_finding", False))
        in_high_risk_domain = domain in _HIGH_RISK_DOMAINS
        if is_critical or (sev == "高" and in_high_risk_domain):
            f["priority"] = _PRIORITY_IMMEDIATE
        elif sev == "高":
            f["priority"] = _PRIORITY_URGENT
        elif sev == "中" and in_high_risk_domain:
            f["priority"] = _PRIORITY_IMPORTANT
        elif sev == "中":
            f["priority"] = _PRIORITY_NORMAL
        else:
            f["priority"] = _PRIORITY_LOW

    # 同步结论
    conclusion = result.get("conclusion", {}) if isinstance(result.get("conclusion"), dict) else {}
    conclusion["audit_status"] = audit_status
    conclusion["severity_counts"] = {
        "high": high_count,
        "medium": medium_count,
        "low": low_count,
        "total": len(open_findings),
    }
    conclusion["thresholds"] = {
        "critical_high_count": critical_t,
        "high_count": high_t,
        "medium_count": medium_t,
    }
    result["conclusion"] = conclusion
    return result
