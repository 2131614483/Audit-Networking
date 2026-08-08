"""自定义阈值 —— 数据湖质量评分分级。

从 config 读取阈值（threshold.confidence），不改代码即可调参：
  - overall_score >= 0.9      优质 (excellent)
  - 0.7 <= overall_score < 0.9 合格 (qualified)，需满足 confidence 门槛
  - overall_score < 0.7       不合格 (unqualified)，需重新清洗
"""
from __future__ import annotations

from typing import Any


def _grade(score: float) -> str:
    if score >= 0.9:
        return "excellent"  # 优质
    if score >= 0.7:
        return "qualified"  # 合格
    return "unqualified"  # 不合格，需重清洗


def _grade_label(grade: str) -> str:
    return {"excellent": "优质", "qualified": "合格", "unqualified": "不合格"}.get(
        grade, grade
    )


def apply_thresholds(result: Any, config: dict) -> Any:
    """对三分区质量评分应用阈值分级，写回 quality_grades / threshold。"""
    if not isinstance(result, dict):
        return result
    threshold_cfg = (config or {}).get("threshold", {}) or {}
    confidence = float(threshold_cfg.get("confidence", 0.85))

    quality = result.get("quality", {}) or {}
    grades: dict[str, dict[str, Any]] = {}
    for zone, metrics in quality.items():
        score = float(metrics.get("overall_score", 0.0))
        grade = _grade(score)
        grades[zone] = {
            "grade": grade,
            "grade_label": _grade_label(grade),
            "overall_score": score,
            "meets_threshold": score >= confidence,
        }
    result["quality_grades"] = grades
    result["threshold"] = {"confidence": confidence}
    return result
