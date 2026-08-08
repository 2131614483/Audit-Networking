"""自定义业务规则：在 engine 评分 + custom_thresholds 分级之后执行，覆盖/补充结果。

规则清单（一票否决 / 自动升级 / 高风险标记）：
  1) 失信被执行人（dishonest_count ≥ 1）→ 自动升级为「极高」
  2) 注册资本 < 10 万元 → 标记 high_risk_flag=capital_too_low
  3) 成立年限 < 1 年 → 标记 high_risk_flag=newly_established
  4) 经营状态为 注销/吊销/停业/清算 → 自动升级为「极高」
  5) 经营现金流为负 且 资产负债率 ≥ 0.8 → 自动升级为「高」（财务恶化组合）
  6) 负面新闻 ≥ 10 条 → 自动升级为「高」（舆情危机）

被规则升级的供应商会在 risk_points 中追加 rule_flags 风险点，并刷新 need_review=True。
"""
from __future__ import annotations

from typing import Any

# 自动升级触发的等级
_LEVEL_EXTREME = "极高"
_LEVEL_HIGH = "高"


def _bump_level(current: str, target: str) -> str:
    """只升不降：将 current 升级到 target（若 target 更高）。"""
    order = {"低": 0, "中": 1, "高": 2, "极高": 3}
    if order.get(target, 0) > order.get(current, 0):
        return target
    return current


def apply_custom_rules(result: Any, config: dict) -> Any:
    """对每个供应商套用业务规则：一票否决升级 + 高风险标记。"""
    if not isinstance(result, dict):
        return result

    for s in result.get("suppliers", []):
        raw = s.get("_raw") or {}
        biz = raw.get("business", {}) or {}
        lit = raw.get("litigation", {}) or {}
        fin = raw.get("financial", {}) or {}
        sen = raw.get("sentiment", {}) or {}

        rule_flags: list[str] = []
        current_level = s.get("level", "低")

        # 规则 1：失信被执行 → 极高
        dishonest = _to_int(lit.get("dishonest_count"))
        if dishonest >= 1:
            current_level = _bump_level(current_level, _LEVEL_EXTREME)
            rule_flags.append(f"失信被执行人（{dishonest}次）→ 自动升级极高")

        # 规则 2：注册资本 < 10 万 → 高风险标记
        cap = _to_float(biz.get("registered_capital"))
        if 0 < cap < 100000:
            rule_flags.append(f"注册资本过低（{cap / 10000:.2f}万元）→ 标记高风险")
            current_level = _bump_level(current_level, _LEVEL_HIGH)

        # 规则 3：成立 < 1 年 → 新设风险标记
        years = _to_float(biz.get("establishment_years"))
        if 0 < years < 1:
            rule_flags.append(f"新设企业（成立{years:.1f}年）→ 标记新设风险")

        # 规则 4：经营状态异常 → 极高
        status = (biz.get("business_status") or "").strip()
        if status in ("注销", "吊销", "停业", "清算"):
            current_level = _bump_level(current_level, _LEVEL_EXTREME)
            rule_flags.append(f"经营状态异常（{status}）→ 自动升级极高")

        # 规则 5：现金流为负 + 高负债 → 高
        cash_flow = _to_float(fin.get("cash_flow"))
        debt_ratio = _to_float(fin.get("debt_ratio"))
        if cash_flow < 0 and debt_ratio >= 0.8:
            current_level = _bump_level(current_level, _LEVEL_HIGH)
            rule_flags.append("现金流为负且资产负债率≥80% → 自动升级高")

        # 规则 6：负面新闻 ≥ 10 条 → 高
        news_count = _to_int(sen.get("news_count"))
        if news_count >= 10:
            current_level = _bump_level(current_level, _LEVEL_HIGH)
            rule_flags.append(f"负面新闻过多（{news_count}条）→ 自动升级高")

        # 写回 level（已被规则升级时）
        if current_level != s.get("level"):
            s["level"] = current_level
            s["rule_upgraded"] = True
        else:
            s["rule_upgraded"] = False

        # 把规则命中追加到 risk_points（dimension=rule）
        if rule_flags:
            existing = s.setdefault("risk_points", [])
            for flag in rule_flags:
                existing.append({"dimension": "rule", "point": flag})
            # 规则命中必复核
            s["need_review"] = True
            s["rule_flags"] = rule_flags
        else:
            s["rule_flags"] = []

    # 规则可能改了等级，重算 level_distribution
    suppliers = result.get("suppliers", [])
    summary = result.get("summary") or {}
    summary["level_distribution"] = {
        "极高": sum(1 for s in suppliers if s.get("level") == "极高"),
        "高": sum(1 for s in suppliers if s.get("level") == "高"),
        "中": sum(1 for s in suppliers if s.get("level") == "中"),
        "低": sum(1 for s in suppliers if s.get("level") == "低"),
    }
    summary["rule_upgraded"] = sum(1 for s in suppliers if s.get("rule_upgraded"))
    result["summary"] = summary
    return result


# ---------- 内部工具 ----------
def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0
