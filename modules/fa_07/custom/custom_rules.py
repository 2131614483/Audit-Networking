"""自定义业务规则：在 engine 之后执行，补充审计复核标记。

规则：
  1) 缺失数据（placeholders_missing 非空）→ 标 has_missing_data，复核原因 missing_data
  2) 交叉引用断裂（broken 引用）→ 标 has_broken_ref，复核原因 broken_cross_ref
  3) 结论需人工复核（conclusion_severity=warning 或 tier≠complete）→ 标 needs_review
  4) 汇总每份底稿的 review_reasons 清单
"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    """对每份底稿补充审计复核标记与原因清单。"""
    if not isinstance(result, dict):
        return result

    for wp in result.get("workpapers", []):
        review_reasons: list[str] = []

        # 规则 1：缺失数据标记
        missing = wp.get("placeholders_missing", []) or []
        if missing:
            wp["has_missing_data"] = True
            review_reasons.append("missing_data")
        else:
            wp["has_missing_data"] = False

        # 规则 2：交叉引用断裂标记
        broken = [r for r in wp.get("cross_references", [])
                  if isinstance(r, dict) and r.get("status") == "broken"]
        if broken:
            wp["has_broken_ref"] = True
            review_reasons.append("broken_cross_ref")
        else:
            wp["has_broken_ref"] = False

        # 规则 3：结论需人工复核（warning 级或底稿未达 complete）
        sev = wp.get("conclusion_severity", "info")
        tier = wp.get("tier", "complete")
        if sev == "warning" or tier != "complete":
            review_reasons.append("conclusion_review")

        # 汇总 needs_review：engine 基础标记 || 任一复核原因命中
        wp["review_reasons"] = review_reasons
        wp["needs_review"] = bool(wp.get("needs_review") or review_reasons)

    return result
