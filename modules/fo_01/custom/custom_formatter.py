"""统一输出格式化：可疑交易明细表 + 扫描统计。

输出结构：
  {
    "status": "ok",
    "module": "FO-01",
    "suspicious_transactions": [ {tx_id, amount, risk_score, risk_level,
                                  hit_layers, evidence_chain, ...}, ... ],
    "layer_summary": { statistical / unsupervised / supervised / graph },
    "statistics": { total_transactions, suspicious_count, coverage_rate,
                    layer_hit_counts, risk_distribution, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    suspicious = result.get("suspicious_transactions", [])
    stats = result.get("statistics", {})
    layer_results = result.get("layer_results", {})

    # 可疑交易明细表
    details = []
    for s in suspicious:
        details.append({
            "tx_id": s.get("tx_id"),
            "amount": s.get("amount"),
            "tx_date": s.get("tx_date"),
            "hour": s.get("hour"),
            "counterparty": s.get("counterparty"),
            "tx_type": s.get("tx_type"),
            "is_related_party": s.get("is_related_party", False),
            "risk_score": s.get("risk_score"),
            "risk_level": s.get("risk_level"),
            "hit_layers": s.get("hit_layers", []),
            "matched_patterns": s.get("matched_patterns", []),
            "evidence_chain": s.get("evidence_chain", []),
            "need_review": s.get("need_review", False),
            "confirmed_suspicious": s.get("confirmed_suspicious", False),
            "off_hours": s.get("off_hours", False),
            "rule_adjustments": s.get("rule_adjustments", []),
        })

    # 各层命中数
    layer_hits = stats.get("layer_hit_counts", {})

    # 扫描统计
    total = stats.get("total_transactions", 0)
    suspicious_count = stats.get("suspicious_count", 0)
    output_stats = {
        "total_transactions": total,
        "suspicious_count": suspicious_count,
        "confirmed_suspicious_count": stats.get(
            "confirmed_suspicious_count", 0
        ),
        "coverage_rate": stats.get("coverage_rate", 1.0),
        "suspicious_rate": round(
            suspicious_count / max(total, 1), 4
        ),
        "layer_hit_counts": layer_hits,
        "risk_distribution": stats.get(
            "risk_distribution", {"high": 0, "medium": 0, "low": 0}
        ),
        "rule_adjustments": stats.get("rule_adjustments", {}),
        "thresholds": stats.get("thresholds", {}),
    }

    # 各层摘要
    layer_summary: dict[str, Any] = {}
    if "statistical" in layer_results:
        lr = layer_results["statistical"]
        layer_summary["statistical"] = {
            "benford_chi_square": lr.get("benford", {}).get("chi_square"),
            "benford_is_anomaly": lr.get("benford", {}).get("is_anomaly"),
            "z_score_flagged": len(
                lr.get("z_score", {}).get("flagged_tx_ids", [])
            ),
            "iqr_flagged": len(
                lr.get("iqr", {}).get("flagged_tx_ids", [])
            ),
        }
    if "unsupervised" in layer_results:
        lr = layer_results["unsupervised"]
        layer_summary["unsupervised"] = {
            "iso_forest_flagged": len(
                lr.get("iso_forest", {}).get("flagged_tx_ids", [])
            ),
            "reconstruction_flagged": len(
                lr.get("reconstruction_error", {}).get("flagged_tx_ids", [])
            ),
        }
    if "supervised" in layer_results:
        lr = layer_results["supervised"]
        layer_summary["supervised"] = {
            "patterns_loaded": lr.get("patterns_loaded", 0),
            "flagged_count": len(lr.get("flagged_tx_ids", [])),
        }
    if "graph" in layer_results:
        lr = layer_results["graph"]
        layer_summary["graph"] = {
            "node_count": lr.get("node_count", 0),
            "hidden_links": len(lr.get("hidden_links", [])),
            "linked_parties": len(lr.get("linked_parties", [])),
            "flagged_count": len(lr.get("flagged_tx_ids", [])),
        }

    return {
        "status": "ok",
        "module": "FO-01",
        "suspicious_transactions": details,
        "layer_summary": layer_summary,
        "statistics": output_stats,
    }
