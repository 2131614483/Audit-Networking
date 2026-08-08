"""自定义业务规则：在 engine 之后执行，补充篡改告警与共识处置。

规则：
  1) 哈希链断裂（chain_valid=False）→ 篡改告警 tamper_alert（critical）
  2) 区块高度异常（chain_height 超阈值或创世块后无交易）→ 调查标记
  3) 共识失败（签名验证失败）→ 拒绝 rejected=True
"""
from __future__ import annotations

from typing import Any

_DEFAULT_MAX_HEIGHT = 100000


def _chain_valid_of(result: dict) -> bool:
    """统一读取 chain_valid（verify / store 两种结果结构）。"""
    if "chain_valid" in result:
        return bool(result["chain_valid"])
    return bool(result.get("certificate", {}).get("chain_valid", True))


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：篡改告警 / 高度异常 / 共识拒绝。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    max_height = int(rules_cfg.get("max_block_height", _DEFAULT_MAX_HEIGHT))

    alerts: list[dict] = []
    result["tamper_alert"] = False
    result["rejected"] = False

    chain_valid = _chain_valid_of(result)

    # 规则 1：哈希链断裂 → 篡改告警
    if not chain_valid:
        result["tamper_alert"] = True
        alerts.append({
            "type": "tamper",
            "severity": "critical",
            "message": "区块链哈希链断裂，检测到存证被篡改",
        })

    # 规则 2：区块高度异常 → 调查
    cert = result.get("certificate", {})
    height = cert.get("chain_height", result.get("latest_index", 0))
    if height > max_height:
        alerts.append({
            "type": "height_anomaly",
            "severity": "high",
            "message": f"区块高度 {height} 超过阈值 {max_height}，需调查",
        })
    # 创世块后无任何交易 → 空链告警
    tx_total = result.get("transactions_total", len(cert.get("tx_ids", [])))
    if tx_total == 0 and "verified" not in result:
        alerts.append({
            "type": "empty_chain",
            "severity": "medium",
            "message": "链上无存证交易，请确认发函流程",
        })

    # 规则 3：共识失败（签名无效）→ 拒绝
    if "signature_valid" in result and not result["signature_valid"]:
        result["rejected"] = True
        alerts.append({
            "type": "consensus_failure",
            "severity": "high",
            "message": "银行签名验证失败，共识未达成，拒绝该回函",
        })

    result["alerts"] = alerts
    result["alert_count"] = len(alerts)
    return result
