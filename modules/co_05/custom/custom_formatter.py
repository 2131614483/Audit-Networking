"""统一输出格式化：洗钱网络发现报告。

输出结构：
  {
    "status": "ok",
    "module": "CO-05",
    "action": "detect_patterns" | "load_graph" | "trace_funds" | "centrality_analysis",
    "detections": [ {pattern_id, pattern_name, severity, risk_grade, evidence, ...}, ... ],
    "summary": { total_detections, by_severity, by_pattern, risk_grading, rule_adjustments, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外洗钱网络报告结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    meta = result.get("meta", {})
    action = _infer_action(result)

    if "patterns_detected" in result:
        return _format_detect_patterns(result, meta)
    if "node_count" in result and "top_pagerank" in result:
        return _format_centrality(result, meta)
    if "total_paths_found" in result:
        return _format_trace_funds(result, meta)
    if "node_count" in result and "edge_count" in result:
        return _format_load_graph(result, meta)

    return {
        "status": "ok",
        "module": "CO-05",
        "action": action,
        "result": result,
    }


def _infer_action(result: dict) -> str:
    if "patterns_detected" in result:
        return "detect_patterns"
    if "total_paths_found" in result:
        return "trace_funds"
    if "top_pagerank" in result:
        return "centrality_analysis"
    if "edge_count" in result:
        return "load_graph"
    return "unknown"


def _format_detect_patterns(result: dict, meta: dict) -> dict:
    """格式化模式检测报告。"""
    detections = result.get("patterns_detected", [])
    details = []
    for d in detections:
        details.append({
            "pattern_id": d.get("pattern_id"),
            "pattern_name": d.get("pattern_name"),
            "severity": d.get("severity"),
            "confidence": d.get("confidence"),
            "risk_grade": d.get("risk_grade", "low"),
            "target_node": d.get("target_node"),
            "source_count": d.get("source_count"),
            "transaction_count": d.get("transaction_count"),
            "total_amount": d.get("total_amount"),
            "cycle_path": d.get("cycle_path"),
            "hop_count": d.get("hop_count"),
            "return_ratio": d.get("return_ratio"),
            "shared_attribute": d.get("shared_attribute"),
            "node_count": d.get("node_count"),
            "nodes": d.get("nodes"),
            "evidence": d.get("evidence", []),
            "layering_pattern": d.get("layering_pattern", False),
            "organized_smurfing": d.get("organized_smurfing", False),
            "suspected_syndicate": d.get("suspected_syndicate", False),
            "rule_adjustments": d.get("rule_adjustments", []),
        })

    summary = {
        "total_detections": result.get("total_detections", len(detections)),
        "by_severity": result.get("by_severity", {}),
        "by_pattern": result.get("by_pattern", {}),
        "risk_grading": result.get("risk_grading", {
            "critical": 0, "high": 0, "medium": 0, "low": 0,
        }),
        "rule_adjustments": result.get("rule_adjustments", {}),
        "thresholds": result.get("thresholds", {}),
    }

    return {
        "status": "ok",
        "module": "CO-05",
        "action": "detect_patterns",
        "meta": meta,
        "detections": details,
        "summary": summary,
    }


def _format_centrality(result: dict, meta: dict) -> dict:
    """格式化中心性分析报告。"""
    return {
        "status": "ok",
        "module": "CO-05",
        "action": "centrality_analysis",
        "meta": meta,
        "node_count": result.get("node_count", 0),
        "top_pagerank": result.get("top_pagerank", []),
        "top_betweenness": result.get("top_betweenness", []),
        "top_degree": result.get("top_degree", []),
        "network_health": result.get("network_health", {}),
    }


def _format_trace_funds(result: dict, meta: dict) -> dict:
    """格式化资金流追踪报告。"""
    return {
        "status": "ok",
        "module": "CO-05",
        "action": "trace_funds",
        "meta": meta,
        "start_nodes": result.get("start_nodes", []),
        "total_paths_found": result.get("total_paths_found", 0),
        "max_depth": result.get("max_depth", 0),
        "paths": result.get("paths", []),
    }


def _format_load_graph(result: dict, meta: dict) -> dict:
    """格式化图谱摘要报告。"""
    return {
        "status": "ok",
        "module": "CO-05",
        "action": "load_graph",
        "meta": meta,
        "node_count": result.get("node_count", 0),
        "edge_count": result.get("edge_count", 0),
        "node_type_distribution": result.get("node_type_distribution", {}),
        "edge_types": result.get("edge_types", {}),
    }
