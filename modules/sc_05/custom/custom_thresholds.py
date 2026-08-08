"""自定义阈值分级：根据对标偏离度进行三级分级（acceptable/marginal/expensive）。

分级规则（可被 config.threshold 覆盖），基于 |deviation_pct|：
  * no_data    : 无基准（status == no_baseline）→ 无法对标
  * acceptable : |deviation_pct| ≤ 10%  → 价格合理
  * marginal   : 10% < |deviation_pct| ≤ 25%  → 边际偏离
  * expensive  : |deviation_pct| > 25%  → 偏离显著
"""
from __future__ import annotations

from typing import Any

_DEFAULT_ACCEPTABLE = 10.0
_DEFAULT_MARGINAL = 25.0


def apply_thresholds(result: Any, config: dict) -> Any:
    """根据 config 阈值按 |deviation_pct| 重新分级对标结果。"""
    if not isinstance(result, dict):
        return result
    threshold = (config or {}).get("threshold", {}) if isinstance(config, dict) else {}
    acceptable = float(threshold.get("acceptable_pct", _DEFAULT_ACCEPTABLE))
    marginal = float(threshold.get("marginal_pct", _DEFAULT_MARGINAL))

    results = result.get("results", [])
    counts = {"acceptable": 0, "marginal": 0, "expensive": 0, "no_data": 0}
    for r in results:
        if r.get("status") == "no_baseline" or r.get("deviation_pct") is None:
            r["grade"] = "no_data"
            counts["no_data"] += 1
            continue
        dev = abs(float(r.get("deviation_pct", 0.0)))
        if dev <= acceptable:
            r["grade"] = "acceptable"
            counts["acceptable"] += 1
        elif dev <= marginal:
            r["grade"] = "marginal"
            counts["marginal"] += 1
        else:
            r["grade"] = "expensive"
            counts["expensive"] += 1
        # 显著偏离确认标记
        r["confirmed_deviation"] = dev > marginal

    # 同步统计
    summary = result.get("summary", {})
    summary["grade_distribution"] = counts
    summary["thresholds"] = {
        "acceptable_pct": acceptable, "marginal_pct": marginal,
    }
    summary["confirmed_deviation_count"] = counts["expensive"]
    result["summary"] = summary
    return result
