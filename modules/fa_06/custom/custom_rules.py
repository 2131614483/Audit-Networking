"""自定义业务规则：在 engine 之后执行，可覆盖/补充差异分析结果。

规则：
  1) 差异占账面余额 > 10% → 标记 is_material（重大差异标记，与分级互补）
  2) 同一科目出现 ≥2 个差异项 → 标记 systemic_issue（疑似系统性问题）
  3) 时间性差异且严重等级 high/critical，或差异金额 >= aged_amount → 标记 aged_item
     （长期未清理的时间性差异，默认 aged_amount=20000）
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

_MATERIAL_RATIO = 0.10  # 差异占账面余额 10%
_DEFAULT_AGED_AMOUNT = 20000.0


def apply_custom_rules(result: Any, config: Any) -> Any:
    """应用业务规则：重大差异标记 / 系统性问题 / 长期时间性差异。"""
    if not isinstance(result, dict):
        return result
    cfg = config if isinstance(config, dict) else {}
    rules_cfg = cfg.get("rules", {}) if isinstance(cfg.get("rules", {}), dict) else {}
    material_ratio = float(rules_cfg.get("material_ratio", _MATERIAL_RATIO))
    aged_amount = float(rules_cfg.get("aged_amount", _DEFAULT_AGED_AMOUNT))

    items = result.get("items", [])

    # 规则 2 预计算：按科目统计有差异的项数
    subject_diff_counts: dict[str, int] = defaultdict(int)
    for it in items:
        if abs(float(it.get("diff", 0.0) or 0.0)) > 0.005:
            subject_diff_counts[str(it.get("subject", ""))] += 1

    material_flagged = 0
    systemic_flagged = 0
    aged_flagged = 0

    for it in items:
        adjustments = it.setdefault("rule_adjustments", [])
        abs_diff = abs(float(it.get("diff", 0.0) or 0.0))
        abs_pct = abs(float(it.get("diff_pct", 0.0) or 0.0))
        book_amount = abs(float(it.get("book_amount", 0.0) or 0.0))
        subject = str(it.get("subject", ""))
        category = str(it.get("category", ""))
        severity = str(it.get("severity", ""))

        # 规则 1：差异占账面余额 > material_ratio → is_material
        if book_amount > 0 and abs_pct > material_ratio:
            it["is_material"] = True
            material_flagged += 1
            adjustments.append(f"差异占账面{abs_pct:.1%}>{material_ratio:.0%}标记重大")
        else:
            it["is_material"] = False

        # 规则 2：同科目 ≥2 个差异 → systemic_issue
        if subject_diff_counts.get(subject, 0) >= 2:
            it["systemic_issue"] = True
            systemic_flagged += 1
            adjustments.append(f"同科目[{subject}]多发差异疑似系统性问题")
        else:
            it["systemic_issue"] = False

        # 规则 3：时间性差异 + (high/critical 或 大额) → aged_item
        is_aged = (
            category == "时间性差异"
            and (severity in ("high", "critical") or abs_diff >= aged_amount)
        )
        if is_aged:
            it["aged_item"] = True
            aged_flagged += 1
            adjustments.append("时间性差异长期未清理标记aged")
        else:
            it["aged_item"] = False

    # 同步统计
    summary = result.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    summary["rule_flags"] = {
        "material_flagged": material_flagged,
        "systemic_flagged": systemic_flagged,
        "aged_flagged": aged_flagged,
    }
    result["summary"] = summary
    return result
