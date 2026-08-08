"""统一输出格式化：供应商风险排名表 + 五维雷达数据 + 统计汇总。

输出结构：
  {
    "status": "ok",
    "supplier_ranking": [
      {
        "supplier_id", "name", "uscc",
        "total_score", "level", "need_review", "rule_upgraded",
        "sub_scores": {"business", "litigation", "financial", "esg", "sentiment"},
        "radar": {"labels": [...5维...], "values": [...5维...]},
        "risk_points": [{"dimension", "point"}, ...],
        "rule_flags": [...],
        "recommendations": [...],
      }, ...
    ],
    "statistics": {
      "total": N,
      "level_distribution": {"极高", "高", "中", "低"},
      "need_review": N,
      "rule_upgraded": N,
      "high_risk_list": [{"supplier_id", "name", "total_score", "level"}, ...],
      "recommendations_summary": [   # 去重后的全部建议措施
        "立即暂停合作，启动专项尽职调查", ...
      ],
    },
  }
"""
from __future__ import annotations

from typing import Any

# 五维雷达标签（顺序固定，便于前端绘制）
_RADAR_LABELS = ["工商", "司法", "财务", "ESG", "舆情"]
_RADAR_KEYS = ["business", "litigation", "financial", "esg", "sentiment"]

# 高风险等级（进入 high_risk_list 的等级）
_HIGH_RISK_LEVELS = ("极高", "高")


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构（供应商排名表 + 五维雷达 + 统计）。"""
    if not isinstance(result, dict):
        return {"status": "ok", "supplier_ranking": [], "statistics": {}}

    suppliers = result.get("suppliers", [])
    # supplier_ranking：按 total_score 降序（engine 已排序，但规则升级后可能乱序，重新排）
    ranked = sorted(
        suppliers, key=lambda s: float(s.get("total_score", 0.0)), reverse=True
    )

    ranking = []
    high_risk_list = []
    all_recommendations: list[str] = []

    for s in ranked:
        sub_scores = s.get("sub_scores", {}) or {}
        # 五维雷达数据
        radar_values = [float(sub_scores.get(k, 0.0)) for k in _RADAR_KEYS]

        item = {
            "supplier_id": s.get("supplier_id"),
            "name": s.get("name"),
            "uscc": s.get("uscc"),
            "total_score": s.get("total_score"),
            "level": s.get("level"),
            "need_review": bool(s.get("need_review", False)),
            "rule_upgraded": bool(s.get("rule_upgraded", False)),
            "sub_scores": sub_scores,
            "radar": {"labels": list(_RADAR_LABELS), "values": radar_values},
            "risk_points": s.get("risk_points", []),
            "rule_flags": s.get("rule_flags", []),
            "recommendations": s.get("recommendations", []),
        }
        ranking.append(item)

        # 高风险清单
        if s.get("level") in _HIGH_RISK_LEVELS:
            high_risk_list.append({
                "supplier_id": s.get("supplier_id"),
                "name": s.get("name"),
                "total_score": s.get("total_score"),
                "level": s.get("level"),
            })

        # 建议措施汇总（去重保序）
        for rec in s.get("recommendations", []):
            if rec not in all_recommendations:
                all_recommendations.append(rec)

    # 统计汇总
    summary = result.get("summary") or {}
    level_dist = summary.get("level_distribution", {}) or {}
    statistics = {
        "total": len(ranking),
        "level_distribution": {
            "极高": level_dist.get("极高", 0),
            "高": level_dist.get("高", 0),
            "中": level_dist.get("中", 0),
            "低": level_dist.get("低", 0),
        },
        "need_review": int(summary.get("need_review", 0)),
        "rule_upgraded": int(summary.get("rule_upgraded", 0)),
        "high_risk_list": high_risk_list,
        "recommendations_summary": all_recommendations,
    }

    return {
        "status": "ok",
        "source": result.get("source"),
        "supplier_ranking": ranking,
        "statistics": statistics,
    }
