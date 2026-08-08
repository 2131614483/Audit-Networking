"""自定义阈值分级：基于环境影响评分对 ROI 进行分级（normal/warning/critical）。

环境影响评分（impact_score）综合考量：
  * 高/中 severity 的指数变化（毁林、火灾、水质下降等）
  * 高/中 severity 的异常事件（趋势异常、极端事件、水体波动）
  * 绿色漂洗矛盾信号（contradiction / weak_support）

分级规则（可被 config.threshold 覆盖）：
  * critical : impact_score >= warning  → 严重环境影响
  * warning  : normal <= impact_score < warning → 需关注
  * normal   : impact_score < normal    → 正常
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_NORMAL = 0.3
_DEFAULT_WARNING = 0.6


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据环境影响评分对每个 ROI 分级，并写入 impact_score / impact_level。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    normal = float(threshold.get("normal", _DEFAULT_NORMAL))
    warning = float(threshold.get("warning", _DEFAULT_WARNING))

    roi_reports = result.get("roi_reports", [])
    dist = {"normal": 0, "warning": 0, "critical": 0}
    for roi in roi_reports:
        score = _compute_impact_score(roi)
        if score >= warning:
            level = "critical"
        elif score >= normal:
            level = "warning"
        else:
            level = "normal"
        roi["impact_score"] = round(score, 3)
        roi["impact_level"] = level
        dist[level] += 1

    summary = result.get("summary", {})
    summary["impact_distribution"] = dist
    summary["thresholds"] = {"normal": normal, "warning": warning}
    result["summary"] = summary
    return result


def _compute_impact_score(roi: dict) -> float:
    """根据变化/异常/绿色漂洗信号计算环境影响评分 ∈ [0, 1]。"""
    changes = roi.get("changes", [])
    anomalies = roi.get("anomalies", [])
    gw = roi.get("greenwashing_check", {}) or {}

    high_changes = sum(1 for c in changes if c.get("severity") == "高")
    mid_changes = sum(1 for c in changes if c.get("severity") == "中")
    high_anom = sum(1 for a in anomalies if a.get("severity") == "高")
    mid_anom = sum(1 for a in anomalies if a.get("severity") == "中")

    score = 0.0
    score += min(0.40, high_changes * 0.15)
    score += min(0.20, mid_changes * 0.05)
    score += min(0.25, high_anom * 0.15)
    score += min(0.10, mid_anom * 0.05)

    signal = gw.get("signal", "")
    if signal == "contradiction":
        score += 0.25
    elif signal == "weak_support":
        score += 0.10

    return min(1.0, score)
