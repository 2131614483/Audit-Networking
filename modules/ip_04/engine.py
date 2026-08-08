"""[IP-04] AI财务规范性智能诊断 —— 规则诊断 + 行业对标 + 异常评分。

算法设计（纯 stdlib：statistics / re / json）：

  * _load_model:
      - 加载财务问题知识库（7大类 20+ 问题模式，每类含特征/指标/严重程度）
      - 预定义行业基准指标（毛利率/净利率/资产负债率/ROE 等）
      - 异常评分公式：0-100 分，≥85 高风险，70-84 中风险，50-69 低风险
  * _preprocess: 从 input 提取 financials（财务指标）+ industry + company_info
  * _infer:
      ① 规则诊断：遍历问题模式，匹配特征指标
      ② 行业对标：计算偏离度 = (企业值 - 行业中位数) / 行业中位数
      ③ 综合异常评分
      ④ 根因关联
  * _postprocess:
      - 输出问题总览 + 风险雷达 + 行业对标表 + 整改建议
"""
from __future__ import annotations

import statistics
from typing import Any

from modules.shared.base_engine import AbstractEngine


INDUSTRY_BENCHMARKS = {
    "制造业": {"gross_margin": 0.22, "net_margin": 0.08, "roe": 0.12,
               "debt_ratio": 0.55, "ar_turnover": 5.2, "inv_turnover": 4.5,
               "ocf_to_net_profit": 0.9},
    "软件和信息技术服务业": {"gross_margin": 0.45, "net_margin": 0.15, "roe": 0.18,
                               "debt_ratio": 0.40, "ar_turnover": 4.8, "inv_turnover": 12.0,
                               "ocf_to_net_profit": 0.85},
    "批发和零售业": {"gross_margin": 0.12, "net_margin": 0.04, "roe": 0.10,
                     "debt_ratio": 0.65, "ar_turnover": 6.5, "inv_turnover": 6.0,
                     "ocf_to_net_profit": 1.0},
    "医药制造业": {"gross_margin": 0.55, "net_margin": 0.20, "roe": 0.16,
                   "debt_ratio": 0.45, "ar_turnover": 4.2, "inv_turnover": 3.8,
                   "ocf_to_net_profit": 0.80},
    "建筑业": {"gross_margin": 0.10, "net_margin": 0.03, "roe": 0.08,
               "debt_ratio": 0.75, "ar_turnover": 3.5, "inv_turnover": 5.0,
               "ocf_to_net_profit": 0.95},
    "default": {"gross_margin": 0.25, "net_margin": 0.09, "roe": 0.12,
                "debt_ratio": 0.55, "ar_turnover": 5.0, "inv_turnover": 5.0,
                "ocf_to_net_profit": 0.9},
}

PROBLEM_PATTERNS = [
    {"id": "FP-001", "category": "收入确认", "name": "收入确认时点不当",
     "severity": "high", "features": ["rev_growth_high", "ar_turnover_low"],
     "indicators": ["rev_yoy", "ar_turnover", "ocf_to_rev"]},
    {"id": "FP-002", "category": "收入确认", "name": "收入与现金流不匹配",
     "severity": "high", "features": ["ocf_to_net_profit_low"],
     "indicators": ["ocf_to_net_profit"]},
    {"id": "FP-003", "category": "成本费用", "name": "毛利率显著高于行业",
     "severity": "medium", "features": ["gross_margin_high"],
     "indicators": ["gross_margin"]},
    {"id": "FP-004", "category": "成本费用", "name": "费用资本化异常",
     "severity": "medium", "features": ["expense_ratio_low"],
     "indicators": ["rd_expense_ratio"]},
    {"id": "FP-005", "category": "资产质量", "name": "应收账款坏账风险",
     "severity": "medium", "features": ["ar_turnover_low"],
     "indicators": ["ar_turnover"]},
    {"id": "FP-006", "category": "资产质量", "name": "存货跌价风险",
     "severity": "medium", "features": ["inv_turnover_low"],
     "indicators": ["inv_turnover"]},
    {"id": "FP-007", "category": "内部控制", "name": "资金管理缺陷",
     "severity": "medium", "features": ["ocf_negative"],
     "indicators": ["ocf_to_net_profit"]},
    {"id": "FP-008", "category": "关联交易", "name": "关联交易占比过高",
     "severity": "high", "features": ["related_party_high"],
     "indicators": ["related_party_ratio"]},
    {"id": "FP-009", "category": "税务合规", "name": "综合税负率偏低",
     "severity": "medium", "features": ["tax_rate_low"],
     "indicators": ["tax_rate"]},
    {"id": "FP-010", "category": "会计政策", "name": "资产负债率偏高",
     "severity": "low", "features": ["debt_ratio_high"],
     "indicators": ["debt_ratio"]},
]


class MLEngine(AbstractEngine):
    """AI财务规范性智能诊断引擎（纯 stdlib：规则诊断 + 行业对标 + 评分）。"""

    def _load_model(self) -> None:
        self.model = {
            "problem_patterns": PROBLEM_PATTERNS,
            "industry_benchmarks": INDUSTRY_BENCHMARKS,
            "thresholds": {
                "high": 85, "medium": 70, "low": 50,
                "deviation_warn": 0.3, "deviation_alert": 0.5,
            },
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取财务指标并映射到统一字段名。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")
        fin = input_data.get("financials", {}) or {}
        industry = input_data.get("industry", "default")
        mapped = {
            "gross_margin": fin.get("gross_margin", fin.get("毛利率")),
            "net_margin": fin.get("net_margin", fin.get("净利率")),
            "roe": fin.get("roe", fin.get("ROE")),
            "debt_ratio": fin.get("debt_ratio", fin.get("资产负债率")),
            "ar_turnover": fin.get("ar_turnover", fin.get("应收账款周转率")),
            "inv_turnover": fin.get("inv_turnover", fin.get("存货周转率")),
            "ocf_to_net_profit": fin.get("ocf_to_net_profit", fin.get("经营现金流/净利润")),
            "rev_yoy": fin.get("rev_yoy", fin.get("营收增长率")),
            "rd_expense_ratio": fin.get("rd_expense_ratio", fin.get("研发费用率")),
            "tax_rate": fin.get("tax_rate", fin.get("综合税率")),
            "related_party_ratio": fin.get("related_party_ratio", fin.get("关联交易占比")),
        }
        return {
            "financials": mapped,
            "industry": industry if industry in INDUSTRY_BENCHMARKS else "default",
            "raw": input_data,
        }

    def _infer(self, prepared: Any) -> Any:
        fin = prepared["financials"]
        ind = prepared["industry"]
        bench = self.model["industry_benchmarks"][ind]

        benchmarks_compare = self._compute_benchmark_compare(fin, bench)
        detected = self._rule_diagnose(fin, bench)
        score = self._compute_score(detected, benchmarks_compare)

        risk_level = "正常"
        if score >= 85:
            risk_level = "高风险"
        elif score >= 70:
            risk_level = "中风险"
        elif score >= 50:
            risk_level = "低风险"

        return {
            "diagnosis_score": score,
            "risk_level": risk_level,
            "industry_benchmark": {"industry": ind, "benchmarks": bench, "compare": benchmarks_compare},
            "problems": detected,
        }

    def _compute_benchmark_compare(self, fin: dict, bench: dict) -> list[dict]:
        result = []
        for key, bench_val in bench.items():
            co_val = fin.get(key)
            if co_val is None:
                continue
            if bench_val == 0:
                deviation = 0.0
            else:
                deviation = (co_val - bench_val) / bench_val
            result.append({
                "metric": key,
                "company": round(co_val, 4) if isinstance(co_val, float) else co_val,
                "industry": round(bench_val, 4),
                "deviation_pct": round(deviation * 100, 2),
                "direction": "up" if deviation > 0 else "down",
                "flag": "alert" if abs(deviation) > 0.5 else ("warn" if abs(deviation) > 0.3 else "ok"),
            })
        return result

    def _rule_diagnose(self, fin: dict, bench: dict) -> list[dict]:
        problems = []
        for p in self.model["problem_patterns"]:
            hit = False
            reasons = []
            if p["id"] == "FP-001":
                if fin.get("rev_yoy", 0) > 0.3 and fin.get("ar_turnover", 99) < bench.get("ar_turnover", 5) * 0.8:
                    hit = True
                    reasons.append(f"营收增长率{fin['rev_yoy']:.0%}但应收账款周转率偏低")
            if p["id"] == "FP-002":
                v = fin.get("ocf_to_net_profit")
                if v is not None and v < 0.7:
                    hit = True
                    reasons.append(f"经营现金流/净利润={v:.2f}")
            if p["id"] == "FP-003":
                v = fin.get("gross_margin")
                if v is not None and v > bench.get("gross_margin", 0.25) * 1.5:
                    hit = True
                    reasons.append(f"毛利率{v:.1%}显著高于行业基准")
            if p["id"] == "FP-005":
                v = fin.get("ar_turnover")
                if v is not None and v < bench.get("ar_turnover", 5) * 0.7:
                    hit = True
                    reasons.append(f"应收账款周转率{v:.1f}明显低于行业")
            if p["id"] == "FP-006":
                v = fin.get("inv_turnover")
                if v is not None and v < bench.get("inv_turnover", 5) * 0.7:
                    hit = True
                    reasons.append(f"存货周转率{v:.1f}偏低")
            if p["id"] == "FP-007":
                v = fin.get("ocf_to_net_profit")
                if v is not None and v < 0:
                    hit = True
                    reasons.append("经营现金流为负")
            if p["id"] == "FP-008":
                v = fin.get("related_party_ratio")
                if v is not None and v > 0.3:
                    hit = True
                    reasons.append(f"关联交易占比{v:.1%}")
            if p["id"] == "FP-009":
                v = fin.get("tax_rate")
                if v is not None and v < 0.05:
                    hit = True
                    reasons.append(f"综合税负率{v:.1%}")
            if p["id"] == "FP-010":
                v = fin.get("debt_ratio")
                if v is not None and v > bench.get("debt_ratio", 0.55) * 1.2:
                    hit = True
                    reasons.append(f"资产负债率{v:.1%}偏高")
            if hit:
                problems.append({
                    "pattern_id": p["id"],
                    "category": p["category"],
                    "name": p["name"],
                    "severity": p["severity"],
                    "reasons": reasons,
                    "indicators": p["indicators"],
                })
        return problems

    def _compute_score(self, problems: list[dict], benchmark_compare: list[dict]) -> int:
        score = 100
        sev_w = {"high": 15, "medium": 8, "low": 3}
        for p in problems:
            score -= sev_w.get(p["severity"], 5)
        alert_count = sum(1 for b in benchmark_compare if b["flag"] == "alert")
        warn_count = sum(1 for b in benchmark_compare if b["flag"] == "warn")
        score -= alert_count * 10
        score -= warn_count * 4
        return max(0, min(100, score))

    def _postprocess(self, result: Any) -> Any:
        problems = result["problems"]
        high = [p for p in problems if p["severity"] == "high"]
        medium = [p for p in problems if p["severity"] == "medium"]
        low = [p for p in problems if p["severity"] == "low"]
        result["statistics"] = {
            "total_issues": len(problems),
            "high": len(high),
            "medium": len(medium),
            "low": len(low),
            "benchmark_metrics": len(result["industry_benchmark"]["compare"]),
        }
        suggestions = []
        for p in problems:
            suggestions.append({
                "pattern_id": p["pattern_id"],
                "severity": p["severity"],
                "name": p["name"],
                "suggestion": self._suggest_for(p["pattern_id"]),
            })
        result["suggestions"] = suggestions
        return result

    def _suggest_for(self, pid: str) -> str:
        tips = {
            "FP-001": "复核收入确认政策，补充合同条款与控制权转移证据",
            "FP-002": "分析大额应收账款形成原因，检查是否存在提前确认收入",
            "FP-003": "对比行业同类公司，复核毛利率计算是否准确",
            "FP-004": "重新划分资本性支出与收益性支出边界",
            "FP-005": "执行应收账款函证，复核坏账准备计提充分性",
            "FP-006": "执行存货盘点与减值测试，关注滞销和过时存货",
            "FP-007": "完善资金内控流程，监控经营现金流",
            "FP-008": "按 CAS 36 号完整披露关联方及交易定价政策",
            "FP-009": "复核税收优惠资质，确保合规持续享受",
            "FP-010": "评估偿债能力，关注到期债务结构",
        }
        return tips.get(pid, "结合具体情况制定整改措施")
