"""[CM-03] 持续审计方法论框架引擎 —— 纯 stdlib 知识图谱匹配 + 方法论推荐 + 质量检查。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 方法论知识图谱（节点+关系+案例）：
      - 节点：流程/方法/技术/场景/指标/最佳实践
      - 关系：适用于/包含/使用/评估/示例/推荐
  * 方法论推荐引擎（五维加权）：
      - 场景匹配（语义关键词匹配 + difflib 相似度）权重 40%
      - 效果评估（历史评分）权重 25%
      - 技术成熟度权重 15%
      - 资源需求匹配权重 10%
      - 风险等级适配权重 10%
  * 审计程序生成（模板化 + 场景自适应）：
      - 基于推荐方法的程序结构生成
      - 场景/技术/规模/风险四维度自动调整
  * 质量检查（五维评分模型）：
      - 完整性×25% + 一致性×20% + 可行性×20% + 有效性×20% + 合规性×15%

模型结构（self.model）：
  {
    "nodes": [...],
    "edges": [...],
    "cases": [...],
    "scenario_keywords": {...},
    "method_scoring": {...},
    "quality_weights": {...},
  }
"""
from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "cm_03.db"

_NODES_SCHEMA = {
    "node_id": "TEXT",
    "node_type": "TEXT",
    "name": "TEXT",
    "content": "TEXT",
    "tags": "JSON",
    "meta": "JSON",
}
_EDGES_SCHEMA = {
    "edge_id": "TEXT",
    "from_id": "TEXT",
    "to_id": "TEXT",
    "relation": "TEXT",
    "weight": "REAL",
}
_CASES_SCHEMA = {
    "case_id": "TEXT",
    "title": "TEXT",
    "scenario": "TEXT",
    "method_id": "TEXT",
    "industry": "TEXT",
    "scale": "TEXT",
    "result_score": "REAL",
    "summary": "TEXT",
    "created_at": "DATETIME",
}
_PROGRAMS_SCHEMA = {
    "program_id": "TEXT",
    "name": "TEXT",
    "scenario": "TEXT",
    "content": "JSON",
    "quality_score": "REAL",
    "created_at": "DATETIME",
}

_SCENARIO_KEYWORDS: dict[str, list[str]] = {
    "procurement_payment": ["采购", "付款", "供应商", "采购付款", "应付款"],
    "sales_receivable": ["销售", "收款", "客户", "销售回款", "应收款"],
    "financial_reporting": ["财务报告", "报表", "披露", "合并报表"],
    "expense_management": ["费用", "报销", "支出", "费用管控"],
    "inventory": ["存货", "库存", "盘点", "存货管理"],
    "fixed_asset": ["固定资产", "资产", "折旧", "资产处置"],
    "payroll": ["薪酬", "工资", "人力成本", "员工薪酬"],
    "compliance": ["合规", "法规", "监管", "合规检查"],
    "fraud_detection": ["舞弊", "欺诈", "贪腐", "舞弊检测"],
    "it_general": ["IT", "系统", "信息系统", "IT内控"],
    "data_analytics": ["数据分析", "数据", "大数据", "数据审计"],
}

_METHOD_CATALOG: list[dict] = [
    {"id": "M01", "name": "实时交易监控", "type": "monitor",
     "applicable": ["procurement_payment", "sales_receivable", "expense_management"],
     "tech": ["streaming", "rule_engine"], "maturity": 0.9, "resource_level": "medium",
     "risk_levels": ["medium", "high"], "base_score": 78,
     "desc": "基于规则引擎对交易流进行实时检查，发现异常即时预警。"},
    {"id": "M02", "name": "ML异常检测", "type": "ml",
     "applicable": ["procurement_payment", "fraud_detection", "inventory"],
     "tech": ["ml", "anomaly"], "maturity": 0.8, "resource_level": "high",
     "risk_levels": ["medium", "high", "critical"], "base_score": 82,
     "desc": "使用Isolation Forest、Z-score等算法识别交易中的统计异常。"},
    {"id": "M03", "name": "连续抽样审计", "type": "sampling",
     "applicable": ["financial_reporting", "inventory", "fixed_asset"],
     "tech": ["sampling", "stats"], "maturity": 0.95, "resource_level": "low",
     "risk_levels": ["low", "medium"], "base_score": 72,
     "desc": "基于统计抽样方法，对持续产生的数据进行随机或分层抽样审计。"},
    {"id": "M04", "name": "嵌入式审计模块", "type": "embedded",
     "applicable": ["procurement_payment", "sales_receivable", "payroll"],
     "tech": ["api", "embedded"], "maturity": 0.75, "resource_level": "high",
     "risk_levels": ["medium", "high"], "base_score": 70,
     "desc": "在业务系统API层嵌入审计检查点，交易前/中/后全程管控。"},
    {"id": "M05", "name": "数据穿透分析", "type": "analytics",
     "applicable": ["financial_reporting", "fraud_detection", "data_analytics"],
     "tech": ["bi", "drill_down"], "maturity": 0.85, "resource_level": "medium",
     "risk_levels": ["medium", "high", "critical"], "base_score": 76,
     "desc": "从汇总数据下钻至底层明细，追溯异常根因。"},
    {"id": "M06", "name": "合规自动检查", "type": "compliance",
     "applicable": ["compliance", "procurement_payment", "financial_reporting"],
     "tech": ["rule_engine", "knowledge_base"], "maturity": 0.88, "resource_level": "medium",
     "risk_levels": ["medium", "high", "critical"], "base_score": 80,
     "desc": "基于法规知识库自动校验业务操作是否符合合规要求。"},
    {"id": "M07", "name": "风险指标看板", "type": "dashboard",
     "applicable": ["it_general", "data_analytics"],
     "tech": ["bi", "visualization"], "maturity": 0.92, "resource_level": "low",
     "risk_levels": ["low", "medium", "high"], "base_score": 68,
     "desc": "实时展示关键风险指标变化趋势，辅助审计决策。"},
    {"id": "M08", "name": "AI文档智能分析", "type": "llm",
     "applicable": ["compliance", "fraud_detection", "financial_reporting"],
     "tech": ["llm", "nlp"], "maturity": 0.7, "resource_level": "high",
     "risk_levels": ["medium", "high"], "base_score": 65,
     "desc": "使用LLM对合同、报告、邮件等非结构化文档进行智能审阅。"},
]

_QUALITY_DIMENSIONS = ["completeness", "consistency", "feasibility", "effectiveness", "compliance"]
_QUALITY_WEIGHTS = {"completeness": 0.25, "consistency": 0.20, "feasibility": 0.20,
                    "effectiveness": 0.20, "compliance": 0.15}


class LLMEngine(AbstractEngine):
    """CM-03 方法论框架引擎（知识图谱匹配 + 推荐 + 程序生成 + 质量检查）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        tables = {"nodes": _NODES_SCHEMA, "edges": _EDGES_SCHEMA,
                  "cases": _CASES_SCHEMA, "programs": _PROGRAMS_SCHEMA}
        for t, s in tables.items():
            if t not in self.db.tables():
                self.db.create_table(t, s)

        self.model = {
            "methods": list(_METHOD_CATALOG),
            "scenario_keywords": dict(_SCENARIO_KEYWORDS),
            "quality_weights": dict(_QUALITY_WEIGHTS),
            "quality_dimensions": list(_QUALITY_DIMENSIONS),
            "edges_index": defaultdict(list),
            "nodes_index": {},
        }
        self._build_kg_index()

    def _build_kg_index(self) -> None:
        if not self.db:
            return
        self.model["nodes_index"].clear()
        self.model["edges_index"].clear()
        for node in self.db.all("nodes"):
            self.model["nodes_index"][node["node_id"]] = node
        for edge in self.db.all("edges"):
            self.model["edges_index"][edge["from_id"]].append(edge)

    def _ensure_loaded(self) -> None:
        """惰性初始化（支持不显式调用 setup() 直接 execute()）。"""
        if getattr(self, "model", None) is None:
            self._load_model()

    def _preprocess(self, input_data: Any) -> dict:
        self._ensure_loaded()
        if isinstance(input_data, str):
            return {"action": "recommend", "scenario_text": input_data,
                    "risk_level": "medium", "resource_level": "medium"}
        if isinstance(input_data, dict):
            action = input_data.get("action", "recommend")
            if action == "recommend":
                scenario = input_data.get("scenario", input_data.get("scenario_text", ""))
                return {
                    "action": "recommend",
                    "scenario_text": str(scenario).lower(),
                    "scenario_obj": input_data.get("scenario_obj"),
                    "risk_level": input_data.get("risk_level", "medium"),
                    "resource_level": input_data.get("resource_level", "medium"),
                    "top_k": input_data.get("top_k", 5),
                }
            if action == "generate_program":
                return {
                    "action": "generate_program",
                    "scenario_text": str(input_data.get("scenario", "")).lower(),
                    "method_ids": input_data.get("method_ids"),
                    "adaptations": input_data.get("adaptations", {}),
                }
            if action == "quality_check":
                program = input_data.get("program", input_data)
                return {
                    "action": "quality_check",
                    "program": program,
                    "scenario_text": str(input_data.get("scenario", "")).lower(),
                }
            if action == "add_case":
                return {"action": "add_case", "case": input_data.get("case", input_data)}
            if action == "add_knowledge":
                return {"action": "add_knowledge",
                        "nodes": input_data.get("nodes", []),
                        "edges": input_data.get("edges", [])}
        raise ValueError(f"无法识别的输入: {input_data}")

    def _infer(self, prepared: dict) -> dict:
        action = prepared["action"]
        if action == "recommend":
            return self._recommend_methods(prepared)
        if action == "generate_program":
            return self._generate_program(prepared)
        if action == "quality_check":
            return self._quality_check(prepared)
        if action == "add_case":
            return self._add_case(prepared["case"])
        if action == "add_knowledge":
            return self._add_knowledge(prepared["nodes"], prepared["edges"])
        raise ValueError(f"未知 action: {action}")

    def _postprocess(self, result: dict) -> dict:
        result["engine"] = "CM-03-MethodologyFramework"
        result["timestamp"] = datetime.now().isoformat()
        return result

    # ---------- 核心算法 ----------

    def _match_scenario(self, text: str) -> list[tuple[str, float]]:
        scores: list[tuple[str, float]] = []
        for scenario, kws in self.model["scenario_keywords"].items():
            hit = sum(1 for kw in kws if kw.lower() in text)
            score = hit / max(len(kws), 1)
            if score > 0:
                scores.append((scenario, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        if not scores:
            for scenario in self.model["scenario_keywords"]:
                scores.append((scenario, 0.1))
        return scores

    def _semantic_similarity(self, text: str, method_desc: str, method_name: str) -> float:
        text_lower = text.lower()
        desc_lower = method_desc.lower()
        name_lower = method_name.lower()
        combined = text_lower
        score = 0.0
        if name_lower and name_lower in combined:
            score += 0.3
        common_words = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]+", desc_lower)) & \
                       set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]+", combined))
        if common_words:
            score += min(len(common_words) * 0.08, 0.4)
        sim = difflib.SequenceMatcher(None, desc_lower, combined).ratio()
        score += sim * 0.3
        return min(score, 1.0)

    def _recommend_methods(self, params: dict) -> dict:
        text = params["scenario_text"]
        risk_level = params["risk_level"]
        resource_level = params["resource_level"]
        top_k = params["top_k"]
        scenario_scores = self._match_scenario(text)
        scenario_map = dict(scenario_scores)
        methods = self.model["methods"]
        raw_scores = []
        for m in methods:
            scenario_match = max(
                (scenario_map.get(s, 0) for s in m["applicable"]), default=0.0
            )
            semantic = self._semantic_similarity(text, m["desc"], m["name"])
            s_score = scenario_match * 0.7 + semantic * 0.3
            e_score = m["base_score"] / 100.0 * m["maturity"]
            t_score = m["maturity"]
            resource_map = {"low": 0.9, "medium": 0.7, "high": 0.4}
            r_need = m["resource_level"]
            r_score = resource_map.get(resource_level, 0.6) if r_need != "high" else (
                resource_map.get(resource_level, 0.3) * 0.8
            )
            risk_fit = 1.0 if risk_level in m["risk_levels"] else 0.5
            score = (s_score * 0.40 + e_score * 0.25 + t_score * 0.15
                     + r_score * 0.10 + risk_fit * 0.10)
            raw_scores.append((m, score, {"s": s_score, "e": e_score, "t": t_score,
                                           "r": r_score, "risk_fit": risk_fit}))
        raw_scores.sort(key=lambda x: x[1], reverse=True)
        top = raw_scores[:top_k]
        recommendations = []
        for m, score, breakdown in top:
            recommendations.append({
                "method_id": m["id"],
                "method_name": m["name"],
                "total_score": round(score * 100, 1),
                "breakdown": {k: round(v * 100, 1) for k, v in breakdown.items()},
                "rationale": self._build_rationale(m, breakdown),
                "desc": m["desc"],
            })
        return {
            "action": "recommend",
            "scenario_matched": scenario_scores[:3],
            "recommendations": recommendations,
            "top_method": recommendations[0] if recommendations else None,
        }

    def _build_rationale(self, method: dict, bd: dict) -> str:
        reasons = []
        if bd["s"] > 0.4:
            reasons.append("场景匹配度高")
        if bd["e"] > 0.7:
            reasons.append("历史效果良好")
        if bd["t"] > 0.8:
            reasons.append("技术成熟")
        if bd["risk_fit"] >= 0.9:
            reasons.append("适配当前风险等级")
        if not reasons:
            reasons.append("综合评分靠前")
        return "；".join(reasons) + f"，建议采用「{method['name']}」。"

    def _generate_program(self, params: dict) -> dict:
        text = params["scenario_text"]
        method_ids = params.get("method_ids")
        adaptations = params.get("adaptations", {})
        if not method_ids:
            rec = self._recommend_methods({"scenario_text": text, "risk_level": "medium",
                                            "resource_level": "medium", "top_k": 2})
            method_ids = [r["method_id"] for r in rec["recommendations"][:2]]
        methods = [m for m in self.model["methods"] if m["id"] in method_ids]
        if not methods:
            methods = self.model["methods"][:2]
        scenario_name = text or "通用业务场景"
        tech_adapt = adaptations.get("technology", "standard")
        scale_adapt = adaptations.get("scale", "medium")
        risk_adapt = adaptations.get("risk", "medium")
        program = {
            "program_name": f"{scenario_name}持续审计程序",
            "audit_goal": f"对{scenario_name}实施持续审计监控，及时发现异常和风险",
            "audit_frequency": "实时/日度" if risk_adapt in ("high", "critical") else "日度/周度",
            "data_sources": self._pick_data_sources(scenario_name),
            "methods_applied": [m["name"] for m in methods],
            "check_rules": self._build_check_rules(methods, risk_adapt),
            "ml_models": [m["name"] for m in methods if m["type"] in ("ml", "llm")],
            "alert_settings": self._build_alert_settings(risk_adapt),
            "handling_flow": "自动处理+人工复核",
            "report_cycle": "周报/月报",
            "adaptations": {"tech": tech_adapt, "scale": scale_adapt, "risk": risk_adapt},
        }
        quality = self._compute_quality(program, text)
        program_id = hashlib.md5(
            (program["program_name"] + datetime.now().isoformat()).encode()
        ).hexdigest()[:12]
        if self.db:
            self.db.insert("programs", {
                "program_id": program_id, "name": program["program_name"],
                "scenario": text, "content": program,
                "quality_score": quality["total_score"],
                "created_at": datetime.now(),
            })
        return {
            "action": "generate_program",
            "program_id": program_id,
            "program": program,
            "quality_preview": {"score": quality["total_score"], "grade": quality["grade"]},
        }

    def _pick_data_sources(self, scenario: str) -> list[str]:
        base = ["ERP系统", "财务系统"]
        if any(kw in scenario for kw in ["采购", "供应商"]):
            base += ["采购系统", "供应商管理系统"]
        if any(kw in scenario for kw in ["销售", "客户"]):
            base += ["CRM系统", "订单管理系统"]
        if any(kw in scenario for kw in ["合规", "法规"]):
            base += ["合规管理平台", "法规数据库"]
        if any(kw in scenario for kw in ["IT", "系统"]):
            base += ["ITSM系统", "安全日志"]
        return list(dict.fromkeys(base))

    def _build_check_rules(self, methods: list[dict], risk: str) -> list[dict]:
        rules = []
        for m in methods:
            if m["id"] == "M01":
                rules += [
                    {"rule": "单笔金额超限检查", "frequency": "实时",
                     "params": {"max_amount": 1000000 if risk != "low" else 500000}},
                    {"rule": "交易时段异常检查", "frequency": "实时"},
                    {"rule": "频率异常检查", "frequency": "日度"},
                ]
            elif m["id"] == "M02":
                rules += [
                    {"rule": "Isolation Forest异常评分", "frequency": "日度",
                     "params": {"threshold": 0.7}},
                    {"rule": "Z-score统计异常", "frequency": "日度",
                     "params": {"z_threshold": 3.0}},
                ]
            elif m["id"] == "M05":
                rules += [
                    {"rule": "汇总-明细穿透校验", "frequency": "日度"},
                    {"rule": "跨系统数据一致性检查", "frequency": "日度"},
                ]
            elif m["id"] == "M06":
                rules += [
                    {"rule": "合规条款自动比对", "frequency": "日度"},
                    {"rule": "审批流程完整性检查", "frequency": "实时"},
                ]
            else:
                rules.append({"rule": f"{m['name']}基础检查", "frequency": "日度"})
        return rules

    def _build_alert_settings(self, risk: str) -> dict:
        thresholds = {"low": (30, 50, 70), "medium": (50, 70, 90),
                      "high": (80, 90, 95), "critical": (70, 85, 95)}
        g, y, r = thresholds.get(risk, thresholds["medium"])
        return {"green": f"<{g}", "yellow": f"{g}-{y}",
                "orange": f"{y}-{r}", "red": f">{r}"}

    def _quality_check(self, params: dict) -> dict:
        program = params["program"]
        text = params["scenario_text"]
        result = self._compute_quality(program, text)
        return {
            "action": "quality_check",
            "program_name": program.get("program_name", "未命名程序"),
            "dimensions": result["dimensions"],
            "total_score": result["total_score"],
            "grade": result["grade"],
            "suggestions": result["suggestions"],
        }

    def _compute_quality(self, program: dict, text: str) -> dict:
        dims: dict[str, float] = {}
        issues: list[str] = []

        methods_names = program.get("methods_applied", [])
        applicable_m = [m for m in self.model["methods"] if m["name"] in methods_names]
        scenario_matches = self._match_scenario(text)
        top_scenarios = [s for s, _ in scenario_matches[:3]]

        completeness_checks = [
            ("check_rules", len(program.get("check_rules", [])) >= 2, "检查规则数量"),
            ("alert_settings", bool(program.get("alert_settings")), "预警设置"),
            ("data_sources", len(program.get("data_sources", [])) >= 2, "数据源覆盖"),
        ]
        comp_hits = sum(1 for _, ok, _ in completeness_checks if ok)
        completeness = comp_hits / len(completeness_checks) * 100
        for key, ok, label in completeness_checks:
            if not ok:
                issues.append(f"完整性: 缺少{label}")
        dims["completeness"] = round(completeness, 1)

        if applicable_m:
            target_methods = [m for m in applicable_m
                              if any(s in m["applicable"] for s in top_scenarios)]
            consistency = (len(target_methods) / max(len(applicable_m), 1)) * 100
        else:
            consistency = 60.0
            issues.append("一致性: 未匹配到适用方法")
        dims["consistency"] = round(consistency, 1)

        has_rule_engine = any(m.get("type") == "monitor" for m in applicable_m)
        has_ml = any(m.get("type") in ("ml", "llm") for m in applicable_m)
        feasibility = 50.0
        if has_rule_engine:
            feasibility += 20
        if has_ml:
            feasibility += 15
        if program.get("handling_flow"):
            feasibility += 15
        feasibility = min(feasibility, 100)
        dims["feasibility"] = round(feasibility, 1)

        rule_count = len(program.get("check_rules", []))
        alert_count = len(program.get("alert_settings", {}))
        effectiveness = min(rule_count * 15 + alert_count * 8, 100)
        if not applicable_m:
            effectiveness = max(effectiveness - 20, 20)
        dims["effectiveness"] = round(effectiveness, 1)

        compliance = 60.0
        if any("合规" in (r.get("rule", "")) or "法规" in (r.get("rule", ""))
               for r in program.get("check_rules", [])):
            compliance += 20
        if any("compliance" in m.get("id", "").lower() for m in applicable_m):
            compliance += 20
        dims["compliance"] = min(compliance, 100.0)

        weights = self.model["quality_weights"]
        total = sum(dims[d] * weights.get(d, 0.2) for d in self.model["quality_dimensions"])

        if total >= 85:
            grade = "优秀"
        elif total >= 70:
            grade = "良好"
        elif total >= 60:
            grade = "合格"
        else:
            grade = "需改进"

        suggestions = list(issues)
        if dims["completeness"] < 70:
            suggestions.append("增加检查规则和数据源覆盖")
        if dims["consistency"] < 70:
            suggestions.append("调整审计方法以更好匹配业务场景")
        if dims["feasibility"] < 70:
            suggestions.append("评估实施技术条件，增加规则引擎或ML组件")
        if not suggestions:
            suggestions.append("方法论框架完善，可直接实施")

        return {
            "dimensions": dims,
            "total_score": round(total, 1),
            "grade": grade,
            "suggestions": suggestions,
        }

    def _add_case(self, case: dict) -> dict:
        if not self.db:
            return {"action": "add_case", "status": "no_db"}
        cid = case.get("case_id") or hashlib.md5(
            (case.get("title", "") + case.get("method_id", "")).encode()
        ).hexdigest()[:12]
        row = {"case_id": cid, "created_at": datetime.now(), **case}
        self.db.insert("cases", row)
        return {"action": "add_case", "case_id": cid, "status": "added"}

    def _add_knowledge(self, nodes: list[dict], edges: list[dict]) -> dict:
        if not self.db:
            return {"action": "add_knowledge", "status": "no_db"}
        n_count = 0
        for n in nodes:
            nid = n.get("node_id") or hashlib.md5(
                (n.get("name", "") + n.get("node_type", "")).encode()
            ).hexdigest()[:12]
            row = {"node_id": nid, "tags": n.get("tags", []),
                   "meta": n.get("meta", {})}
            row.update({k: v for k, v in n.items() if k not in ("tags", "meta")})
            self.db.insert("nodes", row)
            n_count += 1
        e_count = 0
        for e in edges:
            eid = e.get("edge_id") or hashlib.md5(
                (e.get("from_id", "") + e.get("to_id", "") + e.get("relation", "")).encode()
            ).hexdigest()[:12]
            row = {"edge_id": eid, "weight": e.get("weight", 1.0)}
            row.update({k: v for k, v in e.items() if k != "weight"})
            self.db.insert("edges", row)
            e_count += 1
        self._build_kg_index()
        return {"action": "add_knowledge", "nodes_added": n_count,
                "edges_added": e_count}
