"""自定义阈值分级：按加速比例对审计任务分级（达标 / 部分 / 待优化）。

分级规则（可被 config.threshold 覆盖）：
  * passed           : acceleration_ratio ≥ 0.85  → 达标（RPA+ML 高度自动化）
  * partial          : 0.5 ≤ acceleration_ratio < 0.85 → 部分加速（需人工复核）
  * needs_optimization: acceleration_ratio < 0.5  → 待优化（瓶颈任务，待技术提升）

同时标记核查发现的严重程度阈值（severity ≥ high 强制人工复核）。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值（与 module.yaml threshold.confidence=0.85 对齐）
_DEFAULT_PASSED = 0.85   # ≥ 0.85 达标
_DEFAULT_PARTIAL = 0.5   # < 0.5 待优化；中间为部分


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据加速比例对每个审计任务分级：passed / partial / needs_optimization。

    同时对核查发现打 review 标记：severity=high → need_manual_review=True。
    """
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    passed_thr = float(threshold.get("confidence", _DEFAULT_PASSED))
    partial_thr = float(threshold.get("bottleneck", _DEFAULT_PARTIAL))

    # 1. 任务加速分级
    for t in result.get("tasks", []):
        ratio = float(t.get("acceleration_ratio", 0.0))
        if ratio >= passed_thr:
            t["acceleration_tier"] = "passed"
        elif ratio >= partial_thr:
            t["acceleration_tier"] = "partial"
        else:
            t["acceleration_tier"] = "needs_optimization"

    # 2. 核查发现：high 严重程度强制人工复核
    for f in result.get("findings", []):
        if f.get("severity") == "high":
            f["need_manual_review"] = True
        # severity 缺省补 low
        if not f.get("severity"):
            f["severity"] = "low"

    return result
