"""自定义阈值分级：根据相关性评分对法规分级，并标记推送建议。

分级规则（可被 config.threshold 覆盖）：
  * push   : relevance ≥ 0.85  → 高相关，立即推送
  * watch  : 0.5 ≤ relevance < 0.85 → 关注，纳入监控日报
  * ignore : relevance < 0.5   → 忽略，仅归档

config.threshold.confidence 默认 0.85（见 module.yaml），即推送阈值。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_PUSH = 0.85   # ≥ push → 高相关推送
_DEFAULT_WATCH = 0.5   # < watch → 忽略


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据相关性评分对每条法规分级：push / watch / ignore。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    push_threshold = float(threshold.get("confidence", _DEFAULT_PUSH))
    watch_threshold = float(threshold.get("watch", _DEFAULT_WATCH))

    for r in result.get("regulations", []):
        rel = float(r.get("relevance", 0.0))
        if rel >= push_threshold:
            tier = "push"
        elif rel >= watch_threshold:
            tier = "watch"
        else:
            tier = "ignore"
        r["tier"] = tier
        # 高相关（push 级）直接标记推送（业务规则可在 custom_rules 追加强制推送）
        if tier == "push" and not r.get("push"):
            r["push"] = True
            r.setdefault("push_reasons", []).append("high_relevance")
    return result
