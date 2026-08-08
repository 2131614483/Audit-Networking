"""自定义阈值分级：按差异金额与比例对函证差异进行重要性分级。

分级规则（可被 config.threshold 覆盖）：
  * material    : abs_diff >= material_amount 或 abs(diff_pct) >= material_pct  → 重大差异
  * immaterial  : 介于 de_minimis 与 material 之间                              → 非重大差异
  * de_minimis  : abs_diff < de_minimis_amount 且 abs(diff_pct) < de_minimis_pct → 微小差异（可忽略）

默认阈值：
  de_minimis_amount = 1000   de_minimis_pct = 0.005
  material_amount   = 50000  material_pct    = 0.10
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_DE_MINIMIS_AMOUNT = 1000.0
_DEFAULT_DE_MINIMIS_PCT = 0.005
_DEFAULT_MATERIAL_AMOUNT = 50000.0
_DEFAULT_MATERIAL_PCT = 0.10


def apply_thresholds(result: Any, config: Any) -> Any:
    """根据 config 阈值对每个差异项进行重要性分级（material/immaterial/de_minimis）。"""
    if not isinstance(result, dict):
        return result
    cfg = config if isinstance(config, dict) else {}
    threshold = cfg.get("threshold", {}) if isinstance(cfg.get("threshold", {}), dict) else {}
    de_minimis_amount = float(threshold.get("de_minimis_amount", _DEFAULT_DE_MINIMIS_AMOUNT))
    de_minimis_pct = float(threshold.get("de_minimis_pct", _DEFAULT_DE_MINIMIS_PCT))
    material_amount = float(threshold.get("material_amount", _DEFAULT_MATERIAL_AMOUNT))
    material_pct = float(threshold.get("material_pct", _DEFAULT_MATERIAL_PCT))

    items = result.get("items", [])
    grade_counts = {"material": 0, "immaterial": 0, "de_minimis": 0}

    for it in items:
        abs_diff = abs(float(it.get("diff", 0.0) or 0.0))
        abs_pct = abs(float(it.get("diff_pct", 0.0) or 0.0))

        if abs_diff < de_minimis_amount and abs_pct < de_minimis_pct:
            grade = "de_minimis"
        elif abs_diff >= material_amount or abs_pct >= material_pct:
            grade = "material"
        else:
            grade = "immaterial"

        it["materiality_grade"] = grade
        grade_counts[grade] += 1

    # 同步统计
    summary = result.get("summary", {})
    if not isinstance(summary, dict):
        summary = {}
    summary["materiality_distribution"] = dict(grade_counts)
    summary["thresholds"] = {
        "de_minimis_amount": de_minimis_amount,
        "de_minimis_pct": de_minimis_pct,
        "material_amount": material_amount,
        "material_pct": material_pct,
    }
    result["summary"] = summary
    return result
