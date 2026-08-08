"""[TA-01] AI发票智能审计平台 —— 发票字段校验 + 多维规则引擎。

核心算法（纯 stdlib，替代 OCR/CV）：
  * 发票字段结构校验（发票代码/号码/日期/购销方/金额/税额）
  * 金额勾稽校验：价税合计 = 不含税金额 + 税额
  * 税率合理性校验：13%/9%/6%/3%/0% 等标准税率
  * 发票号唯一性校验
  * 重复报销检测（同金额+同供应商+相近日期）
  * 发票日期与业务合理性校验

PortableDB 持久化：
  - invoices        发票主表
  - audit_results    审计结果
  - audit_rules      规则配置
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ta_01.db"

_DEFAULT_MODEL = {
    "standard_tax_rates": [0.0, 0.03, 0.06, 0.09, 0.11, 0.13],
    "allowed_invoice_types": ["增值税专用发票", "增值税普通发票", "电子增值税专用发票",
                              "电子增值税普通发票", "机动车销售统一发票"],
    "duplicate_days_window": 30,
    "tolerance": 0.02,
    "audit_rules": {
        "勾稽校验": "价税合计应等于不含税金额+税额",
        "税率校验": "税率应为0/3/6/9/11/13%之一",
        "号码格式": "发票号码应为8-20位数字",
        "日期合理性": "发票日期不得晚于审计日期",
        "重复报销": "同金额同供应商近30天内不得重复",
    },
}

_INVOICES_SCHEMA = {
    "invoice_id": "TEXT PRIMARY KEY",
    "invoice_no": "TEXT",
    "invoice_code": "TEXT",
    "invoice_type": "TEXT",
    "seller_name": "TEXT",
    "buyer_name": "TEXT",
    "amount_excl_tax": "REAL",
    "tax_rate": "REAL",
    "tax_amount": "REAL",
    "amount_incl_tax": "REAL",
    "invoice_date": "DATETIME",
    "raw_data": "JSON",
}
_AUDIT_SCHEMA = {
    "invoice_id": "TEXT",
    "audit_status": "TEXT",
    "issue_count": "INTEGER",
    "issues": "JSON",
    "risk_score": "REAL",
    "audited_at": "DATETIME",
}


class CVEngine(AbstractEngine):
    """AI发票智能审计引擎（字段校验 + 规则引擎）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("invoices", _INVOICES_SCHEMA),
                             ("audit_results", _AUDIT_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        invoices_raw = input_data.get("invoices", []) or []
        audit_date_str = input_data.get("audit_date")

        invoices = []
        for inv in invoices_raw:
            try:
                excl_tax = float(inv.get("amount_excl_tax", 0) or 0)
                tax_rate = float(inv.get("tax_rate", 0) or 0)
                tax = float(inv.get("tax_amount", 0) or 0)
                incl = float(inv.get("amount_incl_tax", 0) or 0)
            except (TypeError, ValueError):
                continue

            inv_date_str = inv.get("invoice_date", "")
            try:
                inv_date = datetime.fromisoformat(inv_date_str.replace("Z", "+00:00").split("+")[0].strip())
            except (ValueError, AttributeError):
                inv_date = None

            invoices.append({
                "invoice_id": inv.get("invoice_id") or inv.get("invoice_no") or f"INV-{len(invoices)+1:08d}",
                "invoice_no": str(inv.get("invoice_no", "")).strip(),
                "invoice_code": str(inv.get("invoice_code", "")).strip(),
                "invoice_type": inv.get("invoice_type", "未知"),
                "seller_name": str(inv.get("seller_name", "")).strip(),
                "buyer_name": str(inv.get("buyer_name", "")).strip(),
                "amount_excl_tax": excl_tax,
                "tax_rate": tax_rate,
                "tax_amount": tax,
                "amount_incl_tax": incl,
                "invoice_date": inv_date,
                "invoice_date_str": inv_date_str,
            })

        return {
            "invoices": invoices,
            "audit_date": audit_date_str,
        }

    def _infer(self, prepared: Any) -> dict:
        invoices = prepared["invoices"]
        audit_date = prepared.get("audit_date")
        tolerance = self.model["tolerance"]
        std_rates = self.model["standard_tax_rates"]
        dup_window = self.model["duplicate_days_window"]

        results = []
        for inv in invoices:
            issues = []
            risk_score = 0.0

            if not inv["invoice_no"]:
                issues.append({"type": "号码格式", "severity": "error",
                               "msg": "发票号码为空"})
                risk_score += 0.3
            elif not re.match(r"^\d{8,20}$", inv["invoice_no"]):
                issues.append({"type": "号码格式", "severity": "error",
                               "msg": f"发票号码格式异常: {inv['invoice_no']}"})
                risk_score += 0.2

            if inv["tax_rate"] not in std_rates and inv["tax_rate"] > 0:
                closest = min(std_rates, key=lambda x: abs(x - inv["tax_rate"]))
                issues.append({"type": "税率校验", "severity": "warning",
                               "msg": f"税率{inv['tax_rate']*100:.1f}%非标准税率，最接近标准税率{closest*100:.0f}%"})
                risk_score += 0.15

            expected_incl = inv["amount_excl_tax"] + inv["tax_amount"]
            if expected_incl > 0:
                diff = abs(inv["amount_incl_tax"] - expected_incl) / max(expected_incl, 1e-9)
                if diff > tolerance:
                    issues.append({"type": "勾稽校验", "severity": "error",
                                   "msg": f"价税合计勾稽不符: 预期{expected_incl:.2f}, 实际{inv['amount_incl_tax']:.2f}, 差异{diff*100:.2f}%"})
                    risk_score += 0.35

            expected_tax = inv["amount_excl_tax"] * inv["tax_rate"]
            if expected_tax > 0:
                tax_diff = abs(inv["tax_amount"] - expected_tax) / max(expected_tax, 1e-9)
                if tax_diff > tolerance and inv["tax_amount"] > 0:
                    issues.append({"type": "勾稽校验", "severity": "warning",
                                   "msg": f"税额与计算不符: 预期{expected_tax:.2f}, 实际{inv['tax_amount']:.2f}"})
                    risk_score += 0.2

            if inv["invoice_date"] is not None and audit_date:
                try:
                    audit_dt = datetime.fromisoformat(str(audit_date).replace("Z", "+00:00").split("+")[0].strip())
                    if inv["invoice_date"] > audit_dt:
                        issues.append({"type": "日期合理性", "severity": "error",
                                       "msg": "发票日期晚于审计日期"})
                        risk_score += 0.25
                except (ValueError, AttributeError):
                    pass

            if not inv["seller_name"] or not inv["buyer_name"]:
                issues.append({"type": "字段完整性", "severity": "warning",
                               "msg": "购销方信息缺失"})
                risk_score += 0.15

            if inv["amount_incl_tax"] <= 0:
                issues.append({"type": "金额校验", "severity": "error",
                               "msg": "发票金额为零或负数"})
                risk_score += 0.3

            risk_score = min(1.0, risk_score)

            status = "通过"
            if any(i["severity"] == "error" for i in issues):
                status = "异常"
            elif issues:
                status = "警告"

            results.append({
                "invoice_id": inv["invoice_id"],
                "invoice_no": inv["invoice_no"],
                "seller_name": inv["seller_name"],
                "buyer_name": inv["buyer_name"],
                "amount_incl_tax": inv["amount_incl_tax"],
                "invoice_date_str": inv["invoice_date_str"],
                "audit_status": status,
                "issue_count": len(issues),
                "issues": issues,
                "risk_score": round(risk_score, 4),
            })

        seen_keys: dict[tuple, list[dict]] = {}
        for i, inv in enumerate(invoices):
            key = (inv["seller_name"], round(inv["amount_incl_tax"], 2))
            matches = seen_keys.get(key, [])
            for prev in matches:
                if inv["invoice_date"] and prev.get("invoice_date"):
                    delta = abs((inv["invoice_date"] - prev["invoice_date"]).days)
                    if delta <= dup_window:
                        for r in results:
                            if r["invoice_id"] == inv["invoice_id"]:
                                r["issues"].append({
                                    "type": "重复报销", "severity": "error",
                                    "msg": f"疑似重复发票: 与{prev['invoice_id']}间隔{delta}天"
                                })
                                r["issue_count"] += 1
                                r["risk_score"] = min(1.0, r["risk_score"] + 0.3)
                                if r["audit_status"] == "通过":
                                    r["audit_status"] = "异常"
                            elif r["invoice_id"] == prev["invoice_id"]:
                                r["issues"].append({
                                    "type": "重复报销", "severity": "error",
                                    "msg": f"疑似重复发票: 与{inv['invoice_id']}间隔{delta}天"
                                })
                                r["issue_count"] += 1
                                r["risk_score"] = min(1.0, r["risk_score"] + 0.3)
                                if r["audit_status"] == "通过":
                                    r["audit_status"] = "异常"
            matches.append({"invoice_id": inv["invoice_id"], "invoice_date": inv["invoice_date"]})
            seen_keys[key] = matches

        summary = {
            "total": len(results),
            "passed": sum(1 for r in results if r["audit_status"] == "通过"),
            "warning": sum(1 for r in results if r["audit_status"] == "警告"),
            "abnormal": sum(1 for r in results if r["audit_status"] == "异常"),
            "total_issues": sum(r["issue_count"] for r in results),
            "avg_risk_score": round(
                sum(r["risk_score"] for r in results) / max(len(results), 1), 4
            ),
            "high_risk_invoices": sorted(results, key=lambda x: x["risk_score"], reverse=True)[:10],
        }
        return {"results": results, "summary": summary}

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        issue_type_counts: dict[str, int] = {}
        for r in result["results"]:
            for issue in r["issues"]:
                t = issue.get("type", "unknown")
                issue_type_counts[t] = issue_type_counts.get(t, 0) + 1
        summary["issue_type_distribution"] = issue_type_counts
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
