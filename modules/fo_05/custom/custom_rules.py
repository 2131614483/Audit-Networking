"""自定义业务规则：在 engine 之后执行，补充翻译质量告警。

规则：
  1) 翻译置信度 < 0.7 → 人工复核（needs_review = True）
  2) 关键审计术语缺失 → 术语告警（expected_terms 未命中）
  3) 不支持的语言 → 升级处理（escalate = True）
"""
from __future__ import annotations

from typing import Any

_REVIEW_THRESHOLD = 0.7
_SUPPORTED_LANGS = {"zh", "en", "ja", "ko"}


def apply_custom_rules(result: Any, config: dict) -> Any:
    """应用业务规则：低置信度复核 / 术语缺失告警 / 不支持语言升级。"""
    if not isinstance(result, dict):
        return result
    rules_cfg = (config or {}).get("rules", {}) if isinstance(config, dict) else {}
    review_threshold = float(
        rules_cfg.get("review_threshold", _REVIEW_THRESHOLD)
    )
    supported = set(rules_cfg.get("supported_languages", _SUPPORTED_LANGS))
    expected_terms = rules_cfg.get("expected_terms", [])

    translations = result.get("translations", [])
    alerts = []
    review_count = 0
    term_alert_count = 0
    escalate_count = 0

    for t in translations:
        adjustments = t.setdefault("rule_adjustments", [])
        confidence = t.get("translation_confidence", 1.0)

        # 规则 1：置信度 < 阈值 → 人工复核
        if confidence < review_threshold:
            t["needs_review"] = True
            review_count += 1
            adjustments.append(
                f"翻译置信度{confidence:.2f}<{review_threshold}需人工复核"
            )
            alerts.append({
                "type": "low_confidence",
                "text_id": t.get("text_id"),
                "confidence": confidence,
                "message": "翻译置信度低于阈值，需人工复核",
            })
        else:
            t["needs_review"] = False

        # 规则 2：关键审计术语缺失 → 术语告警
        if expected_terms:
            found_terms = {
                term["zh"] for term in t.get("legal_terms_found", [])
            }
            missing = [et for et in expected_terms if et not in found_terms]
            if missing:
                term_alert_count += 1
                t["missing_terms"] = missing
                adjustments.append(f"缺失关键术语:{','.join(missing)}")
                alerts.append({
                    "type": "terminology_alert",
                    "text_id": t.get("text_id"),
                    "missing": missing,
                    "message": "关键审计术语缺失",
                })
            else:
                t.setdefault("missing_terms", [])
        else:
            t.setdefault("missing_terms", [])

        # 规则 3：不支持的语言 → 升级
        detected = t.get("detected_language", "unknown")
        if detected not in supported:
            escalate_count += 1
            t["escalate"] = True
            adjustments.append(f"不支持的语言:{detected}")
            alerts.append({
                "type": "unsupported_language",
                "text_id": t.get("text_id"),
                "language": detected,
                "message": "不支持的语言，需升级处理",
            })
        else:
            t["escalate"] = False

    result["alerts"] = alerts
    summary = result.get("summary", {})
    summary["alert_count"] = len(alerts)
    summary["needs_review_count"] = review_count
    summary["terminology_alerts"] = term_alert_count
    summary["escalate_count"] = escalate_count
    result["summary"] = summary
    return result
