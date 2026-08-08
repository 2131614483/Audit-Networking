"""统一输出格式化：法规监控日报 + 分类统计 + 高影响清单 + 推送建议。

输出结构：
  {
    "status": "ok",
    "report": {
      "title": "法规监控日报",
      "generated_at": "...",
      "enterprise": {...},
      "summary": {"total", "by_category", "by_impact", "push_count", "covered_countries"},
      "regulations": [ {reg_id, title, country, category, impact_level, relevance, tier, push, ...} ],
      "high_impact_list": [ ... ],          # impact_level == high
      "push_recommendations": [ ... ]        # push == true
    }
  }
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _concise_reg(r: dict) -> dict:
    """法规精简视图（用于日报正文）。"""
    title = r.get("title") or r.get("title_en") or r.get("reg_id", "")
    return {
        "reg_id": r.get("reg_id"),
        "title": title,
        "title_en": r.get("title_en"),
        "country": r.get("country"),
        "country_name": r.get("country_name"),
        "agency": r.get("agency"),
        "publish_date": r.get("publish_date"),
        "effective_date": r.get("effective_date"),
        "category": r.get("category"),
        "category_confidence": r.get("category_confidence"),
        "impact_level": r.get("impact_level"),
        "relevance": r.get("relevance"),
        "tier": r.get("tier"),
        "push": bool(r.get("push")),
        "push_reasons": r.get("push_reasons", []),
        "matched_rules": r.get("matched_rules", []),
        "matched_keywords": r.get("matched_keywords", []),
        "url": r.get("url"),
    }


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构（法规监控日报）。"""
    if not isinstance(result, dict):
        return {"status": "ok", "report": result}

    regs = result.get("regulations", [])
    stats = result.get("statistics", {})
    enterprise = result.get("enterprise", {})

    concise = [_concise_reg(r) for r in regs]
    high_impact = [_concise_reg(r) for r in regs if r.get("impact_level") == "high"]
    push_list = [_concise_reg(r) for r in regs if r.get("push")]

    summary = {
        "total": stats.get("total", len(regs)),
        "by_category": stats.get("by_category", {}),
        "by_impact": stats.get("by_impact", {}),
        "push_count": stats.get("push_count", len(push_list)),
        "covered_countries": stats.get("covered_countries", []),
    }

    return {
        "status": "ok",
        "report": {
            "title": "法规监控日报",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "enterprise": enterprise,
            "summary": summary,
            "regulations": concise,
            "high_impact_list": high_impact,
            "push_recommendations": push_list,
        },
    }
