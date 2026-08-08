"""[TA-02] 发票四单自动匹配引擎 —— 多维度相似度加权匹配。

核心算法（纯 stdlib）：
  * 四单：采购订单/入库单/发票/付款单
  * 字段相似度：
    - 数值字段：容差匹配（±threshold）+ 相对偏差
    - 文本字段：Jaccard 系数 + 编辑距离（difflib）
    - 日期字段：天数差值归一化
  * 加权综合评分 + 匹配置信度
  * 贪心 / 匈牙利式最佳匹配

PortableDB 持久化：
  - order_orders     采购订单
  - order_receipts   入库单
  - invoices         发票
  - payments         付款单
  - match_results    匹配结果
"""
from __future__ import annotations

import difflib
from collections import defaultdict
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ta_02.db"

_DEFAULT_MODEL = {
    "field_weights": {
        "amount_incl_tax": 0.35,
        "amount_excl_tax": 0.20,
        "supplier_name": 0.20,
        "tax_amount": 0.10,
        "date_proximity": 0.10,
        "quantity": 0.05,
    },
    "tolerances": {
        "amount_incl_tax": 0.02,
        "amount_excl_tax": 0.02,
        "tax_amount": 0.05,
        "quantity": 0.05,
    },
    "max_date_diff_days": 30,
    "match_threshold": 0.7,
}

_ORDERS_SCHEMA = {
    "order_id": "TEXT PRIMARY KEY",
    "order_no": "TEXT",
    "supplier_name": "TEXT",
    "amount_incl_tax": "REAL",
    "amount_excl_tax": "REAL",
    "tax_amount": "REAL",
    "quantity": "REAL",
    "order_date": "DATETIME",
}
_MATCH_SCHEMA = {
    "match_id": "TEXT PRIMARY KEY",
    "invoice_id": "TEXT",
    "order_id": "TEXT",
    "receipt_id": "TEXT",
    "payment_id": "TEXT",
    "confidence": "REAL",
    "match_details": "JSON",
    "matched_at": "DATETIME",
}


class MLEngine(AbstractEngine):
    """发票四单自动匹配引擎（多维度加权相似度）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("purchase_orders", _ORDERS_SCHEMA),
                             ("receipts", _ORDERS_SCHEMA),
                             ("invoices", _ORDERS_SCHEMA),
                             ("payments", _ORDERS_SCHEMA),
                             ("match_results", _MATCH_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        def clean_list(key):
            items = input_data.get(key, []) or []
            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    result.append({
                        "id": item.get("id") or item.get(f"{key[:-1]}_id") or f"{key.upper()}-{len(result)+1:08d}",
                        "supplier_name": str(item.get("supplier_name", "")).strip(),
                        "amount_incl_tax": float(item.get("amount_incl_tax", 0) or 0),
                        "amount_excl_tax": float(item.get("amount_excl_tax", 0) or 0),
                        "tax_amount": float(item.get("tax_amount", 0) or 0),
                        "quantity": float(item.get("quantity", 0) or 0),
                        "date": item.get("date") or item.get("order_date") or item.get("invoice_date") or item.get("payment_date") or "",
                    })
                except (TypeError, ValueError):
                    continue
            return result

        return {
            "invoices": clean_list("invoices"),
            "orders": clean_list("orders"),
            "receipts": clean_list("receipts"),
            "payments": clean_list("payments"),
        }

    def _infer(self, prepared: Any) -> dict:
        invoices = prepared["invoices"]
        orders = prepared["orders"]
        receipts = prepared["receipts"]
        payments = prepared["payments"]
        weights = self.model["field_weights"]
        tolerances = self.model["tolerances"]
        max_days = self.model["max_date_diff_days"]
        threshold = self.model["match_threshold"]

        matches = []

        for inv in invoices:
            inv_matches = {
                "invoice_id": inv["id"],
                "order_match": self._best_match(inv, orders, weights, tolerances, max_days, threshold),
                "receipt_match": self._best_match(inv, receipts, weights, tolerances, max_days, threshold),
                "payment_match": self._best_match(inv, payments, weights, tolerances, max_days, threshold),
            }

            matched_count = sum(1 for v in inv_matches.values()
                                if isinstance(v, dict) and v.get("matched"))
            confidence_scores = [v["score"] for v in inv_matches.values()
                                 if isinstance(v, dict) and v.get("matched")]
            overall_confidence = sum(confidence_scores) / max(len(confidence_scores), 1) if confidence_scores else 0.0

            status = "四单齐全" if matched_count == 3 else (
                "部分匹配" if matched_count > 0 else "未匹配"
            )

            matches.append({
                "invoice_id": inv["id"],
                "supplier_name": inv["supplier_name"],
                "amount_incl_tax": inv["amount_incl_tax"],
                "matches": inv_matches,
                "matched_orders": matched_count,
                "overall_confidence": round(overall_confidence, 4),
                "status": status,
            })

        summary = {
            "invoice_count": len(invoices),
            "fully_matched": sum(1 for m in matches if m["status"] == "四单齐全"),
            "partially_matched": sum(1 for m in matches if m["status"] == "部分匹配"),
            "unmatched": sum(1 for m in matches if m["status"] == "未匹配"),
            "avg_confidence": round(
                sum(m["overall_confidence"] for m in matches) / max(len(matches), 1), 4
            ),
        }
        return {"matches": matches, "summary": summary}

    def _best_match(self, target: dict, candidates: list[dict],
                    weights: dict, tolerances: dict, max_days: int,
                    threshold: float) -> dict:
        if not candidates:
            return {"matched": False, "reason": "无候选"}

        best = None
        best_score = 0.0
        for c in candidates:
            score = self._compute_similarity(target, c, weights, tolerances, max_days)
            if score > best_score:
                best_score = score
                best = c

        if best and best_score >= threshold:
            return {
                "matched": True,
                "target_id": best["id"],
                "score": round(best_score, 4),
                "supplier": best["supplier_name"],
            }
        return {"matched": False, "best_score": round(best_score, 4) if best else 0.0}

    def _compute_similarity(self, a: dict, b: dict, weights: dict,
                            tolerances: dict, max_days: int) -> float:
        total_weight = 0.0
        score = 0.0

        amount_w = weights.get("amount_incl_tax", 0.35)
        if a["amount_incl_tax"] > 0 and b["amount_incl_tax"] > 0:
            tol = tolerances.get("amount_incl_tax", 0.02)
            diff = abs(a["amount_incl_tax"] - b["amount_incl_tax"]) / max(a["amount_incl_tax"], 1e-9)
            amount_sim = max(0.0, 1.0 - diff / max(tol * 2, 0.01))
            score += amount_w * amount_sim
            total_weight += amount_w

        excl_w = weights.get("amount_excl_tax", 0.20)
        if excl_w > 0 and a["amount_excl_tax"] > 0 and b["amount_excl_tax"] > 0:
            tol = tolerances.get("amount_excl_tax", 0.02)
            diff = abs(a["amount_excl_tax"] - b["amount_excl_tax"]) / max(a["amount_excl_tax"], 1e-9)
            excl_sim = max(0.0, 1.0 - diff / max(tol * 2, 0.01))
            score += excl_w * excl_sim
            total_weight += excl_w

        supplier_w = weights.get("supplier_name", 0.20)
        if supplier_w > 0:
            a_name = a["supplier_name"]
            b_name = b["supplier_name"]
            if a_name and b_name:
                ratio = difflib.SequenceMatcher(None, a_name, b_name).ratio()
                score += supplier_w * ratio
            else:
                score += supplier_w * 0.0
            total_weight += supplier_w

        tax_w = weights.get("tax_amount", 0.10)
        if tax_w > 0 and a["tax_amount"] > 0 and b["tax_amount"] > 0:
            tol = tolerances.get("tax_amount", 0.05)
            diff = abs(a["tax_amount"] - b["tax_amount"]) / max(a["tax_amount"], 1e-9)
            tax_sim = max(0.0, 1.0 - diff / max(tol * 2, 0.01))
            score += tax_w * tax_sim
            total_weight += tax_w

        date_w = weights.get("date_proximity", 0.10)
        if date_w > 0 and a.get("date") and b.get("date"):
            try:
                from datetime import datetime
                da = datetime.fromisoformat(str(a["date"]).replace("Z", "+00:00").split("+")[0].strip())
                db_ = datetime.fromisoformat(str(b["date"]).replace("Z", "+00:00").split("+")[0].strip())
                day_diff = abs((da - db_).days)
                date_sim = max(0.0, 1.0 - day_diff / max(max_days, 1))
                score += date_w * date_sim
            except (ValueError, AttributeError, TypeError):
                pass
            total_weight += date_w

        qty_w = weights.get("quantity", 0.05)
        if qty_w > 0 and a["quantity"] > 0 and b["quantity"] > 0:
            tol = tolerances.get("quantity", 0.05)
            diff = abs(a["quantity"] - b["quantity"]) / max(a["quantity"], 1e-9)
            qty_sim = max(0.0, 1.0 - diff / max(tol * 2, 0.01))
            score += qty_w * qty_sim
            total_weight += qty_w

        return score / max(total_weight, 0.01)

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        fully = [m for m in result["matches"] if m["status"] == "四单齐全"]
        partial = [m for m in result["matches"] if m["status"] == "部分匹配"]
        summary["high_confidence"] = [
            {"invoice_id": m["invoice_id"], "confidence": m["overall_confidence"],
             "matched_orders": m["matched_orders"]}
            for m in sorted(result["matches"], key=lambda x: x["overall_confidence"], reverse=True)[:10]
        ]
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
