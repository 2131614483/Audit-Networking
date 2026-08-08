"""统一输出格式化：翻译报告 + 质量评估 + 告警。

输出结构：
  {
    "status": "ok",
    "module": "FO-05",
    "translations": [ {text_id, detected_language, translated_text,
                       translation_confidence, quality_level, sentiment,
                       legal_terms_found, code_switch_detected, ...}, ... ],
    "quality_assessment": { avg_confidence, quality_level,
                            quality_distribution, overall_sentiment, ... },
    "alerts": [ {type, text_id, message, ...}, ... ],
    "statistics": { text_count, language_distribution, code_switch_count,
                    total_legal_terms, needs_review_count, ... }
  }
"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    """把内部结果转为对外输出结构。"""
    if not isinstance(result, dict):
        return {"status": "error", "message": "invalid result"}

    translations = result.get("translations", [])
    summary = result.get("summary", {})
    alerts = result.get("alerts", [])

    # 翻译明细
    details = []
    for t in translations:
        details.append({
            "text_id": t.get("text_id"),
            "detected_language": t.get("detected_language"),
            "source_language": t.get("source_language"),
            "target_language": t.get("target_language"),
            "translated_text": t.get("translated_text"),
            "translation_confidence": t.get("translation_confidence", 0.0),
            "quality_level": t.get("quality_level", ""),
            "sentiment": t.get("sentiment", {}),
            "legal_terms_found": t.get("legal_terms_found", []),
            "code_switch_detected": t.get("code_switch_detected", False),
            "needs_review": t.get("needs_review", False),
            "escalate": t.get("escalate", False),
            "missing_terms": t.get("missing_terms", []),
            "rule_adjustments": t.get("rule_adjustments", []),
        })

    # 质量评估
    quality_assessment = {
        "avg_confidence": summary.get("avg_confidence", 0.0),
        "quality_level": summary.get("quality_level", ""),
        "quality_distribution": summary.get("quality_distribution", {}),
        "overall_sentiment": summary.get("overall_sentiment", ""),
        "avg_sentiment_score": summary.get("avg_sentiment_score", 0.0),
    }

    # 统计
    output_stats = {
        "text_count": summary.get("text_count", 0),
        "language_distribution": summary.get("language_distribution", {}),
        "code_switch_count": summary.get("code_switch_count", 0),
        "total_legal_terms": summary.get("total_legal_terms", 0),
        "needs_review_count": summary.get("needs_review_count", 0),
        "terminology_alerts": summary.get("terminology_alerts", 0),
        "escalate_count": summary.get("escalate_count", 0),
        "alert_count": summary.get("alert_count", 0),
    }

    return {
        "status": "ok",
        "module": "FO-05",
        "translations": details,
        "quality_assessment": quality_assessment,
        "alerts": alerts,
        "statistics": output_stats,
    }
