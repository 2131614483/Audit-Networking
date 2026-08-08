"""自定义业务规则：在 engine 之后执行，可覆盖/补充 SAR 报告结论。

规则：
  1) 交易总额 > 阈值（默认 100 万）→ 强制必报（mandatory_filing=True，
     结论升级为立即提交）
  2) 跨境/高风险法域模式 → 升级优先级（cross_border_escalation=True，
     sar_priority 不低于 high，附件追加外部情报查询记录）
  3) 多关联方 / 多关联账户（>=3）→ 触发网络分析标记
     （network_analysis_required=True，附件追加关联账户网络图）
  4) PEP / 制裁名单命中 → 增强尽调标记（enhanced_due_diligence=True）
"""
from __future__ import annotations

from typing import Any

_LARGE_AMOUNT = 1_000_000.0          # 交易总额阈值：100 万
_RELATED_NETWORK_THRESHOLD = 3        # 关联方/账户数阈值
_CROSS_BORDER_CODES = {               # 跨境/高风险法域可疑模式代码
    "MONEY_LAUNDRY", "HIGH_RISK_JURISDICTION", "TRADE_BASED",
}
_PEP_CODES = {"PEP_RELATED"}
_PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _bump_priority(current: str, target: str) -> str:
    """将优先级提升到 target（不降级）。"""
    if _PRIORITY_RANK.get(target, 0) > _PRIORITY_RANK.get(current, 0):
        return target
    return current


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：大额必报 / 跨境升级 / 网络分析标记 / PEP 增强尽调。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    large_amount = float(rules_cfg.get("large_amount", _LARGE_AMOUNT))
    network_threshold = int(rules_cfg.get("related_network_threshold", _RELATED_NETWORK_THRESHOLD))

    summary = result.get("summary", {}) or {}
    total_amount = float(summary.get("tx_amount_total", 0) or 0)
    related_accounts_count = int(summary.get("related_accounts_count", 0) or 0)
    related_parties_count = int(summary.get("related_parties_count", 0) or 0)

    patterns = result.get("suspicious_patterns", []) or []
    pattern_codes = {p.get("code") for p in patterns if isinstance(p, dict)}

    rule_flags = []
    attachments = list(result.get("attachments_suggested", []) or [])

    # 规则 1：交易总额超阈值 → 强制必报
    mandatory_filing = False
    if total_amount > large_amount:
        mandatory_filing = True
        rule_flags.append({
            "rule": "large_amount_mandatory_filing",
            "detail": f"交易总额 {total_amount:.2f} > {large_amount:.0f}，强制必报",
        })
        conclusion = result.get("conclusion", {}) or {}
        conclusion["verdict"] = "建议提交 SAR"
        conclusion.setdefault("reasons", []).append(
            f"交易总额超 {large_amount:.0f} 触发强制必报"
        )
        result["conclusion"] = conclusion

    # 规则 2：跨境/高风险法域模式 → 升级优先级
    cross_border = bool(pattern_codes & _CROSS_BORDER_CODES)
    if cross_border:
        rule_flags.append({
            "rule": "cross_border_escalation",
            "detail": f"命中跨境/高风险法域模式 {sorted(pattern_codes & _CROSS_BORDER_CODES)}，优先级升级",
        })
        result["sar_priority"] = _bump_priority(
            result.get("sar_priority", "low"), "high"
        )
        if "外部情报查询记录（PEP/制裁名单）" not in attachments:
            attachments.append("外部情报查询记录（PEP/制裁名单）")
        if "跨境资金流向追踪报告" not in attachments:
            attachments.append("跨境资金流向追踪报告")

    # 规则 3：多关联方/账户 → 网络分析标记
    network_required = (
        related_parties_count >= network_threshold
        or related_accounts_count >= network_threshold
    )
    if network_required:
        rule_flags.append({
            "rule": "network_analysis_required",
            "detail": f"关联方 {related_parties_count} / 关联账户 {related_accounts_count} >= {network_threshold}，触发网络分析",
        })
        if "关联账户网络图" not in attachments:
            attachments.append("关联账户网络图")

    # 规则 4：PEP / 制裁名单 → 增强尽调
    pep_hit = bool(pattern_codes & _PEP_CODES)
    external_info = result.get("external_info")  # 可能为空
    sanction_hit = False
    if isinstance(external_info, dict):
        sanction_val = str(external_info.get("sanction_check", ""))
        sanction_hit = "命中" in sanction_val and "未" not in sanction_val
    if pep_hit or sanction_hit:
        rule_flags.append({
            "rule": "enhanced_due_diligence",
            "detail": "命中 PEP / 制裁名单，启动增强尽调",
        })
        if "增强尽调（EDD）记录" not in attachments:
            attachments.append("增强尽调（EDD）记录")

    result["mandatory_filing"] = mandatory_filing
    result["cross_border_escalation"] = cross_border
    result["network_analysis_required"] = network_required
    result["enhanced_due_diligence"] = bool(pep_hit or sanction_hit)
    result["rule_flags"] = rule_flags
    result["attachments_suggested"] = attachments
    return result
