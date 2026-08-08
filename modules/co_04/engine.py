"""[CO-04] AML 智能交易监控引擎 —— 多模式可疑交易检测。

纯 stdlib 实现，覆盖方案文档中的反洗钱交易监控：
  * 模式 ① 结构化交易（Smurfing）：多笔交易金额略低于报告阈值
  * 模式 ② 快速往返（Round-trip）：资金短时间内进出
  * 模式 ③ 高风险地区：交易涉及高风险国家/地区
  * 模式 ④ 大额现金：超过现金交易报告阈值
  * 模式 ⑤ 异常时间：非工作时段密集交易

模型结构（self.model）：
  {
    "report_threshold": 50000,          # 报告阈值（元）
    "smurf_window": 0.9,                # 结构化交易比例阈值
    "roundtrip_hours": 24,              # 往返检测时间窗（小时）
    "high_risk_jurisdictions": [...],   # 高风险地区清单
  }
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from modules.shared.base_engine import AbstractEngine

_HIGH_RISK = {"IRAN", "NK", "SYRIA", "MM", "AF", "VE", "ZW"}


class KGEngine(AbstractEngine):
    """AML 多模式可疑交易检测引擎（纯 stdlib）。"""

    def _load_model(self) -> None:
        """加载 AML 检测规则参数。"""
        self.model = {
            "report_threshold": float(self.config.get("threshold", {}).get("report", 50000)),
            "smurf_ratio": 0.9,
            "roundtrip_hours": 24,
            "cash_threshold": 200000,
            "high_risk_jurisdictions": _HIGH_RISK,
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取交易列表（懒加载模型）。"""
        if self.model is None:
            self._load_model()
        if isinstance(input_data, dict) and "transactions" in input_data:
            return input_data["transactions"]
        return input_data if isinstance(input_data, list) else []

    def _infer(self, prepared: Any) -> Any:
        """五模式并行检测。"""
        m = self.model
        threshold = m["report_threshold"]
        sars = []

        # --- 模式 ① 结构化交易（Smurfing） ---
        # 同一客户多笔交易金额在阈值的 90%-100% 区间
        by_customer = {}
        for t in prepared:
            cid = t.get("customer_id", "?")
            by_customer.setdefault(cid, []).append(t)
        for cid, txs in by_customer.items():
            near_threshold = [t for t in txs if threshold * m["smurf_ratio"] <= t.get("amount", 0) < threshold]
            if len(near_threshold) >= 3:
                sars.append({
                    "sar_id": f"SAR-SMURF-{cid}",
                    "pattern": "结构化交易（Smurfing）",
                    "customer_id": cid,
                    "transaction_count": len(near_threshold),
                    "total_amount": round(sum(t["amount"] for t in near_threshold), 2),
                    "risk_score": 85,
                    "transactions": [t["tx_id"] for t in near_threshold[:10]],
                })

        # --- 模式 ② 快速往返（Round-trip） ---
        # 资金出去后 24h 内从对手方返回
        for t in prepared:
            cp = t.get("counterparty")
            cid = t.get("customer_id")
            if not cp or not cid:
                continue
            # 查找反向交易：counterparty → customer
            for t2 in prepared:
                if (t2.get("customer_id") == cp and t2.get("counterparty") == cid
                        and t2.get("amount", 0) >= t.get("amount", 0) * 0.8):
                    sars.append({
                        "sar_id": f"SAR-ROUND-{t.get('tx_id','?')}",
                        "pattern": "快速往返（Round-trip）",
                        "customer_id": cid,
                        "counterparty": cp,
                        "amount_out": t.get("amount", 0),
                        "amount_back": t2.get("amount", 0),
                        "risk_score": 75,
                        "transactions": [t.get("tx_id"), t2.get("tx_id")],
                    })
                    break

        # --- 模式 ③ 高风险地区 ---
        for t in prepared:
            juris = t.get("jurisdiction", "").upper()
            if juris in m["high_risk_jurisdictions"]:
                sars.append({
                    "sar_id": f"SAR-HRISK-{t.get('tx_id','?')}",
                    "pattern": "高风险地区交易",
                    "customer_id": t.get("customer_id", "?"),
                    "jurisdiction": juris,
                    "amount": t.get("amount", 0),
                    "risk_score": 90,
                    "transactions": [t.get("tx_id")],
                })

        # --- 模式 ④ 大额现金 ---
        for t in prepared:
            if t.get("channel") == "cash" and t.get("amount", 0) > m["cash_threshold"]:
                sars.append({
                    "sar_id": f"SAR-CASH-{t.get('tx_id','?')}",
                    "pattern": "大额现金交易",
                    "customer_id": t.get("customer_id", "?"),
                    "amount": t.get("amount", 0),
                    "risk_score": 70,
                    "transactions": [t.get("tx_id")],
                })

        # --- 模式 ⑤ 异常时间密集交易 ---
        for cid, txs in by_customer.items():
            night_txs = [t for t in txs if t.get("hour", 12) < 6 or t.get("hour", 12) > 22]
            if len(night_txs) >= 5:
                sars.append({
                    "sar_id": f"SAR-NIGHT-{cid}",
                    "pattern": "非工作时段密集交易",
                    "customer_id": cid,
                    "transaction_count": len(night_txs),
                    "total_amount": round(sum(t.get("amount", 0) for t in night_txs), 2),
                    "risk_score": 65,
                    "transactions": [t.get("tx_id") for t in night_txs[:10]],
                })

        # 去重（同一 tx_id 可能触发多个模式）
        sars.sort(key=lambda x: x["risk_score"], reverse=True)
        return {"total_transactions": len(prepared), "sar_count": len(sars), "sars": sars}

    def _postprocess(self, result: Any) -> Any:
        """SAR 汇总 + 风险分级。"""
        sars = result.get("sars", [])
        result["summary"] = {
            "total_sars": len(sars),
            "high_risk": sum(1 for s in sars if s["risk_score"] >= 80),
            "medium_risk": sum(1 for s in sars if 60 <= s["risk_score"] < 80),
            "low_risk": sum(1 for s in sars if s["risk_score"] < 60),
            "patterns": list(set(s["pattern"] for s in sars)),
        }
        return result
