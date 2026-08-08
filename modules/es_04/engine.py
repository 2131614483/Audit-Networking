"""[kg_gnn] ES-04 知识图谱绿色漂洗检测平台。

纯 stdlib 实现的绿色漂洗检测引擎：
  - _load_model  : 声明/证据/标准 实体关系模式 + 模糊词库 + 矛盾检测规则 + 可信度权重
  - _preprocess  : 输入声明文本 + 多源证据，抽取实体并构建声明-证据知识图谱
  - _infer       : 声明可信度评估 → 多源交叉验证 → 矛盾检测 → 漂洗风险评分
  - _postprocess : 输出检测报告（声明列表+可信度+验证状态+矛盾对+漂洗证据链）
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from datetime import datetime

from modules.shared.base_engine import AbstractEngine


_FUZZY_WORDS = {
    "显著": 0.3, "大幅": 0.25, "大幅提升": 0.15, "全面": 0.4, "领先": 0.35,
    "先进": 0.3, "一流": 0.4, "高效": 0.2, "优良": 0.2, "良好": 0.15,
    "积极": 0.2, "持续": 0.15, "不断": 0.15, "稳步": 0.15, "显著提升": 0.3,
    "大幅下降": 0.25, "行业领先": 0.35, "国际先进": 0.4, "业内领先": 0.35,
}

_QUANTIFIABLE_PATTERNS = [
    r"([\d.,]+)\s*(%|％|吨|kg|tCO2|kWh|GJ|m3|ha|万|亿)",
    r"(?:下降|降低|减少)[^0-9]{0,10}([\d.,]+)\s*(?:%|％|吨|kg)",
    r"(?:达到|占比|覆盖率)[^0-9]{0,10}([\d.,]+)\s*(?:%|％)",
    r"(?:承诺|目标|计划)[^0-9]{0,20}(20\d{2})",
    r"(?:ISO|ISSB|GRI|SASB|TCFD)\s*[\d\-A-Z]+",
]

_CONTRADICTION_RULES = [
    {"kw": "减排", "neg_kw": "排放", "neg_pattern": "上升", "min_delta": 0.15},
    {"kw": "绿化|森林|生态恢复", "neg_kw": "毁林|砍伐|面积减少", "min_delta": 0.05},
    {"kw": "节水|水资源保护", "neg_kw": "取水增加|用水量上升", "min_delta": 0.10},
    {"kw": "零废弃|循环利用", "neg_kw": "废弃物总量|填埋量", "neg_pattern": "上升", "min_delta": 0.10},
]

_EVIDENCE_SOURCE_WEIGHTS = {
    "卫星数据": 1.0, "政府监管": 1.0, "IoT传感器": 1.0,
    "第三方评级": 0.90, "新闻舆情": 0.55, "企业自报": 0.50,
    "行业数据": 0.70, "认证机构": 0.85,
}

_CLAIM_CATEGORIES = {
    "排放声明": ["排放", "减排", "CO2", "GHG", "碳", "温室气体", "碳中和", "净零"],
    "能源声明": ["能源", "可再生", "绿电", "能效", "节能"],
    "水资源声明": ["水", "取水量", "节水", "保护水资源"],
    "废弃物声明": ["废弃物", "固废", "循环", "零废弃", "填埋"],
    "生物多样性声明": ["生物多样性", "生态", "栖息地", "恢复", "造林"],
    "供应链声明": ["供应商", "链", "绿色采购", "可持续采购"],
    "认证声明": ["ISO", "认证", "标准", "GRI", "ISSB", "SASB", "TCFD"],
    "承诺声明": ["承诺", "目标", "计划", "将于", "力争"],
}


class KGEngine(AbstractEngine):
    """ES-04 知识图谱绿色漂洗检测引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.fuzzy_words = {}
        self.quant_patterns = []
        self.contradiction_rules = []
        self.source_weights = {}
        self.category_keywords = {}

    def _load_model(self):
        self.fuzzy_words = dict(_FUZZY_WORDS)
        self.quant_patterns = list(_QUANTIFIABLE_PATTERNS)
        self.contradiction_rules = list(_CONTRADICTION_RULES)
        self.source_weights = dict(_EVIDENCE_SOURCE_WEIGHTS)
        self.category_keywords = {
            cat: [re.compile(k) for k in kws]
            for cat, kws in _CLAIM_CATEGORIES.items()
        }

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        prepared_claims = []
        all_evidence = []
        for it in items:
            claims = it.get("claims") or ([{"text": it.get("claim_text", str(it))}] if isinstance(it, dict) else [{"text": str(it)}])
            evidence = it.get("evidence", [])
            source_meta = it.get("source", "企业自报")
            for c in claims:
                if isinstance(c, str):
                    c = {"text": c, "source": source_meta}
                c_text = c.get("text", "")
                prepared_claims.append({
                    "text": c_text,
                    "source": c.get("source", source_meta),
                    "channel": c.get("channel", "ESG报告"),
                    "date": c.get("date", ""),
                    "entity": it.get("entity", c.get("entity", "")),
                    "category": self._classify_claim(c_text),
                    "company": it.get("company", ""),
                })
            for ev in evidence:
                if isinstance(ev, dict):
                    all_evidence.append({
                        "type": ev.get("type", "generic"),
                        "description": ev.get("description", ""),
                        "source": ev.get("source", "第三方"),
                        "supports": ev.get("supports", True),
                        "related_metric": ev.get("metric", ev.get("indicator", "")),
                        "value": ev.get("value"),
                        "unit": ev.get("unit", ""),
                        "date": ev.get("date", ""),
                    })
        return {"claims": prepared_claims, "evidence": all_evidence}

    def _classify_claim(self, text: str) -> str:
        for cat, patterns in self.category_keywords.items():
            for pat in patterns:
                if pat.search(text):
                    return cat
        return "其他声明"

    def _infer(self, prepared):
        kg = self._build_graph(prepared["claims"], prepared["evidence"])
        claim_evaluations = []
        for c in prepared["claims"]:
            ev_result = self._evaluate_claim(c, kg, prepared["evidence"])
            claim_evaluations.append(ev_result)
        contradictions = self._detect_contradictions(claim_evaluations, prepared["evidence"])
        evidence_conflict = self._cross_validate(claim_evaluations, prepared["evidence"])
        overall_risk = self._aggregate_risk(claim_evaluations, contradictions, evidence_conflict)
        return {
            "knowledge_graph": kg,
            "claim_evaluations": claim_evaluations,
            "contradictions": contradictions,
            "evidence_conflict": evidence_conflict,
            "overall_risk": overall_risk,
            "generated_at": datetime.now().isoformat(),
        }

    def _build_graph(self, claims: list, evidence: list) -> dict:
        nodes = []
        edges = []
        claim_ids = {}
        for idx, c in enumerate(claims):
            cid = f"C{idx:03d}"
            claim_ids[cid] = c
            nodes.append({"id": cid, "type": "Claim", "label": c["text"][:40],
                          "category": c["category"], "source": c["source"]})
        ev_nodes = {}
        for idx, ev in enumerate(evidence):
            eid = f"E{idx:03d}"
            ev_nodes[eid] = ev
            nodes.append({"id": eid, "type": "Evidence", "label": ev.get("description", "")[:40],
                          "source": ev.get("source", ""), "supports": ev.get("supports", True)})
        for cid, c in claim_ids.items():
            matched_ev = self._match_evidence(c, evidence)
            for eid, ev in matched_ev.items():
                rel = "证据支持" if ev.get("supports", True) else "证据反驳"
                edges.append({"from": eid, "to": cid, "type": rel,
                              "weight": self.source_weights.get(ev.get("source", ""), 0.5)})
        for i in range(len(claim_ids)):
            for j in range(i + 1, len(claim_ids)):
                ci = list(claim_ids.values())[i]
                cj = list(claim_ids.values())[j]
                sim = difflib.SequenceMatcher(None, ci["text"], cj["text"]).ratio()
                if 0.3 < sim < 0.85 and ci["category"] == cj["category"]:
                    edges.append({"from": f"C{i:03d}", "to": f"C{j:03d}", "type": "相似声明",
                                  "similarity": round(sim, 3)})
        return {"nodes": nodes, "edges": edges, "claim_ids": claim_ids}

    def _match_evidence(self, claim: dict, evidence: list) -> dict:
        matched = {}
        claim_text = claim["text"].lower()
        claim_cat = claim["category"]
        for idx, ev in enumerate(evidence):
            e_desc = ev.get("description", "").lower()
            e_metric = ev.get("related_metric", "").lower()
            score = 0.0
            for pat in self.category_keywords.get(claim_cat, []):
                if pat.search(e_desc) or pat.search(e_metric):
                    score += 0.4
            words = set(re.findall(r"[\u4e00-\u9fff]+|\w+", claim_text))
            e_words = set(re.findall(r"[\u4e00-\u9fff]+|\w+", e_desc + " " + e_metric))
            overlap = words & e_words
            if overlap:
                score += min(0.6, len(overlap) * 0.1)
            if score > 0.2:
                matched[f"E{idx:03d}"] = ev
        return matched

    def _evaluate_claim(self, claim: dict, kg: dict, evidence: list) -> dict:
        text = claim["text"]
        fuzzy_score = self._fuzzy_word_penalty(text)
        quant_count = self._count_quantifiable(text)
        quant_score = min(1.0, quant_count * 0.4)
        verifiability = self._assess_verifiability(text, claim["category"])
        channel_score = self._channel_consistency(claim, kg["claim_ids"])
        ev_match = self._match_evidence(claim, evidence)
        ev_support = sum(self.source_weights.get(e.get("source", ""), 0.5)
                         for e in ev_match.values() if e.get("supports", True))
        ev_contradict = sum(self.source_weights.get(e.get("source", ""), 0.5)
                            for e in ev_match.values() if not e.get("supports", True))
        if not ev_match:
            evidence_factor = 0.4
        elif ev_support + ev_contradict == 0:
            evidence_factor = 0.5
        else:
            evidence_factor = max(0.0, (ev_support - ev_contradict) / (ev_support + ev_contradict))
        credibility = (
            0.35 * quant_score
            + 0.25 * verifiability
            + 0.20 * evidence_factor
            + 0.10 * channel_score
            + 0.10 * (1 - fuzzy_score)
        )
        credibility = min(1.0, max(0.0, credibility))
        risk = 1.0 - credibility
        return {
            "claim_id": f"C{list(kg['claim_ids'].values()).index(claim):03d}",
            "claim_text": text,
            "category": claim["category"],
            "source": claim["source"],
            "credibility": round(credibility, 3),
            "risk_score": round(risk, 3),
            "verdict": self._risk_label(risk),
            "metrics": {
                "quantifiability": round(quant_score, 3),
                "fuzzy_penalty": round(fuzzy_score, 3),
                "verifiability": round(verifiability, 3),
                "evidence_support": round(evidence_factor, 3),
                "channel_consistency": round(channel_score, 3),
                "supporting_evidence_count": sum(1 for e in ev_match.values() if e.get("supports", True)),
                "contradicting_evidence_count": sum(1 for e in ev_match.values() if not e.get("supports", True)),
            },
            "matched_evidence_ids": list(ev_match.keys()),
        }

    def _fuzzy_word_penalty(self, text: str) -> float:
        text_lower = text.lower()
        penalty = 0.0
        for word, p in self.fuzzy_words.items():
            if word.lower() in text_lower:
                penalty += p
        return min(1.0, penalty)

    def _count_quantifiable(self, text: str) -> int:
        count = 0
        for pat in self.quant_patterns:
            count += len(re.findall(pat, text, re.IGNORECASE))
        return count

    def _assess_verifiability(self, text: str, category: str) -> float:
        score = 0.3
        if self._count_quantifiable(text) > 0:
            score += 0.25
        if any(kw in text for kw in ("%", "吨", "kg", "kWh", "GJ", "m3", "ha", "万", "亿")):
            score += 0.15
        if re.search(r"20\d{2}", text):
            score += 0.15
        if category in ("排放声明", "能源声明", "水资源声明"):
            score += 0.10
        if category == "认证声明":
            score += 0.25
        return min(1.0, score)

    def _channel_consistency(self, claim: dict, all_claims: dict) -> float:
        cat = claim["category"]
        same_cat = [c for c in all_claims.values() if c["category"] == cat]
        if len(same_cat) <= 1:
            return 0.6
        texts = [c["text"] for c in same_cat]
        ref = claim["text"]
        avg_sim = statistics_mean([
            difflib.SequenceMatcher(None, ref, t).ratio() for t in texts if t != ref
        ]) if len(texts) > 1 else 0.5
        if avg_sim > 0.6:
            return 0.9
        if avg_sim > 0.3:
            return 0.6
        return 0.3

    def _detect_contradictions(self, evaluations: list, evidence: list) -> list:
        contradictions = []
        claim_texts = {ev["claim_id"]: ev["claim_text"] for ev in evaluations}
        texts_lower = [(cid, t.lower()) for cid, t in claim_texts.items()]
        for i in range(len(texts_lower)):
            for j in range(i + 1, len(texts_lower)):
                ci, ti = texts_lower[i]
                cj, tj = texts_lower[j]
                for rule in self.contradiction_rules:
                    kws = rule["kw"].split("|")
                    neg_kws = rule["neg_kw"].split("|")
                    a_has = any(k.lower() in ti for k in kws)
                    b_neg = any(k.lower() in tj for k in neg_kws)
                    b_has = any(k.lower() in tj for k in kws)
                    a_neg = any(k.lower() in ti for k in neg_kws)
                    if (a_has and b_neg) or (b_has and a_neg):
                        contradictions.append({
                            "claim_a_id": ci,
                            "claim_b_id": cj,
                            "claim_a_text": claim_texts[ci][:80],
                            "claim_b_text": claim_texts[cj][:80],
                            "rule": rule["kw"],
                            "severity": "高",
                            "type": "声明间矛盾",
                        })
        return contradictions

    def _cross_validate(self, evaluations: list, evidence: list) -> list:
        conflicts = []
        metric_groups = defaultdict(list)
        for ev in evidence:
            m = ev.get("related_metric", ev.get("type", ""))
            if m:
                metric_groups[m].append(ev)
        for metric, ev_list in metric_groups.items():
            supporting = [e for e in ev_list if e.get("supports", True)]
            contradicting = [e for e in ev_list if not e.get("supports", True)]
            if supporting and contradicting:
                src_support = Counter(e.get("source", "") for e in supporting)
                src_contradict = Counter(e.get("source", "") for e in contradicting)
                conflicts.append({
                    "metric": metric,
                    "supporting_sources": dict(src_support),
                    "contradicting_sources": dict(src_contradict),
                    "conflict_level": "高" if len(contradicting) >= len(supporting) else "中",
                    "type": "证据源冲突",
                })
        return conflicts

    def _aggregate_risk(self, evaluations: list, contradictions: list, conflicts: list) -> dict:
        if not evaluations:
            return {"level": "数据不足", "score": 0.0}
        avg_risk = statistics_mean([e["risk_score"] for e in evaluations])
        max_risk = max(e["risk_score"] for e in evaluations)
        contr_penalty = min(0.3, len(contradictions) * 0.06)
        conflict_penalty = min(0.2, len(conflicts) * 0.05)
        score = avg_risk + 0.3 * max_risk + contr_penalty + conflict_penalty
        score = min(1.0, score)
        if score > 0.7:
            level = "高风险-绿色漂洗嫌疑显著"
        elif score > 0.45:
            level = "中风险-部分声明需验证"
        elif score > 0.25:
            level = "低风险-声明整体可信"
        else:
            level = "极低风险"
        return {
            "level": level,
            "score": round(score, 3),
            "avg_claim_risk": round(avg_risk, 3),
            "max_claim_risk": round(max_risk, 3),
            "contradiction_count": len(contradictions),
            "evidence_conflict_count": len(conflicts),
        }

    @staticmethod
    def _risk_label(risk: float) -> str:
        if risk > 0.7:
            return "高风险-显著疑点"
        if risk > 0.5:
            return "中风险-需验证"
        if risk > 0.3:
            return "低风险-基本可信"
        return "极低风险"

    def _postprocess(self, result):
        evals = result["claim_evaluations"]
        by_category = defaultdict(list)
        for e in evals:
            by_category[e["category"]].append(e["credibility"])
        cat_stats = {}
        for cat, creds in by_category.items():
            cat_stats[cat] = {
                "count": len(creds),
                "avg_credibility": round(statistics_mean(creds), 3),
                "min_credibility": round(min(creds), 3),
                "high_risk_count": sum(1 for c in creds if c < 0.3),
            }
        high_risk_claims = [e for e in evals if e["risk_score"] > 0.6]
        return {
            "overall_risk": result["overall_risk"],
            "high_risk_claims": high_risk_claims,
            "all_claim_evaluations": evals,
            "category_statistics": cat_stats,
            "contradictions": result["contradictions"],
            "evidence_conflicts": result["evidence_conflict"],
            "knowledge_graph_summary": {
                "node_count": len(result["knowledge_graph"]["nodes"]),
                "edge_count": len(result["knowledge_graph"]["edges"]),
            },
            "generated_at": datetime.now().isoformat(),
        }


def statistics_mean(values: list) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
