"""自定义阈值分级：根据 config 阈值对舞弊评分进行风险分级。

分级规则（可被 config.threshold 覆盖）：
  * high   : risk_score ≥ 0.8  → 高风险
  * medium : 0.5 ≤ risk_score < 0.8 → 中风险
  * low    : risk_score < 0.5  → 低风险
  * confidence (默认 0.85)：高置信度可疑门槛，超过此值标记 confirmed_suspicious
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_HIGH = 0.8
_DEFAULT_MEDIUM = 0.5
_DEFAULT_CONFIDENCE = 0.85


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值重新分级可疑交易，并标记 confirmed_suspicious。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    confidence = float(threshold.get("confidence", _DEFAULT_CONFIDENCE))

    suspicious = result.get("suspicious_transactions", [])
    high_count = medium_count = low_count = 0
    confirmed_count = 0
    for s in suspicious:
        score = float(s.get("risk_score", 0.0))
        if score >= high:
            s["risk_level"] = "high"
            high_count += 1
        elif score >= medium:
            s["risk_level"] = "medium"
            medium_count += 1
        else:
            s["risk_level"] = "low"
            low_count += 1
        # 高置信度可疑标记（用于优先复核排序）
        s["confirmed_suspicious"] = score >= confidence
        if s["confirmed_suspicious"]:
            confirmed_count += 1

    # 同步统计
    stats = result.get("statistics", {})
    stats["risk_distribution"] = {
        "high": high_count, "medium": medium_count, "low": low_count,
    }
    stats["confirmed_suspicious_count"] = confirmed_count
    stats["thresholds"] = {
        "high": high, "medium": medium, "confidence": confidence,
    }
    result["statistics"] = stats
    return result
