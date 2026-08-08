"""自定义阈值分级：翻译质量评分分级。

分级规则（可被 config.threshold 覆盖）：
  * high   : confidence >= 0.8  → 高置信度翻译
  * medium : 0.6 <= confidence < 0.8 → 中置信度
  * low    : confidence < 0.6  → 低置信度

置信度评估维度：
  - 源语言与目标语言是否相同（相同=1.0）
  - 代码切换检测（混用降低置信度）
  - 检测语言与声明源语言一致性
  - 法律术语命中情况
"""
from __future__ import annotations

from typing import Any

_DEFAULT_HIGH = 0.8
_DEFAULT_MEDIUM = 0.6


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据翻译置信度对每条翻译进行质量分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))

    translations = result.get("translations", [])
    high_count = medium_count = low_count = 0

    for t in translations:
        confidence = _compute_confidence(t)
        t["translation_confidence"] = confidence
        if confidence >= high:
            t["quality_level"] = "high"
            high_count += 1
        elif confidence >= medium:
            t["quality_level"] = "medium"
            medium_count += 1
        else:
            t["quality_level"] = "low"
            low_count += 1

    avg_confidence = sum(
        t["translation_confidence"] for t in translations
    ) / max(len(translations), 1)
    avg_confidence = round(avg_confidence, 4)

    if avg_confidence >= high:
        overall_level = "high"
    elif avg_confidence >= medium:
        overall_level = "medium"
    else:
        overall_level = "low"

    summary = result.get("summary", {})
    summary["avg_confidence"] = avg_confidence
    summary["quality_level"] = overall_level
    summary["quality_distribution"] = {
        "high": high_count,
        "medium": medium_count,
        "low": low_count,
    }
    result["summary"] = summary
    return result


def _compute_confidence(t: dict) -> float:
    """计算单条翻译的置信度。"""
    src = t.get("source_language", "")
    tgt = t.get("target_language", "")
    detected = t.get("detected_language", "")

    if src == tgt and src:
        return 1.0

    base = 0.9

    if t.get("code_switch_detected"):
        base -= 0.2

    if src and detected and src != detected:
        base -= 0.15

    legal_terms = t.get("legal_terms_found", [])
    if not legal_terms:
        base -= 0.05

    if detected == "unknown":
        base = 0.3

    return round(max(0.0, min(1.0, base)), 4)
