"""自定义阈值分级：根据敏感度评分进行四级分级（public/internal/confidential/restricted）。

分级规则（可被 config.threshold 覆盖）：
  * restricted   : sensitivity_score >= 0.85  → 受限（PII/医疗/生物特征，GDPR Art.9）
  * confidential : 0.65 <= score < 0.85       → 机密（财务/商业合同/客户名单，SOX/PCI-DSS）
  * internal     : 0.15 <= score < 0.65       → 内部（员工薪酬/绩效/联系方式）
  * public       : score < 0.15               → 公开（官网信息/公开年报）

同时把 engine 的 L0-L4 级别映射为四级 grade，便于对外报告。
"""
from __future__ import annotations

from typing import Any

# 出厂默认阈值
_DEFAULT_RESTRICTED = 0.85
_DEFAULT_CONFIDENTIAL = 0.65
_DEFAULT_INTERNAL = 0.15

# engine 五级 → 四级 grade 映射
_LEVEL_TO_GRADE = {
    "L4": "restricted",
    "L3": "confidential",
    "L2": "internal",
    "L1": "internal",
    "L0": "public",
}


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值对资产进行四级敏感度分级，写入 sensitivity_grade。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    restricted = float(threshold.get("restricted", _DEFAULT_RESTRICTED))
    confidential = float(threshold.get("confidential", _DEFAULT_CONFIDENTIAL))
    internal = float(threshold.get("internal", _DEFAULT_INTERNAL))

    assets = result.get("assets", [])
    grade_counts = {"public": 0, "internal": 0, "confidential": 0, "restricted": 0}
    for a in assets:
        score = float(a.get("sensitivity_score", 0.0) or 0.0)
        if score >= restricted:
            grade = "restricted"
        elif score >= confidential:
            grade = "confidential"
        elif score >= internal:
            grade = "internal"
        else:
            grade = "public"
        a["sensitivity_grade"] = grade
        grade_counts[grade] += 1

    # 同步统计
    stats = result.get("statistics", {})
    stats["grade_distribution"] = grade_counts
    stats["thresholds"] = {
        "restricted": restricted,
        "confidential": confidential,
        "internal": internal,
    }
    result["statistics"] = stats
    return result
