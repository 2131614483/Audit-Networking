"""自定义阈值分级：完整性评分 + 信任等级 + 验证级别。

分级规则（可被 config.threshold 覆盖）：
  * 完整性评分 integrity_score：
      - verify 结果：0.4*found_on_chain + 0.3*signature_valid + 0.3*chain_valid
      - store 结果：1.0（链有效） / 0.0（链被篡改）
  * 信任等级 trust_level：
      - score >= high_trust(0.95)  → high
      - score >= medium_trust(0.7) → medium
      - 其余                          → low
  * 验证级别 verification_level：
      - verified / unverified / tampered
"""
from __future__ import annotations

from typing import Any

_DEFAULT_HIGH_TRUST = 0.95
_DEFAULT_MEDIUM_TRUST = 0.7


def _trust_level(score: float, high: float, medium: float) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    return "low"


def _verification_level(result: dict) -> str:
    """根据验证结果判定验证级别。"""
    if "verified" in result:
        # verify 模式结果
        if result.get("verified"):
            return "verified"
        if not result.get("chain_valid", True):
            return "tampered"
        return "unverified"
    # store 模式结果
    chain_valid = result.get("certificate", {}).get(
        "chain_valid", result.get("chain_valid", True)
    )
    return "verified" if chain_valid else "tampered"


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值计算完整性评分 / 信任等级 / 验证级别。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    high_trust = float(threshold.get("high_trust_score", _DEFAULT_HIGH_TRUST))
    medium_trust = float(threshold.get("medium_trust_score", _DEFAULT_MEDIUM_TRUST))

    if "verified" in result:
        # verify 模式：组合三项指标
        score = 0.0
        if result.get("found_on_chain"):
            score += 0.4
        if result.get("signature_valid"):
            score += 0.3
        if result.get("chain_valid"):
            score += 0.3
    else:
        # store 模式：以链有效性为准
        chain_valid = result.get("certificate", {}).get(
            "chain_valid", result.get("chain_valid", False)
        )
        score = 1.0 if chain_valid else 0.0

    score = round(score, 4)
    result["integrity_score"] = score
    result["trust_level"] = _trust_level(score, high_trust, medium_trust)
    result["verification_level"] = _verification_level(result)

    result["grading"] = {
        "integrity_score": score,
        "trust_level": result["trust_level"],
        "verification_level": result["verification_level"],
        "thresholds": {
            "high_trust_score": high_trust,
            "medium_trust_score": medium_trust,
        },
    }
    return result
