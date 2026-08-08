"""自定义完成度阈值分级：从 config 读取阈值，对每份底稿按完成度分级。

分级规则（可被 config.threshold 覆盖）：
  * complete   : completeness ≥ 0.85          → 底稿完整，可直接使用
  * supplement : 0.6 ≤ completeness < 0.85     → 需补充数据后完善
  * incomplete : completeness < 0.6            → 不完整，需人工重编

出厂默认：threshold.confidence = 0.85（与 module.yaml 一致）。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_COMPLETE = 0.85   # ≥ complete → 完整
_DEFAULT_SUPPLEMENT = 0.6  # < supplement_low → 不完整


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据完成度对每份底稿分级：complete / supplement / incomplete。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    complete_thr = float(threshold.get("confidence", _DEFAULT_COMPLETE))
    supplement_thr = float(threshold.get("supplement", _DEFAULT_SUPPLEMENT))

    for wp in result.get("workpapers", []):
        comp = float(wp.get("completeness", 0.0))
        if comp >= complete_thr:
            tier = "complete"
        elif comp >= supplement_thr:
            tier = "supplement"
        else:
            tier = "incomplete"
        wp["tier"] = tier
    return result
