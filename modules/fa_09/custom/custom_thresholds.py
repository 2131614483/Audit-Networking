"""自定义阈值分级：根据 config 阈值对质量评分进行等级划分与通过/不通过判定。

分级规则（可被 config.threshold 覆盖）：
  * grade_a (默认 90): overall_score ≥ 此值 → A 级
  * grade_b (默认 80): ≥ 此值 → B 级
  * grade_c (默认 70): ≥ 此值 → C 级
  * grade_d (默认 60): ≥ 此值 → D 级
  * pass_threshold (默认 60): ≥ 此值 → passed=True
"""
from __future__ import annotations

from collections import Counter
from typing import Any

_DEFAULT_GRADE_A = 90.0
_DEFAULT_GRADE_B = 80.0
_DEFAULT_GRADE_C = 70.0
_DEFAULT_GRADE_D = 60.0
_DEFAULT_PASS = 60.0


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值重新计算等级与通过判定。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    g_a = float(threshold.get("grade_a", _DEFAULT_GRADE_A))
    g_b = float(threshold.get("grade_b", _DEFAULT_GRADE_B))
    g_c = float(threshold.get("grade_c", _DEFAULT_GRADE_C))
    g_d = float(threshold.get("grade_d", _DEFAULT_GRADE_D))
    pass_thresh = float(threshold.get("pass_threshold", _DEFAULT_PASS))

    items = result.get("items", [])
    for item in items:
        score = float(item.get("overall_score", 0))
        # 重新计算等级
        if score >= g_a:
            item["grade"] = "A"
        elif score >= g_b:
            item["grade"] = "B"
        elif score >= g_c:
            item["grade"] = "C"
        elif score >= g_d:
            item["grade"] = "D"
        else:
            item["grade"] = "F"
        # 通过判定
        item["passed"] = score >= pass_thresh

    # 重算 grade_distribution
    grade_dist = dict(Counter(i.get("grade") for i in items))
    summary = result.get("summary", {})
    summary["grade_distribution"] = grade_dist
    summary["pass_count"] = sum(1 for i in items if i.get("passed"))
    summary["fail_count"] = sum(1 for i in items if not i.get("passed"))
    summary["pass_rate"] = round(
        summary["pass_count"] / max(1, len(items)), 3
    )
    summary["thresholds"] = {
        "grade_a": g_a, "grade_b": g_b, "grade_c": g_c,
        "grade_d": g_d, "pass_threshold": pass_thresh,
    }
    result["summary"] = summary
    return result
