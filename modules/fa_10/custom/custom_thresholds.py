"""自定义阈值分级：根据关联强度对关联方分级。

分级规则（可被 config.threshold 覆盖）：
  * strong  : strength ≥ 0.8    → 强关联（重点核查）
  * medium  : 0.5 ≤ strength < 0.8 → 中关联（建议关注）
  * weak    : strength < 0.5    → 弱关联（备查）

config.threshold.confidence = 0.85 为强关联门槛基准。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_STRONG = 0.8    # ≥ strong → 强关联
_DEFAULT_MEDIUM = 0.5    # ≥ medium 且 < strong → 中关联；< medium → 弱关联


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据关联强度对每个关联方分级：strong / medium / weak。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    strong_th = float(threshold.get("confidence", _DEFAULT_STRONG))
    # confidence 作为强关联门槛，中关联门槛取其 0.625 倍（≈0.5 当 confidence=0.8）
    medium_th = float(threshold.get("medium", _DEFAULT_MEDIUM))

    for net in result.get("networks", []):
        for rp in net.get("related_parties", []):
            strength = float(rp.get("strength", 0.0))
            if strength >= strong_th:
                rp["tier"] = "strong"
            elif strength >= medium_th:
                rp["tier"] = "medium"
            else:
                rp["tier"] = "weak"
        # 更新统计中的 strong_count（以阈值门槛为准，而非 0.8 硬编码）
        strong_count = sum(
            1 for rp in net.get("related_parties", [])
            if rp.get("tier") == "strong"
        )
        net["statistics"]["strong_count"] = strong_count
    return result
