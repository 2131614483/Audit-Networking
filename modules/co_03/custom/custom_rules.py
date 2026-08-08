"""自定义业务规则：在 engine 之后执行，可覆盖/补充更新结果。

规则：
  1) AML 法规变更 → 受影响 aml 程序标记 mandatory_update=True（强制立即更新）
  2) 低影响程序 → 标记 archive_candidate + archive_reason（步骤可能已过时，建议归档）
  3) 自动更新覆盖率 < 阈值 → 标记 coverage_alert（需人工补充更新）
"""
from __future__ import annotations

from typing import Any

_DEFAULT_COVERAGE_THRESHOLD = 0.80


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：AML 强制更新 / 低影响归档候选 / 覆盖率告警。"""
    if not isinstance(result, dict):
        return result

    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    coverage_threshold = float(
        rules_cfg.get("coverage_threshold", _DEFAULT_COVERAGE_THRESHOLD)
    )
    rule_flags: list[str] = []

    affected_domains = result.get("affected_domains", []) or []
    affected_programs = result.get("affected_programs", []) or []

    # 规则 1：AML 法规变更 → 强制更新 aml 域程序
    if "aml" in affected_domains:
        mandatory_count = 0
        for p in affected_programs:
            if not isinstance(p, dict) or p.get("domain") != "aml":
                continue
            p["mandatory_update"] = True
            mandatory_count += 1
        if mandatory_count:
            rule_flags.append(
                f"AML法规变更→{mandatory_count}个反洗钱程序强制更新"
            )

    # 规则 2：低影响程序 → 归档候选（步骤可能已过时）
    archive_count = 0
    for p in affected_programs:
        if not isinstance(p, dict):
            continue
        if p.get("impact_level") == "low":
            p["archive_candidate"] = True
            p["archive_reason"] = "法规变更影响度低，建议评估是否归档过时步骤"
            archive_count += 1
    if archive_count:
        rule_flags.append(
            f"{archive_count}个低影响程序标记为归档候选"
        )

    # 规则 3：自动更新覆盖率 < 阈值 → 告警
    if affected_programs:
        total = len(affected_programs)
        updatable = sum(
            1 for p in affected_programs
            if isinstance(p, dict)
            and p.get("impact_level") in ("high", "medium")
        )
        coverage = updatable / max(total, 1)
        result["coverage_rate"] = round(coverage, 4)
        if coverage < coverage_threshold:
            result["coverage_alert"] = True
            rule_flags.append(
                f"自动更新覆盖率{coverage * 100:.0f}%<{coverage_threshold * 100:.0f}%→告警"
            )
        else:
            result["coverage_alert"] = False

    # update_programs 结果：未触发任何更新 → 覆盖率告警
    updated = result.get("updated_programs")
    if isinstance(updated, list) and not affected_programs:
        programs_updated = int(result.get("programs_updated", 0) or 0)
        if programs_updated == 0:
            result["coverage_rate"] = 0.0
            result["coverage_alert"] = True
            rule_flags.append("法规变更未触发任何程序更新→覆盖率告警")
        else:
            result.setdefault("coverage_rate", 1.0)
            result.setdefault("coverage_alert", False)

    if rule_flags:
        result["custom_rule_flags"] = rule_flags
    else:
        result.setdefault("custom_rule_flags", [])
    return result
