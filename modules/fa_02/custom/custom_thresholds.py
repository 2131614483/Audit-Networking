"""自定义阈值分级：从 config 读取阈值，对标准化结果按置信度分级。

分级规则（可被 config.threshold 覆盖）：
  * auto   : confidence ≥ 0.85  → 自动通过
  * review : 0.6 ≤ confidence < 0.85 → 建议人工复核
  * manual : confidence < 0.6 或 unmapped → 强制人工
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_HIGH = 0.85   # ≥ high → auto
_DEFAULT_LOW = 0.6     # < low → manual


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据置信度对每个字段分级：auto / review / manual。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high = float(threshold.get("confidence", _DEFAULT_HIGH))
    low = float(threshold.get("manual", _DEFAULT_LOW))

    for f in result.get("fields", []):
        conf = float(f.get("confidence", 0.0))
        # 未映射字段强制人工
        if f.get("unmapped") or conf < low:
            tier = "manual"
        elif conf >= high:
            tier = "auto"
        else:
            tier = "review"
        f["tier"] = tier
    return result
