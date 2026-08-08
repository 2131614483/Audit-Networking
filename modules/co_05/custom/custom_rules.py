"""自定义业务规则：在 engine 之后执行，标记洗钱网络关键特征。

规则：
  1) 资金循环（PAT-MONEY-LOOP）检测 → 标记 layering_pattern=True（分层洗钱）
  2) 分散汇入（PAT-SMURFING）且源账户 >= 5 → 标记 organized_smurfing=True（有组织分散）
  3) 空壳公司网络（PAT-SHELL-COMPANY）且关联节点 >= 4 → 标记 suspected_syndicate=True（犯罪团伙嫌疑）
"""
from __future__ import annotations

from typing import Any

_ORGANIZED_SMURFING_THRESHOLD = 5
_SYNDICATE_NODE_THRESHOLD = 4


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：分层标记 / 有组织分散 / 团伙嫌疑。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    smurf_threshold = int(
        rules_cfg.get("organized_smurfing_sources", _ORGANIZED_SMURFING_THRESHOLD)
    )
    syndicate_threshold = int(
        rules_cfg.get("syndicate_nodes", _SYNDICATE_NODE_THRESHOLD)
    )

    detections = result.get("patterns_detected", [])
    if not detections:
        return result

    layering_count = 0
    organized_count = 0
    syndicate_count = 0

    for d in detections:
        adjustments = d.setdefault("rule_adjustments", [])
        pattern_id = d.get("pattern_id", "")

        # 规则 1：资金循环 → 分层洗钱标记
        if pattern_id == "PAT-MONEY-LOOP":
            d["layering_pattern"] = True
            layering_count += 1
            adjustments.append("资金循环→分层洗钱标记")
        else:
            d.setdefault("layering_pattern", False)

        # 规则 2：有组织分散汇入（源账户 >= 5）
        if pattern_id == "PAT-SMURFING":
            source_count = int(d.get("source_count", 0))
            if source_count >= smurf_threshold:
                d["organized_smurfing"] = True
                organized_count += 1
                adjustments.append(
                    f"分散汇入源账户{source_count}>={smurf_threshold}→有组织分散"
                )
            else:
                d.setdefault("organized_smurfing", False)
        else:
            d.setdefault("organized_smurfing", False)

        # 规则 3：空壳公司团伙嫌疑（关联节点 >= 4）
        if pattern_id == "PAT-SHELL-COMPANY":
            node_count = int(d.get("node_count", 0))
            if node_count >= syndicate_threshold:
                d["suspected_syndicate"] = True
                syndicate_count += 1
                adjustments.append(
                    f"空壳网络节点{node_count}>={syndicate_threshold}→犯罪团伙嫌疑"
                )
            else:
                d.setdefault("suspected_syndicate", False)
        else:
            d.setdefault("suspected_syndicate", False)

    result["rule_adjustments"] = {
        "layering_pattern": layering_count,
        "organized_smurfing": organized_count,
        "suspected_syndicate": syndicate_count,
    }
    return result
