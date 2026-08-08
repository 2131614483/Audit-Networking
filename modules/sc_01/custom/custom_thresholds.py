"""自定义风险等级阈值：从 config 读取，对评分结果按综合分映射风险等级。

分级规则（与 module.yaml threshold.confidence=0.85 同源；可被 config.threshold 覆盖）：
  * 极高 : 综合分 ≥ 80        → 立即预警，暂停合作
  * 高   : 60 ≤ 综合分 < 80   → 收紧账期，季度复评
  * 中   : 40 ≤ 综合分 < 60   → 半年度复评
  * 低   : 综合分 < 40        → 年度常规复评

config.threshold 字段说明：
  * confidence : 置信度门槛（默认 0.85，本模块用于标记 need_review）
  * extreme    : 极高阈值（默认 80）
  * high       : 高阈值（默认 60）
  * medium     : 中阈值（默认 40）
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值（与 engine._DEFAULT_LEVELS 保持一致）
_DEFAULT_EXTREME = 80.0
_DEFAULT_HIGH = 60.0
_DEFAULT_MEDIUM = 40.0
_DEFAULT_CONFIDENCE = 0.85


def apply_thresholds(result: Any, config: dict) -> Any:
    """对每个供应商按综合风险评分映射风险等级，并标记置信度复核。

    覆盖 engine 内部已写入的 level（确保阈值统一来自 config，便于不改代码调参）。
    同时打 need_review 标记：维度数据缺失或综合分落在边界区间时建议人工复核。
    """
    if not isinstance(result, dict):
        return result

    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    extreme = float(threshold.get("extreme", _DEFAULT_EXTREME))
    high = float(threshold.get("high", _DEFAULT_HIGH))
    medium = float(threshold.get("medium", _DEFAULT_MEDIUM))
    confidence = float(threshold.get("confidence", _DEFAULT_CONFIDENCE))

    suppliers = result.get("suppliers", [])

    def _level_of(score: float) -> str:
        if score >= extreme:
            return "极高"
        if score >= high:
            return "高"
        if score >= medium:
            return "中"
        return "低"

    def _is_borderline(score: float) -> bool:
        """落在等级边界 ±2 分区间视为边界案例，建议人工复核。"""
        for edge in (extreme, high, medium):
            if abs(score - edge) <= 2.0:
                return True
        return False

    for s in suppliers:
        score = float(s.get("total_score", 0.0))
        # 重新映射 level（确保统一来自 config）
        s["level"] = _level_of(score)
        # 置信度复核标记：边界分数 或 风险点过多 → need_review
        risk_point_count = len(s.get("risk_points", []))
        s["need_review"] = _is_borderline(score) or risk_point_count >= 5
        s["threshold_confidence"] = confidence

    # 重算 summary.level_distribution（保证与最新阈值一致）
    summary = result.get("summary") or {}
    summary["level_distribution"] = {
        "极高": sum(1 for s in suppliers if s["level"] == "极高"),
        "高": sum(1 for s in suppliers if s["level"] == "高"),
        "中": sum(1 for s in suppliers if s["level"] == "中"),
        "低": sum(1 for s in suppliers if s["level"] == "低"),
    }
    summary["need_review"] = sum(1 for s in suppliers if s.get("need_review"))
    result["summary"] = summary
    return result
