"""统一输出格式化：变更程序 / 版本历史 / 覆盖率统计 / 变更日志。

按 action 输出不同结构：
  analyze_change → 变更影响分析报告
  update_programs → 程序更新报告（含版本变更 + 变更日志）
  get_status → 程序库状态报告
  rollback → 回滚结果
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    meta = result.get("meta", {}) or {}
    base = {
        "status": "ok",
        "module": meta.get("module", "CO-03"),
        "meta": meta,
        "custom_rule_flags": result.get("custom_rule_flags", []),
    }

    # rollback 错误或 get_status / rollback 简单结果
    if "error" in result:
        base["status"] = "error"
        base["error"] = result["error"]
        return base

    if "updated_programs" in result:
        return _format_update(base, result)
    if "affected_programs" in result:
        return _format_analyze(base, result)
    if "total_programs" in result:
        return _format_status(base, result)
    if "rolled_back_to" in result:
        return _format_rollback(base, result)
    return base


def _format_analyze(base: dict, result: dict) -> dict:
    """analyze_change：变更影响分析报告。"""
    affected = result.get("affected_programs", []) or []
    base["regulation_title"] = result.get("regulation_title", "")
    base["affected_domains"] = result.get("affected_domains", [])
    base["affected_program_count"] = result.get("affected_program_count", 0)
    base["analysis_summary"] = result.get("analysis_summary", "")
    base["affected_programs"] = [
        {
            "prog_id": p.get("prog_id"),
            "name": p.get("name"),
            "domain": p.get("domain"),
            "current_version": p.get("current_version"),
            "impact_similarity": p.get("impact_similarity"),
            "impact_level": p.get("impact_level"),
            "update_urgency": p.get("update_urgency"),
            "update_priority": p.get("update_priority"),
            "mandatory_update": p.get("mandatory_update", False),
            "archive_candidate": p.get("archive_candidate", False),
            "archive_reason": p.get("archive_reason", ""),
        }
        for p in affected if isinstance(p, dict)
    ]
    base["priority_distribution"] = result.get("priority_distribution", {})
    base["coverage_stats"] = _coverage(result)
    base["thresholds"] = result.get("thresholds", {})
    return base


def _format_update(base: dict, result: dict) -> dict:
    """update_programs：程序更新报告。"""
    updated = result.get("updated_programs", []) or []
    base["batch_id"] = result.get("batch_id", "")
    base["change_type"] = result.get("change_type", "")
    base["programs_updated"] = result.get("programs_updated", 0)
    base["updated_programs"] = [
        {
            "prog_id": p.get("prog_id"),
            "old_version": p.get("old_version"),
            "new_version": p.get("new_version"),
            "change_count": p.get("change_count", 0),
            "updates_made": p.get("updates_made", []),
            "update_priority": p.get("update_priority"),
        }
        for p in updated if isinstance(p, dict)
    ]
    base["version_history"] = _version_history(updated)
    base["change_log"] = _change_log(updated)
    base["coverage_stats"] = _coverage(result)
    base["thresholds"] = result.get("thresholds", {})
    return base


def _format_status(base: dict, result: dict) -> dict:
    """get_status：程序库状态报告。"""
    base["total_programs"] = result.get("total_programs", 0)
    base["by_domain"] = result.get("by_domain", {})
    base["version_distribution"] = result.get("version_distribution", {})
    base["total_updates_applied"] = result.get("total_updates_applied", 0)
    base["last_update"] = result.get("last_update")
    return base


def _format_rollback(base: dict, result: dict) -> dict:
    """rollback：回滚结果。"""
    base["prog_id"] = result.get("prog_id", "")
    base["rolled_back_to"] = result.get("rolled_back_to", "")
    base["remaining_updates"] = result.get("remaining_updates", 0)
    base["rollback_status"] = result.get("status", "")
    return base


def _coverage(result: dict) -> dict:
    """覆盖率统计。"""
    return {
        "coverage_rate": result.get("coverage_rate"),
        "coverage_alert": result.get("coverage_alert", False),
    }


def _version_history(updated: list) -> list:
    """版本变更历史（old → new）。"""
    history = []
    for p in updated:
        if not isinstance(p, dict):
            continue
        history.append({
            "prog_id": p.get("prog_id"),
            "old_version": p.get("old_version"),
            "new_version": p.get("new_version"),
        })
    return history


def _change_log(updated: list) -> list:
    """变更日志（程序级变更明细）。"""
    log = []
    for p in updated:
        if not isinstance(p, dict):
            continue
        log.append({
            "prog_id": p.get("prog_id"),
            "change_count": p.get("change_count", 0),
            "changes": p.get("updates_made", []),
        })
    return log
