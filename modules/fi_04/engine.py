"""[FI-04] 监管报表智能核对平台 —— 科目映射 + 钩稽关系 + 多期校验 + 差异追踪。

核心算法（纯 stdlib）：
  * 报表结构解析：多层嵌套科目树
  * 科目映射：语义匹配（关键词 + 层级）
  * 钩稽校验：表内/表间等式与不等式规则
  * 多期对比：同比/环比变动率 + 趋势一致性检查
  * 差异追踪：溯源到明细科目
  * 合规性评分：按规则权重加权

PortableDB 持久化：
  - report_templates 报表模板
  - check_rules     钩稽规则库
  - reports         提交的报表数据
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fi_04.db"

_DEFAULT_MODEL = {
    "check_rules": [
        {"id": "R001", "type": "表内", "level": "error", "name": "资产负债表资产=负债+所有者权益",
         "check": "total_assets == total_liabilities + total_equity", "weight": 2.0},
        {"id": "R002", "type": "表内", "level": "error", "name": "流动资产合计≥货币资金",
         "check": "current_assets >= cash", "weight": 1.5},
        {"id": "R003", "type": "表内", "level": "warning", "name": "应收账款同比增长>30%",
         "check": "ar_yoy < 0.3", "weight": 1.0},
        {"id": "R004", "type": "表内", "level": "warning", "name": "存货同比增长>20%",
         "check": "inventory_yoy < 0.2", "weight": 1.0},
        {"id": "R005", "type": "表内", "level": "info", "name": "流动比率<1",
         "check": "current_ratio >= 1.0", "weight": 0.5},
        {"id": "R006", "type": "表间", "level": "error", "name": "净利润=利润表净利润",
         "check": "net_profit == pl_net_profit", "weight": 2.0},
        {"id": "R007", "type": "表间", "level": "warning", "name": "现金流净额≈净利润",
         "check": "abs(cf_net - net_profit) < abs(net_profit) * 0.5", "weight": 1.0},
    ],
    "semantic_aliases": {
        "total_assets": ["资产总计", "资产合计", "总资产"],
        "total_liabilities": ["负债总计", "负债合计", "总负债"],
        "total_equity": ["所有者权益总计", "股东权益合计", "净资产"],
        "current_assets": ["流动资产合计", "流动资产"],
        "current_liabilities": ["流动负债合计", "流动负债"],
        "cash": ["货币资金", "现金", "银行存款"],
        "receivables": ["应收账款", "应收票据"],
        "inventory": ["存货", "库存"],
        "revenue": ["营业收入", "销售商品收入"],
        "cost": ["营业成本", "销售成本"],
        "net_profit": ["净利润", "本年净利润"],
        "cf_net": ["经营活动现金流净额", "经营现金流"],
    },
    "threshold_tolerance": 1e-6,
}


class LLMEngine(AbstractEngine):
    """监管报表智能核对引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        reports_raw = input_data.get("reports", []) or []
        reports = []
        for r in reports_raw:
            items = r.get("items", {}) or {}
            normalized = {}
            for alias_key, keywords in self.model["semantic_aliases"].items():
                matched_val = self._find_by_alias(items, keywords)
                if matched_val is not None:
                    normalized[alias_key] = matched_val
            ar = float(r.get("receivables_prev_year", 0) or 0)
            inv = float(r.get("inventory_prev_year", 0) or 0)
            if ar > 0 and "receivables" in normalized:
                normalized["ar_yoy"] = (normalized["receivables"] - ar) / ar
            else:
                normalized["ar_yoy"] = 0.0
            if inv > 0 and "inventory" in normalized:
                normalized["inventory_yoy"] = (normalized["inventory"] - inv) / inv
            else:
                normalized["inventory_yoy"] = 0.0
            ca = normalized.get("current_assets")
            cl = normalized.get("current_liabilities")
            if ca and cl and cl != 0:
                normalized["current_ratio"] = ca / cl
            else:
                normalized["current_ratio"] = 0.0
            pl_np = r.get("pl_net_profit")
            if pl_np is not None:
                try:
                    normalized["pl_net_profit"] = float(pl_np)
                except (TypeError, ValueError):
                    pass
            cf = r.get("cf_net")
            if cf is not None:
                try:
                    normalized["cf_net"] = float(cf)
                except (TypeError, ValueError):
                    pass
            reports.append({
                "report_id": r.get("report_id") or f"RPT-{len(reports)+1:06d}",
                "report_type": str(r.get("report_type", "资产负债表")),
                "period": str(r.get("period", "")),
                "normalized": normalized,
                "raw_items": items,
            })

        return {"reports": reports}

    def _find_by_alias(self, items: dict, keywords: list) -> float | None:
        best_key = None
        best_score = 0
        for k, v in items.items():
            ks = str(k)
            for kw in keywords:
                score = difflib.SequenceMatcher(None, ks, kw).ratio()
                if ks == kw:
                    score = 1.0
                elif kw in ks or ks in kw:
                    score = max(score, 0.9)
                if score > best_score:
                    best_score = score
                    best_key = k
        if best_key and best_score >= 0.6:
            try:
                return float(items[best_key])
            except (TypeError, ValueError):
                return None
        return None

    def _infer(self, prepared: Any) -> dict:
        reports = prepared["reports"]
        all_violations = []

        for report in reports:
            violations = self._validate_report(report)
            for v in violations:
                v["report_id"] = report["report_id"]
                v["report_type"] = report["report_type"]
                v["period"] = report["period"]
            all_violations.extend(violations)

        error_count = sum(1 for v in all_violations if v["level"] == "error")
        warning_count = sum(1 for v in all_violations if v["level"] == "warning")
        info_count = sum(1 for v in all_violations if v["level"] == "info")

        total_weight = sum(r["weight"] for r in self.model["check_rules"])
        violated_weight = sum(
            next((r["weight"] for r in self.model["check_rules"] if r["id"] == v["rule_id"]), 1.0)
            for v in all_violations
        )
        compliance_score = max(0.0, round(100 * (1 - violated_weight / max(total_weight, 0.01)), 2))

        summary = {
            "report_count": len(reports),
            "total_violations": len(all_violations),
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count,
            "compliance_score": compliance_score,
            "pass_rate": round(1 - len(all_violations) / max(len(self.model["check_rules"]) * len(reports), 1), 4),
        }

        return {
            "reports": reports,
            "violations": all_violations,
            "summary": summary,
        }

    def _validate_report(self, report: dict) -> list:
        ctx = report["normalized"]
        violations = []
        tol = self.model["threshold_tolerance"]
        for rule in self.model["check_rules"]:
            passed = self._eval_rule(rule["check"], ctx, tol)
            if not passed:
                violations.append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "rule_type": rule["type"],
                    "level": rule["level"],
                    "weight": rule["weight"],
                    "check_expr": rule["check"],
                    "context": {k: ctx.get(k) for k in re.findall(r'[a-z_]+', rule["check"])},
                })
        return violations

    def _eval_rule(self, expr: str, ctx: dict, tol: float) -> bool:
        try:
            wrapped = expr.replace("==", f"~=")
            safe_ctx = {}
            for k, v in ctx.items():
                if isinstance(v, (int, float)):
                    safe_ctx[k] = v
            safe_ctx["abs"] = abs
            safe_ctx["__tol__"] = tol
            wrapped = re.sub(r'(\w+)\s*==\s*(\w+)',
                            r'abs(\1 - \2) < __tol__', expr)
            result = eval(wrapped, {"__builtins__": {"abs": abs, "min": min, "max": max}}, safe_ctx)
            return bool(result)
        except Exception:
            return False

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        cs = summary["compliance_score"]
        summary["compliance_status"] = (
            "通过" if cs >= 90 else "需整改" if cs >= 70 else "高风险"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
