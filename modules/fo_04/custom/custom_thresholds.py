"""自定义阈值分级：根据取证完整性评分进行分级。

分级规则（可被 config.threshold 覆盖）：
  * verified : integrity_score >= 0.8  → 完整性验证通过
  * partial  : 0.5 <= score < 0.8      → 部分完整
  * tampered : score < 0.5             → 疑似篡改

完整性评分维度：
  - 链完整性（chain_complete）
  - 重复物证数量
  - 缺失元数据（author/source/timestamp）
"""
from __future__ import annotations

from typing import Any

_DEFAULT_VERIFIED = 0.8
_DEFAULT_PARTIAL = 0.5


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据完整性评分对取证结果进行分级。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    verified = float(threshold.get("verified", _DEFAULT_VERIFIED))
    partial = float(threshold.get("partial", _DEFAULT_PARTIAL))

    items = result.get("items", [])
    summary = result.get("summary", {})

    # 计算完整性评分
    score = 1.0
    deductions = []

    # 链完整性
    if not summary.get("chain_complete", True):
        score -= 0.3
        deductions.append("chain_incomplete")

    # 重复物证
    dup_count = summary.get("duplicate_groups", 0)
    if dup_count > 0:
        score -= min(0.1 * dup_count, 0.3)
        deductions.append(f"duplicates:{dup_count}")

    # 缺失元数据
    missing_meta = 0
    for item in items:
        if not item.get("author"):
            missing_meta += 1
        if not item.get("source"):
            missing_meta += 1
        if not item.get("timestamp"):
            missing_meta += 1
    if missing_meta > 0:
        score -= min(0.05 * missing_meta, 0.3)
        deductions.append(f"missing_metadata:{missing_meta}")

    score = max(0.0, min(1.0, round(score, 4)))

    if score >= verified:
        level = "verified"
    elif score >= partial:
        level = "partial"
    else:
        level = "tampered"

    summary["integrity_score"] = score
    summary["integrity_level"] = level
    summary["integrity_deductions"] = deductions
    result["summary"] = summary

    # 给每个物证标记完整性级别
    for item in items:
        item["integrity_level"] = level

    return result
