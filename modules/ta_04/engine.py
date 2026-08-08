"""[TA-04] AI转让定价文档自动生成 —— 模板填充 + 可比分析 + 合规检查。

核心算法（纯 stdlib）：
  * 模板填充：预定义转让定价文档结构，按章节填充企业/可比数据
  * 功能风险分析（FRA）：按功能/风险/资产三维度评分
  * 可比数据处理：计算均值/中位数/四分位区间
  * 利润水平指标（PLI）：营业利润率/完全成本加成率/资产回报率
  * 合规性检查：是否满足转让定价文档合规要求

PortableDB 持久化：
  - comparable_companies  可比公司数据
  - tp_documents         转让定价文档
  - compliance_records   合规检查记录
"""
from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ta_04.db"

_DEFAULT_MODEL = {
    "pli_metrics": [
        ("营业利润率", "operating_margin"),
        ("完全成本加成率", "full_cost_plus_markup"),
        ("资产回报率", "roa"),
    ],
    "func_risk_dims": [
        ("functions_performed", ["研发", "生产", "营销", "分销", "管理", "服务"]),
        ("risks_assumed", ["市场风险", "信用风险", "外汇风险", "存货风险", "知识产权风险"]),
        ("assets_used", ["有形资产", "无形资产", "金融资产", "人力资本"]),
    ],
    "doc_templates": {
        "intro": "一、企业概况\n1.1 企业基本信息\n1.2 集团组织结构\n1.3 业务范围描述",
        "func_risk": "二、功能风险分析\n2.1 功能分析\n2.2 风险分析\n2.3 资产分析\n2.4 功能风险定位",
        "comparability": "三、可比性分析\n3.1 可比公司筛选\n3.2 可比性调整\n3.3 独立交易区间",
        "method": "四、转让定价方法选择\n4.1 方法选择理由\n4.2 方法适用性分析\n4.3 方法应用说明",
        "adjustment": "五、转让定价调整\n5.1 调整计算\n5.2 调整合理性\n5.3 合规性说明",
    },
}

_COMPARABLE_SCHEMA = {
    "company_id": "TEXT PRIMARY KEY",
    "company_name": "TEXT",
    "country": "TEXT",
    "industry": "TEXT",
    "operating_margin": "REAL",
    "full_cost_plus_markup": "REAL",
    "roa": "REAL",
    "revenue": "REAL",
    "employees": "INTEGER",
    "scale_score": "REAL",
    "intangible_score": "REAL",
}
_DOC_SCHEMA = {
    "doc_id": "TEXT PRIMARY KEY",
    "doc_type": "TEXT",
    "enterprise_id": "TEXT",
    "sections": "JSON",
    "compliance_score": "REAL",
    "generated_at": "DATETIME",
}


class LLMEngine(AbstractEngine):
    """AI转让定价文档自动生成引擎（模板填充 + 可比分析）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for name, schema in [("comparable_companies", _COMPARABLE_SCHEMA),
                             ("tp_documents", _DOC_SCHEMA)]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        enterprise = input_data.get("enterprise", {}) or {}
        comparables_raw = input_data.get("comparables", []) or []
        doc_type = input_data.get("doc_type", "同期资料")

        comparables = []
        for c in comparables_raw:
            try:
                comparables.append({
                    "company_id": c.get("company_id") or f"COMP-{len(comparables)+1:06d}",
                    "company_name": str(c.get("company_name", "")),
                    "country": str(c.get("country", "")),
                    "industry": str(c.get("industry", "")),
                    "operating_margin": float(c.get("operating_margin", 0) or 0),
                    "full_cost_plus_markup": float(c.get("full_cost_plus_markup", 0) or 0),
                    "roa": float(c.get("roa", 0) or 0),
                    "revenue": float(c.get("revenue", 0) or 0),
                })
            except (TypeError, ValueError):
                continue

        return {
            "enterprise": enterprise,
            "comparables": comparables,
            "doc_type": doc_type,
        }

    def _infer(self, prepared: Any) -> dict:
        enterprise = prepared["enterprise"]
        comparables = prepared["comparables"]

        pli_analysis = {}
        for pli_name, pli_key in self.model["pli_metrics"]:
            vals = [c[pli_key] for c in comparables if c[pli_key] > 0]
            if len(vals) >= 3:
                sorted_v = sorted(vals)
                pli_analysis[pli_key] = {
                    "name": pli_name,
                    "count": len(vals),
                    "mean": round(statistics.mean(vals), 4),
                    "median": round(statistics.median(vals), 4),
                    "q1": round(sorted_v[len(sorted_v) // 4], 4),
                    "q3": round(sorted_v[3 * len(sorted_v) // 4], 4),
                    "iqr_range": [round(sorted_v[len(sorted_v) // 4], 4),
                                 round(sorted_v[3 * len(sorted_v) // 4], 4)],
                    "max": round(max(vals), 4),
                    "min": round(min(vals), 4),
                }

        func_risk_profile = self._analyze_func_risk(enterprise)

        enterprise_plis = enterprise.get("pli_values", {})
        interquartile_check = {}
        for pli_key, analysis in pli_analysis.items():
            q1, q3 = analysis["iqr_range"]
            ent_val = enterprise_plis.get(pli_key)
            if ent_val is not None:
                in_range = q1 <= ent_val <= q3
                interquartile_check[pli_key] = {
                    "enterprise_value": ent_val,
                    "q1": q1,
                    "q3": q3,
                    "in_interquartile_range": in_range,
                    "adjustment_needed": not in_range,
                }

        compliance = self._check_compliance(enterprise, comparables, pli_analysis)

        doc_sections = {}
        templates = self.model["doc_templates"]
        doc_sections["intro"] = f"{templates['intro']}\n\n企业名称: {enterprise.get('name', '未提供')}\n统一社会信用代码: {enterprise.get('uscc', '未提供')}"
        doc_sections["func_risk"] = f"{templates['func_risk']}\n\n{func_risk_profile}"
        doc_sections["comparability"] = f"{templates['comparability']}\n\n可比公司数量: {len(comparables)}\nPLI分析: {pli_analysis}"
        doc_sections["method"] = templates["method"]
        doc_sections["adjustment"] = f"{templates['adjustment']}\n\n合规评分: {compliance['score']}"

        return {
            "doc_sections": doc_sections,
            "pli_analysis": pli_analysis,
            "func_risk_profile": func_risk_profile,
            "interquartile_check": interquartile_check,
            "compliance": compliance,
            "enterprise": enterprise,
            "summary": {
                "compliance_score": compliance["score"],
                "comparable_count": len(comparables),
                "pli_count": len(pli_analysis),
                "adjustment_needed": sum(1 for c in interquartile_check.values()
                                         if c.get("adjustment_needed")),
            },
        }

    def _analyze_func_risk(self, enterprise: dict) -> dict:
        dims = self.model["func_risk_dims"]
        result = {}
        for dim_name, options in dims:
            selected = enterprise.get(dim_name, []) or []
            score = len(selected) / max(len(options), 1)
            level = "高" if score >= 0.6 else ("中" if score >= 0.3 else "低")
            result[dim_name] = {
                "selected": selected,
                "coverage": f"{len(selected)}/{len(options)}",
                "score": round(score, 2),
                "level": level,
            }
        return result

    def _check_compliance(self, enterprise: dict, comparables: list,
                          pli_analysis: dict) -> dict:
        checks = []
        score = 100.0

        if len(comparables) < 5:
            checks.append({"item": "可比公司数量", "passed": False,
                           "msg": f"仅{len(comparables)}家可比公司，建议至少5家"})
            score -= 20
        else:
            checks.append({"item": "可比公司数量", "passed": True,
                           "msg": f"{len(comparables)}家可比公司"})

        if len(pli_analysis) < 2:
            checks.append({"item": "PLI指标覆盖", "passed": False,
                           "msg": "PLI指标不足，建议至少覆盖2个指标"})
            score -= 15
        else:
            checks.append({"item": "PLI指标覆盖", "passed": True,
                           "msg": f"覆盖{len(pli_analysis)}个PLI指标"})

        name = enterprise.get("name", "")
        if not name:
            checks.append({"item": "企业信息完整性", "passed": False,
                           "msg": "企业名称缺失"})
            score -= 15
        else:
            checks.append({"item": "企业信息完整性", "passed": True,
                           "msg": "企业基本信息完整"})

        score = max(0.0, round(score, 1))
        return {"score": score, "checks": checks, "status": "合规" if score >= 70 else "需改进"}

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        compliance = result["compliance"]
        summary["compliance_status"] = compliance.get("status", "未知")
        summary["failed_checks"] = [
            c for c in compliance.get("checks", []) if not c["passed"]
        ]
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
