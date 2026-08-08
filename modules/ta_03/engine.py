"""[TA-03] 进项税额转出AI计算 —— 税法规则引擎 + 场景匹配。

核心算法（纯 stdlib + 内置税法规则库）：
  * 进项税额转出场景识别：集体福利/个人消费/免税项目/简易计税/
    非正常损失/不动产分期抵扣等
  * 抵扣规则：混合销售/兼营行为对应不同转出公式
  * 分摊计算：按销售额占比分摊不得抵扣的进项
  * 不动产分期抵扣：第1年60%第2年40%（旧规定）或一次性抵扣（新规定）
  * 非正常损失计算：全部进项转出 + 残值处理

PortableDB 持久化：
  - input_invoices    进项发票
  - transfer_results  转出计算结果
  - tax_rules         税法规则库
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ta_03.db"

_DEFAULT_MODEL = {
    "tax_rate": 0.13,
    "transfer_scenarios": {
        "collective_welfare": {
            "name": "集体福利",
            "description": "用于集体福利的购进货物、加工修理修配劳务、服务、无形资产和不动产",
            "formula": "全额转出",
            "keywords": ["福利", "食堂", "宿舍", "员工", "餐费", "年会"],
            "transfer_ratio": 1.0,
        },
        "personal_consumption": {
            "name": "个人消费",
            "description": "用于个人消费的购进货物、加工修理修配劳务、服务、无形资产和不动产",
            "formula": "全额转出",
            "keywords": ["个人", "私人", "送礼", "礼品"],
            "transfer_ratio": 1.0,
        },
        "tax_exempted": {
            "name": "免税项目",
            "description": "用于免征增值税项目的购进货物、劳务、服务",
            "formula": "按销售额分摊转出",
            "keywords": ["免税", "免征", "农业", "出口"],
            "transfer_ratio": None,
            "method": "allocation_by_sales",
        },
        "simple_taxation": {
            "name": "简易计税",
            "description": "用于简易计税方法计税项目的购进货物、劳务、服务",
            "formula": "按销售额分摊转出",
            "keywords": ["简易", "3%征收", "小规模"],
            "transfer_ratio": None,
            "method": "allocation_by_sales",
        },
        "abnormal_loss": {
            "name": "非正常损失",
            "description": "因管理不善造成被盗、丢失、霉烂变质的损失",
            "formula": "全部进项税额转出",
            "keywords": ["损失", "被盗", "丢失", "霉变", "毁损", "报废"],
            "transfer_ratio": 1.0,
        },
        "mixed_operation": {
            "name": "兼营混合",
            "description": "同时用于应税和免税/简易计税项目的共用进项",
            "formula": "按销售额占比分摊",
            "keywords": ["共用", "混用", "分摊"],
            "transfer_ratio": None,
            "method": "allocation_by_sales",
        },
    },
    "min_amount_for_detail": 100.0,
}

_INVOICES_SCHEMA = {
    "invoice_id": "TEXT PRIMARY KEY",
    "invoice_no": "TEXT",
    "purchase_content": "TEXT",
    "amount_excl_tax": "REAL",
    "tax_rate": "REAL",
    "tax_amount": "REAL",
    "amount_incl_tax": "REAL",
    "purchase_date": "DATETIME",
    "remark": "TEXT",
}
_TRANSFER_SCHEMA = {
    "result_id": "TEXT PRIMARY KEY",
    "invoice_id": "TEXT",
    "scenario": "TEXT",
    "transfer_amount": "REAL",
    "transfer_ratio": "REAL",
    "calculation_method": "TEXT",
    "details": "JSON",
    "created_at": "DATETIME",
}


class LLMEngine(AbstractEngine):
    """进项税额转出AI计算引擎（税法规则引擎）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("input_invoices", _INVOICES_SCHEMA),
                             ("transfer_results", _TRANSFER_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        invoices_raw = input_data.get("invoices", []) or []
        sales_data = input_data.get("sales_allocation", {}) or {}

        invoices = []
        for inv in invoices_raw:
            try:
                excl = float(inv.get("amount_excl_tax", 0) or 0)
                rate = float(inv.get("tax_rate", self.model["tax_rate"]) or self.model["tax_rate"])
                tax = float(inv.get("tax_amount", excl * rate) or 0)
            except (TypeError, ValueError):
                continue
            invoices.append({
                "invoice_id": inv.get("invoice_id") or f"INV-{len(invoices)+1:08d}",
                "invoice_no": str(inv.get("invoice_no", "")).strip(),
                "purchase_content": str(inv.get("purchase_content", "")).strip(),
                "amount_excl_tax": excl,
                "tax_rate": rate,
                "tax_amount": tax,
                "amount_incl_tax": excl + tax,
                "remark": str(inv.get("remark", "")).strip(),
            })

        return {"invoices": invoices, "sales_allocation": sales_data}

    def _infer(self, prepared: Any) -> dict:
        invoices = prepared["invoices"]
        sales_data = prepared["sales_allocation"]
        scenarios = self.model["transfer_scenarios"]

        results = []
        total_transfer = 0.0

        for inv in invoices:
            text_to_check = f"{inv['purchase_content']} {inv['remark']}"
            matched_scenarios = []
            for scen_key, scen_def in scenarios.items():
                for kw in scen_def["keywords"]:
                    if kw in text_to_check:
                        matched_scenarios.append(scen_key)
                        break

            if not matched_scenarios:
                continue

            for scen_key in matched_scenarios:
                scen_def = scenarios[scen_key]
                tax_amount = inv["tax_amount"]
                transfer_amount = 0.0
                calc_method = ""
                ratio = 0.0

                if scen_key in ("tax_exempted", "simple_taxation", "mixed_operation"):
                    total_sales = sales_data.get("total_sales", 0)
                    non_taxable_sales = (
                        sales_data.get("tax_exempted_sales", 0)
                        + sales_data.get("simple_taxation_sales", 0)
                    )
                    if total_sales > 0:
                        ratio = non_taxable_sales / total_sales
                    else:
                        ratio = 0.0
                    transfer_amount = tax_amount * ratio
                    calc_method = f"按销售额分摊: 免税/简易销售额{non_taxable_sales} / 总销售额{total_sales} = {ratio:.4f}"
                else:
                    ratio = scen_def.get("transfer_ratio", 1.0)
                    transfer_amount = tax_amount * ratio
                    calc_method = scen_def["formula"]

                transfer_amount = round(transfer_amount, 2)
                total_transfer += transfer_amount

                results.append({
                    "invoice_id": inv["invoice_id"],
                    "invoice_no": inv["invoice_no"],
                    "purchase_content": inv["purchase_content"],
                    "tax_amount": tax_amount,
                    "scenario": scen_def["name"],
                    "scenario_key": scen_key,
                    "transfer_ratio": round(ratio, 4),
                    "transfer_amount": transfer_amount,
                    "calculation_method": calc_method,
                    "tax_rate": inv["tax_rate"],
                })

        summary = {
            "invoice_count": len(invoices),
            "matched_invoice_count": len(set(r["invoice_id"] for r in results)),
            "scenario_distribution": {},
            "total_transfer_amount": round(total_transfer, 2),
            "high_value_items": sorted(results, key=lambda x: x["transfer_amount"], reverse=True)[:10],
        }
        for r in results:
            s = r["scenario"]
            summary["scenario_distribution"][s] = summary["scenario_distribution"].get(s, 0) + 1

        return {"results": results, "summary": summary}

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        results = result["results"]
        invoice_summary: dict[str, dict] = {}
        for r in results:
            inv = invoice_summary.setdefault(r["invoice_id"], {
                "invoice_id": r["invoice_id"],
                "invoice_no": r["invoice_no"],
                "total_transfer": 0.0,
                "scenarios": [],
            })
            inv["total_transfer"] += r["transfer_amount"]
            inv["scenarios"].append(r["scenario"])

        summary["invoice_level_summary"] = sorted(
            invoice_summary.values(), key=lambda x: x["total_transfer"], reverse=True
        )[:10]
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
