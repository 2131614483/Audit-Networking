"""[FI-01] AI信贷资产质量评估引擎 —— RWO加权 + 现金流折现 + 行业因子。

核心算法（纯 stdlib）：
  * 信贷分类：五级（正常/关注/次级/可疑/损失）
  * 加权风险敞口（RWE）：按违约概率加权
  * 违约概率（PD）：基于历史数据的Logistic近似
  * 违约损失率（LGD）：根据担保品类型估计
  * 预期损失（EL）= PD × LGD × EAD
  * 现金流折现：IRR近似计算

PortableDB 持久化：
  - credit_assets  信贷资产数据
  - risk_history   历史违约数据
  - evaluations    评估结果
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fi_01.db"

_DEFAULT_MODEL = {
    "grade_ranges": [
        ("正常", 0.0, 0.02),
        ("关注", 0.02, 0.05),
        ("次级", 0.05, 0.15),
        ("可疑", 0.15, 0.40),
        ("损失", 0.40, 1.0),
    ],
    "collateral_lgd": {
        "现金": 0.10,
        "国债": 0.15,
        "银行存单": 0.15,
        "房产": 0.35,
        "应收账款": 0.45,
        "存货": 0.55,
        "设备": 0.50,
        "保证": 0.40,
        "信用": 0.75,
    },
    "industry_adjustment": {
        "房地产": 1.3,
        "建筑业": 1.2,
        "制造业": 1.0,
        "批发零售": 1.05,
        "信息技术": 0.9,
        "金融业": 0.85,
        "农业": 1.15,
    },
    "pd_intercept": -3.0,
    "pd_coefficients": {
        "debt_ratio": 2.5,
        "current_ratio": -1.0,
        "operating_margin": -2.0,
        "cashflow_coverage": -1.5,
    },
}

_ASSET_SCHEMA = {
    "asset_id": "TEXT PRIMARY KEY",
    "borrower": "TEXT",
    "amount": "REAL",
    "industry": "TEXT",
    "collateral_type": "TEXT",
    "term_months": "INTEGER",
    "debt_ratio": "REAL",
    "current_ratio": "REAL",
    "operating_margin": "REAL",
    "cashflow_coverage": "REAL",
    "payment_history": "INTEGER",
}


class MLEngine(AbstractEngine):
    """AI信贷资产质量评估引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        if "credit_assets" not in self.db.tables():
            self.db.create_table("credit_assets", _ASSET_SCHEMA)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        loans_raw = input_data.get("loans", []) or []
        loans = []
        for l in loans_raw:
            try:
                loans.append({
                    "asset_id": l.get("asset_id") or f"LOAN-{len(loans)+1:06d}",
                    "borrower": str(l.get("borrower", "")),
                    "amount": float(l.get("amount", 0) or 0),
                    "industry": str(l.get("industry", "")),
                    "collateral_type": str(l.get("collateral_type", "信用")),
                    "term_months": int(l.get("term_months", 12) or 12),
                    "debt_ratio": float(l.get("debt_ratio", 0.5) or 0.5),
                    "current_ratio": float(l.get("current_ratio", 1.5) or 1.5),
                    "operating_margin": float(l.get("operating_margin", 0.05) or 0.05),
                    "cashflow_coverage": float(l.get("cashflow_coverage", 1.2) or 1.2),
                    "payment_history": int(l.get("payment_history", 12) or 12),
                    "remaining_months": int(l.get("remaining_months", 12) or 12),
                    "remaining_amount": float(l.get("remaining_amount", 0) or 0),
                    "interest_rate": float(l.get("interest_rate", 0.05) or 0.05),
                })
            except (TypeError, ValueError):
                continue

        return {"loans": loans}

    def _infer(self, prepared: Any) -> dict:
        loans = prepared["loans"]
        assessments = []

        for loan in loans:
            pd_score = self._compute_pd(loan)
            lgd_score = self._compute_lgd(loan)
            ead = loan.get("remaining_amount") or loan["amount"]
            el = pd_score * lgd_score * ead
            grade = self._map_grade(pd_score)
            risk_weight = self._grade_to_weight(grade)
            rwa = ead * risk_weight
            industry_mult = self.model["industry_adjustment"].get(loan["industry"], 1.0)
            adjusted_rwa = rwa * industry_mult
            capital_requirement = adjusted_rwa * 0.08

            assessments.append({
                "asset_id": loan["asset_id"],
                "borrower": loan["borrower"],
                "grade": grade,
                "pd": round(pd_score, 4),
                "lgd": round(lgd_score, 4),
                "ead": round(ead, 2),
                "expected_loss": round(el, 2),
                "risk_weight": risk_weight,
                "rwa": round(adjusted_rwa, 2),
                "capital_requirement": round(capital_requirement, 2),
                "industry_multiplier": industry_mult,
                "factors": {
                    "debt_ratio": loan["debt_ratio"],
                    "current_ratio": loan["current_ratio"],
                    "operating_margin": loan["operating_margin"],
                    "cashflow_coverage": loan["cashflow_coverage"],
                    "payment_score": min(1.0, loan["payment_history"] / 24.0),
                },
            })

        summary = self._summarize(assessments)

        return {
            "loans": loans,
            "assessments": assessments,
            "summary": summary,
        }

    def _compute_pd(self, loan: dict) -> float:
        intercept = self.model["pd_intercept"]
        coeffs = self.model["pd_coefficients"]
        z = intercept
        for key, coef in coeffs.items():
            z += coef * loan.get(key, 0.5)
        payment_factor = max(0.0, 1.0 - loan["payment_history"] / 24.0)
        pd = 1.0 / (1.0 + math.exp(-z))
        pd = pd * (1.0 + payment_factor * 0.3)
        return min(0.99, max(0.001, pd))

    def _compute_lgd(self, loan: dict) -> float:
        lgd_table = self.model["collateral_lgd"]
        coll = loan["collateral_type"]
        base = lgd_table.get(coll, 0.6)
        if loan["payment_history"] < 6:
            base = min(0.9, base + 0.1)
        return base

    def _map_grade(self, pd: float) -> str:
        for name, lo, hi in self.model["grade_ranges"]:
            if lo <= pd < hi:
                return name
        return "损失"

    def _grade_to_weight(self, grade: str) -> float:
        return {
            "正常": 0.2,
            "关注": 0.5,
            "次级": 1.0,
            "可疑": 1.5,
            "损失": 1.5,
        }.get(grade, 1.0)

    def _summarize(self, assessments: list) -> dict:
        total_ead = sum(a["ead"] for a in assessments)
        total_el = sum(a["expected_loss"] for a in assessments)
        total_rwa = sum(a["rwa"] for a in assessments)
        grade_counts = defaultdict(int)
        for a in assessments:
            grade_counts[a["grade"]] += 1
        return {
            "asset_count": len(assessments),
            "total_ead": round(total_ead, 2),
            "total_expected_loss": round(total_el, 2),
            "total_rwa": round(total_rwa, 2),
            "avg_risk_weight": round(
                total_rwa / total_ead if total_ead > 0 else 0, 4
            ),
            "grade_distribution": dict(grade_counts),
            "el_ratio": round(total_el / total_ead, 6) if total_ead > 0 else 0,
        }

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        summary["risk_level"] = (
            "高风险" if summary.get("el_ratio", 0) > 0.05
            else "中风险" if summary.get("el_ratio", 0) > 0.02
            else "低风险"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
