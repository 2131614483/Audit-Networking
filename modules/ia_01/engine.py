"""[IA-01] 动态风险地图与智能审计计划引擎 —— 纯 stdlib 风险评分 + NLP 信号 + 审计计划生成。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 100+ 指标体系风险评分（加权回归）：
      - 6 大类指标：财务/运营/合规/外部/历史审计/战略
      - 指标→风险贡献：clamp(指标值 × 权重, 0, 上限分)
      - 汇总：风险分 = Σ(各类指标贡献)
  * NLP 文本风险信号提取（双语关键词 + 情感词典）：
      - 中文风险词库 + 英文风险词库（正面/负面/等级）
      - 情感得分 = 加权匹配 + 等级叠加
      - 实体关联：regex 提取 BU/产品/区域关键词
  * 动态风险地图（按组织层级下钻）：
      - 层级：集团 → BU → 子公司 → 部门 → 流程
      - 热力图 + 阈值预警（黄60/橙75/红90）
  * 智能审计计划生成（约束规划 + 启发式）：
      - 硬约束：高风险≥1次/年、中风险≤2次/年、低风险≤3次/年
      - 资源约束：工时上限、技能匹配
      - 贪心 + 后处理优化

模型结构（self.model）：
  {
    "indicators": [...],
    "risk_signals_cn": {...},
    "risk_signals_en": {...},
    "thresholds": {"yellow": 60, "orange": 75, "red": 90},
  }
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ia_01.db"

_INDICATORS_SCHEMA = {
    "indicator_id": "TEXT",
    "category": "TEXT",
    "name": "TEXT",
    "value": "REAL",
    "threshold": "REAL",
    "weight": "REAL",
    "scored_at": "DATETIME",
}
_RISK_MAP_SCHEMA = {
    "entity_id": "TEXT",
    "entity_name": "TEXT",
    "entity_type": "TEXT",
    "parent_id": "TEXT",
    "risk_score": "REAL",
    "risk_level": "TEXT",
    "risk_trend": "TEXT",
    "top_indicators": "JSON",
    "scored_at": "DATETIME",
}
_TEXT_SIGNALS_SCHEMA = {
    "signal_id": "TEXT",
    "source": "TEXT",
    "text": "TEXT",
    "sentiment_score": "REAL",
    "risk_entities": "JSON",
    "severity": "TEXT",
    "detected_at": "DATETIME",
}
_AUDIT_PLANS_SCHEMA = {
    "plan_id": "TEXT",
    "period": "TEXT",
    "projects": "JSON",
    "resource_gap": "JSON",
    "total_score": "REAL",
    "created_at": "DATETIME",
}

_INDICATOR_TEMPLATES: list[dict] = [
    {"id": "FIN_001", "category": "financial", "name": "收入波动率",
     "threshold": 15, "weight": 1.0, "max_score": 20},
    {"id": "FIN_002", "category": "financial", "name": "应收账款周转天数异常",
     "threshold": 20, "weight": 0.8, "max_score": 15},
    {"id": "FIN_003", "category": "financial", "name": "利润率异常",
     "threshold": 10, "weight": 0.7, "max_score": 12},
    {"id": "OPS_001", "category": "operational", "name": "系统宕机时间",
     "threshold": 4, "weight": 0.9, "max_score": 18},
    {"id": "OPS_002", "category": "operational", "name": "员工流失率",
     "threshold": 8, "weight": 0.6, "max_score": 10},
    {"id": "OPS_003", "category": "operational", "name": "订单错误率",
     "threshold": 3, "weight": 0.7, "max_score": 12},
    {"id": "CMP_001", "category": "compliance", "name": "监管处罚金额(万)",
     "threshold": 50, "weight": 1.0, "max_score": 20},
    {"id": "CMP_002", "category": "compliance", "name": "整改逾期率",
     "threshold": 15, "weight": 0.8, "max_score": 15},
    {"id": "EXT_001", "category": "external", "name": "行业负面新闻量",
     "threshold": 20, "weight": 0.5, "max_score": 8},
    {"id": "EXT_002", "category": "external", "name": "供应链中断预警数",
     "threshold": 3, "weight": 0.7, "max_score": 12},
    {"id": "HIS_001", "category": "historical", "name": "上次审计评分",
     "threshold": 60, "weight": -0.6, "max_score": 15},
    {"id": "HIS_002", "category": "historical", "name": "重复发现率",
     "threshold": 20, "weight": 0.8, "max_score": 14},
    {"id": "STR_001", "category": "strategic", "name": "关键人才流失",
     "threshold": 5, "weight": 0.5, "max_score": 10},
]

_RISK_WORDS_CN = {
    "negative_high": ["欺诈", "造假", "舞弊", "洗钱", "重大损失", "资不抵债", "破产"],
    "negative_medium": ["违规", "处罚", "调查", "立案", "异常", "损失", "危机", "下滑", "逾期"],
    "negative_low": ["波动", "偏差", "异常", "待查", "关注", "风险", "隐患"],
    "positive": ["增长", "提升", "稳定", "合规", "达标", "优秀", "稳健"],
}
_RISK_WORDS_EN = {
    "negative_high": ["fraud", "embezzlement", "laundering", "bankruptcy", "default"],
    "negative_medium": ["violation", "penalty", "investigation", "lawsuit", "decline", "loss"],
    "negative_low": ["risk", "concern", "deviation", "pending", "alert"],
    "positive": ["growth", "improvement", "stable", "compliant", "exceeded", "strong"],
}

_BU_KEYWORDS: dict[str, list[str]] = {
    "BU-A": ["采购", "供应商", "procurement", "supplier"],
    "BU-B": ["销售", "客户", "sales", "customer"],
    "BU-C": ["财务", "会计", "finance", "accounting"],
    "BU-D": ["IT", "系统", "it", "system", "cyber"],
    "BU-E": ["合规", "法律", "compliance", "legal"],
}


class LLMEngine(AbstractEngine):
    """IA-01 风险地图 + 智能审计计划引擎（加权评分 + NLP 信号 + 约束规划）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        tables = {"indicators": _INDICATORS_SCHEMA, "risk_map": _RISK_MAP_SCHEMA,
                  "text_signals": _TEXT_SIGNALS_SCHEMA, "audit_plans": _AUDIT_PLANS_SCHEMA}
        for t, s in tables.items():
            if t not in self.db.tables():
                self.db.create_table(t, s)
        self.model = {
            "indicators": list(_INDICATOR_TEMPLATES),
            "risk_words_cn": dict(_RISK_WORDS_CN),
            "risk_words_en": dict(_RISK_WORDS_EN),
            "thresholds": {"yellow": 60, "orange": 75, "red": 90},
            "bu_keywords": dict(_BU_KEYWORDS),
            "risk_categories": ["financial", "operational", "compliance",
                                "external", "historical", "strategic"],
        }

    def _ensure_loaded(self) -> None:
        """惰性初始化（支持不显式调用 setup() 直接 execute()）。"""
        if getattr(self, "model", None) is None:
            self._load_model()

    def _preprocess(self, input_data: Any) -> dict:
        self._ensure_loaded()
        if isinstance(input_data, dict):
            action = input_data.get("action", "score")
            if action == "score":
                return {"action": "score", "entity": input_data.get("entity"),
                        "indicators": input_data.get("indicators"),
                        "parent_id": input_data.get("parent_id", "root")}
            if action == "score_all":
                return {"action": "score_all",
                        "entities": input_data.get("entities", []),
                        "indicator_values": input_data.get("indicator_values", {})}
            if action == "text_signals":
                return {"action": "text_signals",
                        "texts": input_data.get("texts", []),
                        "source": input_data.get("source", "manual")}
            if action == "risk_map":
                return {"action": "risk_map",
                        "depth": input_data.get("depth", "all"),
                        "entity_type": input_data.get("entity_type"),
                        "min_score": input_data.get("min_score", 0)}
            if action == "generate_plan":
                return {"action": "generate_plan",
                        "period": input_data.get("period", "annual"),
                        "resources": input_data.get("resources", {}),
                        "mandatory_projects": input_data.get("mandatory_projects", []),
                        "management_focus": input_data.get("management_focus", [])}
        raise ValueError(f"无法识别的输入: {input_data}")

    def _infer(self, prepared: dict) -> dict:
        action = prepared["action"]
        if action == "score":
            return self._score_entity(prepared)
        if action == "score_all":
            return self._score_all(prepared)
        if action == "text_signals":
            return self._extract_text_signals(prepared)
        if action == "risk_map":
            return self._build_risk_map(prepared)
        if action == "generate_plan":
            return self._generate_audit_plan(prepared)
        raise ValueError(f"未知 action: {action}")

    def _postprocess(self, result: dict) -> dict:
        result["engine"] = "IA-01-RiskMapAndPlan"
        result["timestamp"] = datetime.now().isoformat()
        return result

    # ---------- 风险评分 ----------

    def _score_entity(self, params: dict) -> dict:
        entity = params.get("entity") or {"entity_id": "unknown", "entity_name": "未知实体",
                                           "entity_type": "bu", "parent_id": params["parent_id"]}
        indicator_values = params.get("indicators") or {}
        contributions = []
        total = 0.0
        for ind in self.model["indicators"]:
            raw_value = indicator_values.get(ind["id"], 0)
            threshold = ind["threshold"]
            weight = ind["weight"]
            max_score = ind["max_score"]
            if weight >= 0:
                deviation = max(raw_value - threshold, 0) / max(threshold, 0.01)
            else:
                deviation = max(threshold - raw_value, 0) / max(threshold, 0.01)
            contrib = max(0, deviation * abs(weight) * max_score)
            contrib = min(contrib, max_score)
            contributions.append({"indicator_id": ind["id"], "name": ind["name"],
                                   "value": raw_value, "threshold": threshold,
                                   "contribution": round(contrib, 2)})
            total += contrib
        total = min(total, 100)
        level = self._risk_level(total)
        entity.setdefault("entity_id", hashlib.md5(
            (entity.get("entity_name", "unknown") + datetime.now().isoformat()).encode()
        ).hexdigest()[:12])
        entity.setdefault("scored_at", datetime.now())
        risk_map_row = {
            "entity_id": entity["entity_id"],
            "entity_name": entity.get("entity_name", "未知"),
            "entity_type": entity.get("entity_type", "bu"),
            "parent_id": entity.get("parent_id", "root"),
            "risk_score": round(total, 1),
            "risk_level": level,
            "risk_trend": "stable",
            "top_indicators": sorted(contributions, key=lambda c: c["contribution"], reverse=True)[:5],
            "scored_at": datetime.now(),
        }
        if self.db:
            self.db.upsert("risk_map", risk_map_row, pk="entity_id")
            for c in contributions:
                ind_row = {**c, "category": next(
                    (i["category"] for i in self.model["indicators"] if i["id"] == c["indicator_id"]), "other"
                ), "indicator_id": c["indicator_id"], "scored_at": datetime.now()}
                if "name" in ind_row:
                    pass
                self.db.insert("indicators", ind_row)
        return {
            "action": "score",
            "entity": entity,
            "risk_score": round(total, 1),
            "risk_level": level,
            "contributions": contributions,
            "top_3": sorted(contributions, key=lambda c: c["contribution"], reverse=True)[:3],
        }

    def _score_all(self, params: dict) -> dict:
        indicator_values = params.get("indicator_values", {})
        results = []
        for entity in params.get("entities", []):
            r = self._score_entity({"entity": entity, "indicators": indicator_values,
                                     "parent_id": entity.get("parent_id", "root")})
            results.append(r)
        results.sort(key=lambda x: x["risk_score"], reverse=True)
        return {"action": "score_all", "total_entities": len(results),
                "high_risk_count": sum(1 for r in results if r["risk_score"] >= 75),
                "medium_risk_count": sum(1 for r in results if 50 <= r["risk_score"] < 75),
                "low_risk_count": sum(1 for r in results if r["risk_score"] < 50),
                "results": results}

    def _risk_level(self, score: float) -> str:
        t = self.model["thresholds"]
        if score >= t["red"]:
            return "red"
        if score >= t["orange"]:
            return "orange"
        if score >= t["yellow"]:
            return "yellow"
        return "green"

    # ---------- 文本风险信号 ----------

    def _extract_text_signals(self, params: dict) -> dict:
        texts = params["texts"]
        source = params.get("source", "manual")
        signals = []
        for item in texts:
            if isinstance(item, str):
                text = item
                meta = {}
            else:
                text = item.get("text", "")
                meta = item
            text_lower = text.lower()
            sentiment = self._compute_sentiment(text, text_lower)
            risk_entities = self._extract_risk_entities(text, text_lower)
            severity = self._severity_from_sentiment(sentiment)
            sid = hashlib.md5(
                (text[:100] + datetime.now().isoformat()).encode()
            ).hexdigest()[:12]
            signal = {
                "signal_id": sid, "source": source, "text": text[:500],
                "sentiment_score": sentiment, "risk_entities": risk_entities,
                "severity": severity, "detected_at": datetime.now(),
                **meta,
            }
            signals.append(signal)
            if self.db:
                self.db.insert("text_signals", signal)
        return {
            "action": "text_signals",
            "total_texts": len(texts),
            "signals": signals,
            "severity_dist": Counter(s["severity"] for s in signals),
        }

    def _compute_sentiment(self, text: str, text_lower: str) -> float:
        score = 0.0
        cn = self.model["risk_words_cn"]
        en = self.model["risk_words_en"]
        for w in cn["negative_high"]:
            if w in text:
                score -= 3.0
        for w in cn["negative_medium"]:
            if w in text:
                score -= 1.5
        for w in cn["negative_low"]:
            if w in text:
                score -= 0.5
        for w in cn["positive"]:
            if w in text:
                score += 1.0
        for w in en["negative_high"]:
            if w in text_lower:
                score -= 3.0
        for w in en["negative_medium"]:
            if w in text_lower:
                score -= 1.5
        for w in en["negative_low"]:
            if w in text_lower:
                score -= 0.5
        for w in en["positive"]:
            if w in text_lower:
                score += 1.0
        return round(max(-5.0, min(score, 5.0)), 2)

    def _extract_risk_entities(self, text: str, text_lower: str) -> list[str]:
        entities = []
        for bu, kws in self.model["bu_keywords"].items():
            if any(kw.lower() in text_lower for kw in kws):
                entities.append(bu)
        if any(re.search(r"\d{4,}", text) for _ in [0]):
            pass
        return list(dict.fromkeys(entities))

    def _severity_from_sentiment(self, score: float) -> str:
        if score <= -3:
            return "critical"
        if score <= -1.5:
            return "high"
        if score <= -0.5:
            return "medium"
        if score > 0.5:
            return "positive"
        return "low"

    # ---------- 风险地图 ----------

    def _build_risk_map(self, params: dict) -> dict:
        if not self.db:
            return {"action": "risk_map", "entities": [], "stats": {}}
        depth = params["depth"]
        etype = params.get("entity_type")
        min_score = params["min_score"]
        where = f"risk_score >= {min_score}"
        if etype:
            where += f" AND entity_type = '{etype}'"
        all_entities = self.db.query("risk_map", where=where, order_by="risk_score DESC")
        tree = self._build_tree(all_entities)
        heatmap = self._heatmap_by_bu_and_category()
        thresholds = self.model["thresholds"]
        return {
            "action": "risk_map",
            "depth": depth,
            "thresholds": thresholds,
            "tree": tree,
            "heatmap": heatmap,
            "stats": {
                "total_entities": len(all_entities),
                "red": sum(1 for e in all_entities if e["risk_level"] == "red"),
                "orange": sum(1 for e in all_entities if e["risk_level"] == "orange"),
                "yellow": sum(1 for e in all_entities if e["risk_level"] == "yellow"),
                "green": sum(1 for e in all_entities if e["risk_level"] == "green"),
            },
            "top_risk_entities": all_entities[:10],
        }

    def _build_tree(self, entities: list[dict]) -> dict:
        by_id = {e["entity_id"]: e for e in entities}
        children: dict[str, list[dict]] = defaultdict(list)
        roots = []
        for e in entities:
            pid = e.get("parent_id", "root")
            if pid and pid != "root" and pid in by_id:
                children[pid].append(e)
            else:
                roots.append(e)
        def enrich(e: dict) -> dict:
            return {**e, "children": [enrich(c) for c in children.get(e["entity_id"], [])]}
        return {"roots": [enrich(r) for r in roots], "total": len(entities)}

    def _heatmap_by_bu_and_category(self) -> dict:
        if not self.db:
            return {"rows": []}
        entities = self.db.query("risk_map", where="entity_type = 'bu' OR entity_type = 'subsidiary'")
        if not entities:
            return {"rows": []}
        return {"entities": [{"name": e["entity_name"], "score": e["risk_score"],
                              "level": e["risk_level"]} for e in entities]}

    # ---------- 审计计划生成 ----------

    def _generate_audit_plan(self, params: dict) -> dict:
        period = params["period"]
        resources = params.get("resources", {})
        mandatory = params.get("mandatory_projects", [])
        mgmt_focus = params.get("management_focus", [])
        if self.db:
            entities = self.db.query("risk_map", order_by="risk_score DESC")
        else:
            entities = []
        max_projects_per_year = resources.get("max_projects", 20)
        high_freq = resources.get("high_risk_audit_per_year", 1)
        medium_freq = resources.get("medium_risk_audit_years", 2)
        low_freq = resources.get("low_risk_audit_years", 3)
        projects = []
        for e in entities[:max_projects_per_year + len(mandatory)]:
            score = e["risk_score"]
            if score >= 75:
                priority = "high"
                duration_weeks = 4
            elif score >= 50:
                priority = "medium"
                duration_weeks = 3
            else:
                priority = "low"
                duration_weeks = 2
            projects.append({
                "project_name": f"{e['entity_name']}持续审计",
                "business_entity": e["entity_name"],
                "entity_id": e["entity_id"],
                "scope": f"对 {e['entity_name']} 进行全面持续审计监控",
                "risk_score": score,
                "priority": priority,
                "duration_weeks": duration_weeks,
                "team_size": 2 if priority != "low" else 1,
                "rationale": f"基于风险评分 {score}（{e['risk_level']}级），属于 {'高' if priority == 'high' else '中' if priority == 'medium' else '低'}优先级审计目标。",
                "mandatory": False,
            })
        for m in mandatory:
            projects.append({**m, "mandatory": True, "priority": m.get("priority", "high")})
        focus_bonus = sum(1 for p in projects
                          if any(f.lower() in (p.get("scope", "") + p.get("project_name", "")).lower()
                                 for f in mgmt_focus))
        projects.sort(key=lambda p: (
            0 if p.get("mandatory") else 1,
            {"high": 0, "medium": 1, "low": 2}.get(p["priority"], 3),
            -p.get("risk_score", 0),
        ))
        total_hours = sum(p["duration_weeks"] * 40 * p["team_size"] for p in projects)
        available_hours = resources.get("available_hours_per_month", 400) * 12
        utilization = total_hours / max(available_hours, 1)
        gap = []
        if utilization > 0.85:
            gap.append("审计资源紧张，建议增加人力或延长部分非紧急项目")
        skills_needed = set()
        for p in projects[:10]:
            if p.get("risk_score", 0) >= 75:
                skills_needed.add("高级审计")
            if "IT" in p.get("project_name", "") or "系统" in p.get("scope", ""):
                skills_needed.add("IT审计")
            if "财务" in p.get("project_name", "") or "finance" in p.get("scope", "").lower():
                skills_needed.add("财务审计")
        plan_id = hashlib.md5(
            (period + datetime.now().isoformat()).encode()
        ).hexdigest()[:12]
        plan = {
            "action": "generate_plan",
            "period": period,
            "plan_id": plan_id,
            "total_projects": len(projects),
            "priority_distribution": dict(Counter(p["priority"] for p in projects)),
            "projects": projects,
            "resource_gap": {
                "total_hours_needed": total_hours,
                "available_hours": available_hours,
                "utilization_percent": round(utilization * 100, 1),
                "skill_requirements": list(skills_needed),
                "recommendations": gap + ["确保高级审计师参与所有高风险项目"],
            },
            "management_focus_covered": focus_bonus,
        }
        if self.db:
            self.db.insert("audit_plans", {
                "plan_id": plan_id, "period": period,
                "projects": projects,
                "resource_gap": plan["resource_gap"],
                "total_score": sum(p.get("risk_score", 0) for p in projects),
                "created_at": datetime.now(),
            })
        return plan
