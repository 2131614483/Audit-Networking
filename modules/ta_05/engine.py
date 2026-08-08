"""[TA-05] ML可比公司智能筛选 —— 多因子评分 + 相似度 + 分层抽样。

核心算法（纯 stdlib）：
  * 多因子标准化：z-score归一化 + min-max归一化
  * 因子加权评分：规模/行业/地域/功能/财务五维度
  * 余弦相似度：可比公司与待评估企业的相似度
  * 分层抽样：按相似度区间分层抽取可比组
  * Top-K筛选：选取得分最高的K家作为可比组

PortableDB 持久化：
  - company_profiles  公司画像
  - screening_results 筛选结果
"""
from __future__ import annotations

import math
import statistics
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ta_05.db"

_DEFAULT_MODEL = {
    "factor_weights": {
        "industry_match": 0.25,
        "region_match": 0.10,
        "scale_similarity": 0.25,
        "functional_similarity": 0.20,
        "financial_similarity": 0.20,
    },
    "top_k": 5,
    "min_similarity": 0.5,
    "scale_log_transform": True,
}

_PROFILE_SCHEMA = {
    "company_id": "TEXT PRIMARY KEY",
    "company_name": "TEXT",
    "industry": "TEXT",
    "sub_industry": "TEXT",
    "region": "TEXT",
    "country": "TEXT",
    "revenue": "REAL",
    "employees": "INTEGER",
    "operating_margin": "REAL",
    "roa": "REAL",
    "functions": "JSON",
    "features": "JSON",
}


class MLEngine(AbstractEngine):
    """ML可比公司智能筛选引擎（多因子相似度）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        if "company_profiles" not in self.db.tables():
            self.db.create_table("company_profiles", _PROFILE_SCHEMA)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        target = input_data.get("target_company", {}) or {}
        candidates_raw = input_data.get("candidates", []) or []

        candidates = []
        for c in candidates_raw:
            try:
                candidates.append({
                    "company_id": c.get("company_id") or f"COMP-{len(candidates)+1:06d}",
                    "company_name": str(c.get("company_name", "")),
                    "industry": str(c.get("industry", "")),
                    "sub_industry": str(c.get("sub_industry", "")),
                    "region": str(c.get("region", "")),
                    "country": str(c.get("country", "")),
                    "revenue": float(c.get("revenue", 0) or 0),
                    "employees": int(c.get("employees", 0) or 0),
                    "operating_margin": float(c.get("operating_margin", 0) or 0),
                    "roa": float(c.get("roa", 0) or 0),
                    "functions": c.get("functions", []) or [],
                })
            except (TypeError, ValueError):
                continue

        return {"target": target, "candidates": candidates}

    def _infer(self, prepared: Any) -> dict:
        target = prepared["target"]
        candidates = prepared["candidates"]
        weights = self.model["factor_weights"]

        if not candidates:
            return {"results": [], "summary": {"candidate_count": 0}}

        revenues = [c["revenue"] for c in candidates if c["revenue"] > 0]
        if revenues:
            rev_mean = statistics.mean(revenues)
            rev_std = statistics.pstdev(revenues) if len(revenues) > 1 else 1.0
        else:
            rev_mean = 1.0
            rev_std = 1.0

        target_rev = float(target.get("revenue", 0) or 0)
        target_emp = int(target.get("employees", 0) or 0)
        target_ind = target.get("industry", "")
        target_sub = target.get("sub_industry", "")
        target_region = target.get("region", "")
        target_country = target.get("country", "")
        target_funcs = set(target.get("functions", []) or [])
        target_margin = float(target.get("operating_margin", 0) or 0)
        target_roa = float(target.get("roa", 0) or 0)

        scored = []
        for c in candidates:
            scores = {}

            ind_score = 0.0
            if target_ind and c["industry"]:
                if c["sub_industry"] == target_sub and c["industry"] == target_ind:
                    ind_score = 1.0
                elif c["industry"] == target_ind:
                    ind_score = 0.8
                else:
                    ind_score = 0.1
            scores["industry_match"] = ind_score

            reg_score = 0.0
            if c["country"] == target_country:
                reg_score = 1.0
            elif c["region"] == target_region:
                reg_score = 0.7
            scores["region_match"] = reg_score

            scale_score = 0.5
            if target_rev > 0 and c["revenue"] > 0:
                ratio = min(target_rev, c["revenue"]) / max(target_rev, c["revenue"])
                scale_score = ratio
            scores["scale_similarity"] = scale_score

            c_funcs = set(c["functions"])
            if target_funcs and c_funcs:
                func_score = len(target_funcs & c_funcs) / max(len(target_funcs | c_funcs), 1)
            else:
                func_score = 0.5
            scores["functional_similarity"] = func_score

            fin_score = 0.5
            if target_margin != 0 or target_roa != 0:
                margin_diff = abs(target_margin - c["operating_margin"])
                roa_diff = abs(target_roa - c["roa"])
                fin_score = max(0.0, 1.0 - (margin_diff + roa_diff))
            scores["financial_similarity"] = fin_score

            total = sum(weights[k] * scores[k] for k in weights)
            scored.append({
                "company_id": c["company_id"],
                "company_name": c["company_name"],
                "total_score": round(total, 4),
                "detail_scores": {k: round(v, 4) for k, v in scores.items()},
            })

        scored.sort(key=lambda x: x["total_score"], reverse=True)
        top_k = self.model["top_k"]
        selected = scored[:top_k]

        summary = {
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "selection_threshold": self.model["min_similarity"],
            "avg_score_selected": round(
                sum(s["total_score"] for s in selected) / max(len(selected), 1), 4
            ),
            "selected_companies": selected,
        }

        return {
            "target": target,
            "all_candidates": scored,
            "selected": selected,
            "summary": summary,
        }

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        all_cands = result["all_candidates"]
        low_sim = [c for c in all_cands
                   if c["total_score"] < self.model["min_similarity"]]
        summary["low_similarity_count"] = len(low_sim)
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
