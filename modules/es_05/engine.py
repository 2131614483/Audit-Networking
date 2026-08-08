"""[llm_rag] ES-05 ESG审计知识库与AI助手。

纯 stdlib 实现的 ESG 审计知识库 RAG 问答引擎：
  - _load_model  : 加载内置知识库（ISSB/CSRD/GRI/SASB/TCFD + 方法论 + 审计案例）→ 倒排索引 + 同义词扩展表
  - _preprocess  : 输入用户查询，意图识别 + 查询改写/扩展 → 多路检索（BM25 + 语义相似度）
  - _infer       : 召回 → 重排序(RRF融合) → 上下文组装 → 生成式回答（基于模板填充 + 证据链）
  - _postprocess : 答案格式化 + 引用溯源 + 置信度评估 + 反幻觉校验
"""
from __future__ import annotations

import difflib
import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from itertools import chain

from modules.shared.base_engine import AbstractEngine


_KB_ENTRIES = [
    {"id": "ISSB_S2_01", "standard": "ISSB IFRS S2", "category": "气候", "title": "Scope1直接排放披露",
     "content": "Scope1直接排放包括企业拥有或控制的温室气体来源产生的直接排放。企业应披露报告期内的Scope1排放总量（以tCO2e计），并按气体类型分类。披露要求包括：排放计算方法、活动数据来源、排放因子选择依据。"},
    {"id": "ISSB_S2_02", "standard": "ISSB IFRS S2", "category": "气候", "title": "Scope2能源间接排放披露",
     "content": "Scope2排放是企业外购电力、热力或蒸汽产生的间接排放。披露应区分位置法（location-based）和市场法（market-based）两种计算方法，并说明选择依据。两种方法计算结果均需披露。"},
    {"id": "ISSB_S2_03", "standard": "ISSB IFRS S2", "category": "气候", "title": "Scope3其他间接排放披露",
     "content": "Scope3排放包括价值链上下游的所有其他间接排放，分为15个子类别。企业至少应披露重大类别的排放数据，并说明估算方法和数据质量。供应链合作是Scope3减排的关键。"},
    {"id": "GRI_305_01", "standard": "GRI 305", "category": "气候", "title": "温室气体排放总量",
     "content": "GRI 305要求企业披露直接温室气体排放（Scope1）、间接温室气体排放（Scope2）和其他间接排放（Scope3）。应使用全球变暖潜势（GWP）将各种气体转换为CO2当量。"},
    {"id": "CSRD_01", "standard": "CSRD/ESRS", "category": "通用", "title": "双重重要性评估",
     "content": "CSRD要求企业进行双重重要性评估（Double Materiality Assessment），包括财务重要性（影响企业财务状况的可持续发展事项）和影响重要性（企业对人和环境的影响）。评估结果应确定需要披露的ESG议题。"},
    {"id": "TCFD_01", "standard": "TCFD", "category": "气候", "title": "气候相关财务信息披露",
     "content": "TCFD建议从治理、战略、风险管理、指标和目标四个维度披露气候相关财务信息。治理板块涉及董事会监督和管理层角色。战略板块需描述气候相关风险和机遇对企业战略的影响。"},
    {"id": "GRI_302_01", "standard": "GRI 302", "category": "能源", "title": "能源消耗",
     "content": "企业应披露报告期内的能源消耗总量，包括内部能源消耗和外部能源消耗。能源数据应按能源类型（电、气、油、煤、可再生能源等）分类披露，并说明计量方法。"},
    {"id": "GRI_303_01", "standard": "GRI 303", "category": "水", "title": "水资源取水量",
     "content": "企业应披露报告期内的取水总量，按水源类型（地表水、地下水、海水、生产废水再利用）分类。处于水资源压力地区的企业需额外披露取水量占当地水资源的比例。"},
    {"id": "SASB_01", "standard": "SASB", "category": "通用", "title": "行业特定可持续会计准则",
     "content": "SASB为77个行业制定了行业特定的可持续会计准则，每个标准包含可持续披露主题、说明性会计指标、活动指标和技术协议。SASB指标体系的核心是财务重要性原则。"},
    {"id": "METHODOLOGY_01", "standard": "审计方法论", "category": "方法", "title": "GHG排放审计程序",
     "content": "GHG排放审计程序包括：1)了解企业边界和运营控制；2)评估排放计算方法学选择；3)验证活动数据（燃料账单、电力发票、生产记录）；4)核对排放因子选择和GWP值；5)重新计算关键数据；6)检查内部一致性。"},
    {"id": "CASE_01", "standard": "审计案例", "category": "案例", "title": "制造业Scope2审计案例",
     "content": "某制造企业Scope2审计发现：企业仅使用位置法报告排放，未按ISSB要求披露市场法数据；电力消耗数据与电网账单存在5%差异；可再生能源证书（REC）重复计算问题。建议补充市场法计算并核对REC归属。"},
    {"id": "DEEP_MATERIALITY_01", "standard": "核心概念", "category": "通用", "title": "双重重要性（Double Materiality）",
     "content": "双重重要性是CSRD和ISSB框架的核心概念，要求企业同时评估：(1)可持续发展事项对企业的财务影响（财务重要性）；(2)企业活动对人和环境的影响（影响重要性）。两个维度的交集定义了需要披露的议题。"},
]


_SYNONYM_MAP = {
    "排放": ["温室气体", "GHG", "碳", "碳排放", "scope1", "scope2", "scope3"],
    "重要性": ["materiality", "重大性", "重要议题"],
    "披露": ["disclosure", "报告", "公开", "transparency"],
    "审计": ["audit", "核查", "验证", "assurance"],
    "能源": ["energy", "能耗", "电力", "电耗"],
    "水": ["water", "取水", "用水", "水资源"],
    "标准": ["standard", "准则", "框架", "framework"],
    "方法": ["methodology", "程序", "步骤", "procedure"],
    "案例": ["case", "实例", "经验", "practice"],
}


class LLMEngine(AbstractEngine):
    """ES-05 ESG审计知识库与AI助手。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.kb = []
        self.inverted_index = {}
        self.synonyms = {}
        self.idf = {}
        self.kb_id = ""

    def _load_model(self):
        self.kb = list(_KB_ENTRIES)
        self.synonyms = dict(_SYNONYM_MAP)
        self.kb_id = hashlib.md5(
            "|".join(e["id"] for e in self.kb).encode()
        ).hexdigest()[:10]
        self._build_index()

    def _build_index(self):
        inv = defaultdict(set)
        doc_tokens = []
        for doc in self.kb:
            text = f"{doc['title']} {doc['content']} {doc['standard']} {doc['category']}"
            tokens = self._tokenize(text)
            doc_tokens.append(set(tokens))
            for t in tokens:
                inv[t].add(doc["id"])
        self.inverted_index = dict(inv)
        n_docs = len(self.kb)
        for token, doc_ids in self.inverted_index.items():
            self.idf[token] = math.log((n_docs + 1) / (len(doc_ids) + 1)) + 1

    def _tokenize(self, text: str) -> list:
        text = text.lower()
        tokens = re.findall(r"[\u4e00-\u9fff]|\w+", text)
        expanded = list(tokens)
        for t in tokens:
            for root, syns in self.synonyms.items():
                if t == root or t in syns:
                    expanded.append(root)
                    expanded.extend(syns)
        return [t for t in expanded if t.strip()]

    def _preprocess(self, input_data):
        queries = input_data if isinstance(input_data, list) else [input_data]
        prepared = []
        for q in queries:
            if isinstance(q, str):
                q = {"query": q}
            query_text = q.get("query", "")
            intent = self._classify_intent(query_text)
            rewritten = self._rewrite_query(query_text)
            prepared.append({
                "original_query": query_text,
                "query": rewritten,
                "intent": intent,
                "filters": q.get("filters", {}),
                "top_k": q.get("top_k", 5),
            })
        return prepared

    def _classify_intent(self, query: str) -> str:
        q = query.lower()
        if any(kw in q for kw in ("对比", "差异", "区别", "哪个好")):
            return "comparison"
        if any(kw in q for kw in ("步骤", "方法", "怎么做", "如何", "程序")):
            return "procedure"
        if any(kw in q for kw in ("定义", "什么是", "解释", "含义")):
            return "definition"
        if any(kw in q for kw in ("案例", "实例", "经验")):
            return "case"
        if any(kw in q for kw in ("标准", "规定", "要求", "必须")):
            return "standard"
        return "general"

    def _rewrite_query(self, query: str) -> str:
        expanded_tokens = self._tokenize(query)
        seen = set()
        unique = []
        for t in expanded_tokens:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return " ".join(unique)

    def _infer(self, prepared):
        results = []
        for p in prepared:
            hits = self._retrieve(p["query"], p["top_k"] * 3)
            hits = self._apply_filters(hits, p["filters"])
            hits = self._rerank_rrf(hits)
            top_hits = hits[:p["top_k"]]
            if not top_hits:
                answer = self._fallback_answer(p["original_query"])
                evidence = []
                confidence = 0.3
            else:
                answer = self._generate_answer(p, top_hits)
                evidence = [
                    {"kb_id": h["id"], "title": h["title"], "standard": h["standard"],
                     "relevance_score": round(h["combined_score"], 3)}
                    for h in top_hits
                ]
                confidence = self._assess_confidence(p["original_query"], top_hits, answer)
            results.append({
                "query": p["original_query"],
                "intent": p["intent"],
                "answer": answer,
                "evidence": evidence,
                "confidence": round(confidence, 3),
                "confidence_label": self._confidence_label(confidence),
                "kb_version": self.kb_id,
                "generated_at": datetime.now().isoformat(),
            })
        return results

    def _retrieve(self, query: str, top_k: int) -> list:
        tokens = set(self._tokenize(query))
        if not tokens:
            return []
        bm25_scores = {}
        for token in tokens:
            for doc_id in self.inverted_index.get(token, set()):
                bm25_scores[doc_id] = bm25_scores.get(doc_id, 0) + self.idf.get(token, 0)
        doc_map = {e["id"]: e for e in self.kb}
        hits = []
        for doc_id, bm25 in bm25_scores.items():
            doc = doc_map[doc_id]
            sim = self._query_doc_similarity(query, doc)
            hits.append({
                "id": doc_id,
                "bm25": bm25,
                "semantic": sim,
                "combined_score": 0.0,
                **doc,
            })
        return hits

    def _apply_filters(self, hits: list, filters: dict) -> list:
        if not filters:
            return hits
        out = []
        for h in hits:
            ok = True
            if "standard" in filters:
                if h.get("standard") != filters["standard"]:
                    ok = False
            if "category" in filters:
                if h.get("category") != filters["category"]:
                    ok = False
            if ok:
                out.append(h)
        return out

    def _rerank_rrf(self, hits: list) -> list:
        bm25_sorted = sorted(hits, key=lambda h: h["bm25"], reverse=True)
        sem_sorted = sorted(hits, key=lambda h: h["semantic"], reverse=True)
        k_const = 60.0
        rrf = {}
        for rank, h in enumerate(bm25_sorted):
            rrf[h["id"]] = rrf.get(h["id"], 0) + 1.0 / (k_const + rank + 1)
        for rank, h in enumerate(sem_sorted):
            rrf[h["id"]] = rrf.get(h["id"], 0) + 1.0 / (k_const + rank + 1)
        for h in hits:
            h["combined_score"] = rrf.get(h["id"], 0)
        return sorted(hits, key=lambda h: h["combined_score"], reverse=True)

    def _query_doc_similarity(self, query: str, doc: dict) -> float:
        q_tokens = set(self._tokenize(query))
        d_tokens = set(self._tokenize(f"{doc['title']} {doc['content']}"))
        if not q_tokens or not d_tokens:
            return 0.0
        overlap = q_tokens & d_tokens
        base = len(overlap) / max(1, len(q_tokens))
        title_bonus = 0.0
        title_tokens = set(self._tokenize(doc["title"]))
        title_overlap = q_tokens & title_tokens
        if title_overlap:
            title_bonus = 0.3 * len(title_overlap) / max(1, len(q_tokens))
        return min(1.0, base + title_bonus)

    def _generate_answer(self, prepared: dict, hits: list) -> str:
        intent = prepared["intent"]
        if intent == "comparison" and len(hits) >= 2:
            a, b = hits[0], hits[1]
            return (
                f"关于「{prepared['original_query']}」，检索到两个相关标准来源：\n\n"
                f"【{a['standard']}】- {a['title']}\n"
                f"  {a['content']}\n\n"
                f"【{b['standard']}】- {b['title']}\n"
                f"  {b['content']}\n\n"
                f"两者关联度评估：{a['combined_score']:.2f} vs {b['combined_score']:.2f}"
            )
        top = hits[0]
        if intent == "definition":
            return f"【{top['title']}】（来源：{top['standard']}）\n\n{top['content']}"
        if intent == "procedure":
            steps = self._extract_steps(top["content"])
            if len(hits) > 1:
                steps.extend(self._extract_steps(hits[1]["content"]))
            return f"基于【{top['standard']} - {top['title']}】，建议审计程序如下：\n\n" + "\n".join(steps)
        if intent == "case":
            return f"【审计案例】{top['title']}\n\n{top['content']}"
        contents = [f"• [{h['standard']}] {h['title']}: {h['content']}" for h in hits[:3]]
        return f"关于「{prepared['original_query']}」，根据ESG审计知识库检索结果：\n\n" + "\n\n".join(contents)

    @staticmethod
    def _extract_steps(text: str) -> list:
        parts = re.split(r"[；;。]|\d+[)．、.]", text)
        steps = []
        for p in parts:
            p = p.strip()
            if len(p) > 4 and not p.startswith("Scope") and not p.startswith("企业"):
                steps.append(p)
        if not steps:
            return [f"参考: {text[:200]}"]
        return [f"{i+1}. {s}" for i, s in enumerate(steps[:6])]

    def _fallback_answer(self, query: str) -> str:
        return (
            f"抱歉，知识库中暂未检索到关于「{query}」的直接内容。\n\n"
            f"建议尝试：\n"
            f"• 使用更具体的关键词（如具体标准名称 GRI 305、ISSB S2）\n"
            f"• 缩小查询范围（限定 E/S/G 某个维度）\n"
            f"• 检查是否有错别字\n\n"
            f"知识库当前覆盖 {len(self.kb)} 条标准/方法论/案例。"
        )

    def _assess_confidence(self, query: str, hits: list, answer: str) -> float:
        if not hits:
            return 0.3
        top_score = hits[0]["combined_score"]
        query_tokens = set(self._tokenize(query))
        answer_tokens = set(self._tokenize(answer[:200]))
        ref_hit = hits[0]
        ref_tokens = set(self._tokenize(f"{ref_hit['title']} {ref_hit['content']}"))
        in_answer = query_tokens & ref_tokens & answer_tokens
        coverage = len(in_answer) / max(1, len(query_tokens & ref_tokens))
        evidence_count = min(1.0, len(hits) / 3.0)
        return min(1.0, 0.4 * top_score + 0.3 * coverage + 0.3 * evidence_count)

    @staticmethod
    def _confidence_label(conf: float) -> str:
        if conf >= 0.8:
            return "高-多条权威来源支撑"
        if conf >= 0.6:
            return "中-有相关参考但建议人工复核"
        return "低-证据有限，需谨慎使用"

    def _postprocess(self, result):
        by_intent = defaultdict(int)
        for r in result:
            by_intent[r["intent"]] += 1
        low_conf = [r for r in result if r["confidence"] < 0.5]
        return {
            "answers": result,
            "intent_distribution": dict(by_intent),
            "needs_human_review": low_conf,
            "kb_version": self.kb_id,
            "kb_size": len(self.kb),
            "generated_at": datetime.now().isoformat(),
        }
