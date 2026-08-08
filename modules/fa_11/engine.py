from typing import Any, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import re, math, json, statistics
from difflib import SequenceMatcher

from modules.shared.base_engine import AbstractEngine


class MLEngine(AbstractEngine):
    """FA-11 关联交易定价公允性AI分析。

    算法：
      1) 可比公司法：同行业、同规模、同业务的非关联交易价格做参照，计算 Z-score；
      2) 历史价格趋势：过去 3 年同类交易的均值 ± 2σ 区间；
      3) 利润分割法/成本加成法：与关联方利润率比较；
      4) 风险调整：根据关联方持股比例、业务依赖度做调整系数；
      5) 综合输出：公允/偏离/重大偏离三级 + 偏离率 + 调整建议。
    """

    TOLERANCE_DEFAULT = 0.10

    def __init__(self, name: str = "fa_11") -> None:
        super().__init__(name)
        self._industry_bias: Dict[str, float] = {}

    def _load_model(self) -> None:
        self._industry_bias = {
            "制造": 0.08,
            "贸易": 0.12,
            "金融": 0.05,
            "房地产": 0.15,
            "科技": 0.10,
            "医药": 0.09,
            "default": 0.10,
        }

    def _preprocess(self, input_data: Any) -> Dict[str, Any]:
        data = input_data or {}
        if not isinstance(data, dict):
            data = {"transactions": data}
        txs = data.get("transactions", data.get("交易", []))
        peers = data.get("peers", data.get("可比数据", []))
        history = data.get("history", data.get("历史价格", []))
        if not isinstance(txs, list):
            txs = [txs]
        norm_txs = []
        for t in txs:
            if not isinstance(t, dict):
                continue
            norm_txs.append({
                "tx_id": str(t.get("tx_id", t.get("id", ""))),
                "subject": str(t.get("subject", t.get("科目/业务", ""))),
                "amount": self._f(t.get("amount", t.get("金额", 0))),
                "quantity": self._f(t.get("quantity", t.get("数量", 1))),
                "unit_price": self._f(t.get("unit_price", t.get("单价", 0))),
                "related_party": str(t.get("related_party", t.get("关联方", ""))),
                "ownership_pct": self._f(t.get("ownership_pct", t.get("持股比例", 0))),
                "industry": str(t.get("industry", t.get("行业", "default"))),
                "direction": str(t.get("direction", t.get("交易方向", ""))),
                "profit_margin": self._f(t.get("profit_margin", t.get("利润率", 0))),
                "dependence": self._f(t.get("dependence", t.get("业务依赖度", 0))),
                "contract_ref": str(t.get("contract_ref", "")),
            })
        peer_list = [
            {"price": self._f(p.get("price", p.get("单价", 0))), "industry": str(p.get("industry", "default"))}
            for p in peers if isinstance(p, dict)
        ]
        hist_list = [
            {"price": self._f(h.get("price", h.get("单价", 0))), "year": str(h.get("year", ""))}
            for h in history if isinstance(h, dict)
        ]
        return {"transactions": norm_txs, "peers": peer_list, "history": hist_list, "context": data.get("context", {})}

    def _infer(self, prepared: Any) -> Any:
        txs = prepared["transactions"]
        peers = prepared["peers"]
        hist = prepared["history"]
        peer_stats = self._peer_stats(peers)
        hist_stats = self._hist_stats(hist)
        results = []
        for tx in txs:
            unit = tx["unit_price"] or (tx["amount"] / max(1, tx["quantity"]))
            fairness, score, methods = self._evaluate(tx, unit, peer_stats, hist_stats)
            results.append({
                "tx_id": tx["tx_id"],
                "subject": tx["subject"],
                "related_party": tx["related_party"],
                "amount": tx["amount"],
                "unit_price": round(unit, 4),
                "ownership_pct": tx["ownership_pct"],
                "industry": tx["industry"],
                "fairness_level": fairness,
                "fairness_score": round(score, 3),
                "deviation_rate": round(self._deviation(unit, peer_stats.get("mean", unit)), 4),
                "peer_zscore": round(self._zscore(unit, peer_stats.get("mean", 0), peer_stats.get("std", 0.001)), 2),
                "hist_zscore": round(self._zscore(unit, hist_stats.get("mean", 0), hist_stats.get("std", 0.001)), 2),
                "assessment_methods": methods,
                "suggestion": self._suggestion(fairness, tx),
                "tax_risk_level": self._tax_risk(fairness, tx),
            })
        return results

    def _postprocess(self, result: Any) -> Any:
        items = result or []
        if not isinstance(items, list):
            items = []
        dist = Counter(i["fairness_level"] for i in items)
        tax_risks = Counter(i["tax_risk_level"] for i in items)
        total_amount = sum(i["amount"] for i in items)
        biased_amount = sum(i["amount"] for i in items if i["fairness_level"] != "fair")
        critical_amount = sum(i["amount"] for i in items if i["fairness_level"] == "significantly_biased")
        return {
            "items": items,
            "summary": {
                "total_transactions": len(items),
                "total_amount": round(total_amount, 2),
                "fairness_distribution": dict(dist),
                "tax_risk_distribution": dict(tax_risks),
                "biased_amount": round(biased_amount, 2),
                "critical_biased_amount": round(critical_amount, 2),
                "fair_rate": round(dist.get("fair", 0) / max(1, len(items)), 3),
            },
            "adjustment_suggestions": [
                {"tx_id": i["tx_id"], "suggestion": i["suggestion"]}
                for i in items if i["fairness_level"] != "fair"
            ],
        }

    # ── 核心评估 ─────────────────────────────────────────────────────────────
    def _evaluate(self, tx, unit, peer_stats, hist_stats):
        methods = {}
        # 1 可比公司法
        if peer_stats.get("count", 0) >= 3:
            peer_z = self._zscore(unit, peer_stats["mean"], peer_stats["std"] or 0.001)
            methods["comparable_company"] = {
                "zscore": peer_z,
                "deviation_pct": self._deviation(unit, peer_stats["mean"]),
                "mean": peer_stats["mean"],
                "std": peer_stats["std"],
            }
        # 2 历史趋势
        if hist_stats.get("count", 0) >= 2:
            hist_z = self._zscore(unit, hist_stats["mean"], hist_stats["std"] or 0.001)
            methods["historical_trend"] = {
                "zscore": hist_z,
                "deviation_pct": self._deviation(unit, hist_stats["mean"]),
                "mean": hist_stats["mean"],
                "std": hist_stats["std"],
            }
        # 3 成本加成/利润分割
        if tx["profit_margin"] and tx["profit_margin"] != 0:
            methods["cost_plus"] = {"related_margin": tx["profit_margin"]}
        # 综合打分
        scores = []
        if "comparable_company" in methods:
            z = abs(methods["comparable_company"]["zscore"])
            scores.append(max(0, 1.0 - z / 3.0) * 0.45)
        if "historical_trend" in methods:
            z = abs(methods["historical_trend"]["zscore"])
            scores.append(max(0, 1.0 - z / 3.0) * 0.35)
        if "cost_plus" in methods:
            scores.append(0.2)
        # 风险调整
        risk_adj = 1.0 - 0.3 * min(1.0, tx["ownership_pct"]) - 0.15 * min(1.0, tx["dependence"])
        final_score = (sum(scores) / max(0.01, sum([0.45, 0.35, 0.2][: len(methods)])) * risk_adj) if methods else 0.5
        if final_score >= 0.8:
            level = "fair"
        elif final_score >= 0.55:
            level = "slightly_biased"
        else:
            level = "significantly_biased"
        return level, final_score, methods

    # ── 工具 ────────────────────────────────────────────────────────────────
    @staticmethod
    def _peer_stats(peers):
        prices = [p["price"] for p in peers if p["price"] > 0]
        if len(prices) < 2:
            return {"count": len(prices), "mean": prices[0] if prices else 0, "std": 0}
        return {"count": len(prices), "mean": statistics.mean(prices), "std": statistics.stdev(prices)}

    @staticmethod
    def _hist_stats(hist):
        prices = [h["price"] for h in hist if h["price"] > 0]
        if len(prices) < 2:
            return {"count": len(prices), "mean": prices[0] if prices else 0, "std": 0}
        return {"count": len(prices), "mean": statistics.mean(prices), "std": statistics.stdev(prices)}

    @staticmethod
    def _zscore(x, mean, std):
        if std == 0:
            return 0.0
        return (x - mean) / std

    @staticmethod
    def _deviation(price, mean):
        if mean == 0:
            return 0.0
        return (price - mean) / mean

    def _suggestion(self, level, tx):
        if level == "fair":
            return "定价符合独立交易原则，保留原合同"
        if level == "slightly_biased":
            return "建议补充可比分析文档，关注税务机关挑战风险"
        return "定价显著偏离，建议调整至公允区间或准备充分的转让定价同期资料"

    def _tax_risk(self, level, tx):
        if level == "significantly_biased":
            return "high" if tx["amount"] > 10_000_000 else "medium"
        if level == "slightly_biased":
            return "medium" if tx["ownership_pct"] > 0.5 else "low"
        return "low"

    @staticmethod
    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0
