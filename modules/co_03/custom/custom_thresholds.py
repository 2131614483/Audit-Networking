"""自定义阈值：更新优先级分级（critical/high/medium/low）。

基于法规影响相似度 impact_similarity 分级（可被 config.threshold 覆盖）：
  * critical : sim >= 0.50  → 立即更新（阻断性法规变更）
  * high     : 0.30 <= sim < 0.50 → 优先更新
  * medium   : 0.15 <= sim < 0.30 → 下次审计前更新
  * low      : sim < 0.15  → 年度更新

engine._analyze_change 已内置 impact_level（high/medium/low），本模块允许通过
config 不改代码调参，并补充 update_priority（含 critical 档）。
对 update_programs 结果，按 change_count 赋优先级。
"""
from __future__ import annotations

from typing import Any

# 出厂默认相似度阈值
_DEFAULT_CRITICAL = 0.50
_DEFAULT_HIGH = 0.30
_DEFAULT_MEDIUM = 0.15


def _grade_by_similarity(sim: float, critical: float, high: float,
                         medium: float) -> str:
    if sim >= critical:
        return "critical"
    if sim >= high:
        return "high"
    if sim >= medium:
        return "medium"
    return "low"


def _grade_by_change_count(change_count: int) -> str:
    if change_count >= 5:
        return "critical"
    if change_count >= 3:
        return "high"
    if change_count >= 1:
        return "medium"
    return "low"


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值为受影响/已更新程序赋 update_priority。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    critical = float(threshold.get("sim_critical", _DEFAULT_CRITICAL))
    high = float(threshold.get("sim_high", _DEFAULT_HIGH))
    medium = float(threshold.get("sim_medium", _DEFAULT_MEDIUM))

    thresholds_meta = {
        "sim_critical": critical, "sim_high": high, "sim_medium": medium,
    }

    # analyze_change 结果：affected_programs 含 impact_similarity
    affected = result.get("affected_programs", [])
    if isinstance(affected, list) and affected:
        priority_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for p in affected:
            if not isinstance(p, dict):
                continue
            sim = float(p.get("impact_similarity", 0.0) or 0.0)
            priority = _grade_by_similarity(sim, critical, high, medium)
            p["update_priority"] = priority
            # 同步 impact_level（保持与优先级档位一致，但保留原 high/medium/low 语义）
            if priority == "critical":
                p["impact_level"] = "high"
            elif priority == "low":
                p["impact_level"] = "low"
            else:
                p["impact_level"] = priority
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        result["priority_distribution"] = priority_counts
        result["thresholds"] = thresholds_meta

    # update_programs 结果：updated_programs 含 change_count
    updated = result.get("updated_programs", [])
    if isinstance(updated, list) and updated:
        for p in updated:
            if not isinstance(p, dict):
                continue
            cc = int(p.get("change_count", 0) or 0)
            p["update_priority"] = _grade_by_change_count(cc)
        result["thresholds"] = thresholds_meta

    return result
