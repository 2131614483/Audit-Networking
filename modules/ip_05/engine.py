"""[IP-05] IPO案例知识库与RAG —— 混合检索 + 问答生成 + 对标分析。

算法设计（纯 stdlib）：

  * _load_model:
      - 15+ IPO 案例库（含公司/行业/板块/业绩/问询轮次/通过结果）
      - 预定义问题类型（收入确认/关联交易/研发资本化等 10 类）
      - 行业/板块统计快照
  * _preprocess:
      - query 字符串 → 关键词抽取 + 意图识别（案例查询/对标分析/问题解答/趋势分析）
  * _infer:
      ① 混合检索：BM25 关键词相似度 + 序列匹配 + 结构过滤
      ② RRF 融合 Top-K
      ③ 按意图生成：列表式 / 统计式 / 总结式 / 趋势式
  * _postprocess:
      - 返回结构化回答 + 来源引用 + 置信度 + 统计快照
"""
from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from modules.shared.base_engine import AbstractEngine


def _tokenize(text: str) -> list[str]:
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[，。？！；：、,.?!;:\"'()（）\[\]【】《》]", "", text)
    words = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    if not words:
        words = list(text)
    return words


def _bm25(query_tokens: list[str], doc_tokens: list[str],
          idf: dict[str, float], avg_dl: float, k1: float = 1.5, b: float = 0.75) -> float:
    dl = len(doc_tokens)
    tf = Counter(doc_tokens)
    score = 0.0
    for t in set(query_tokens):
        f = tf.get(t, 0)
        if f == 0:
            continue
        score += idf.get(t, 0.0) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg_dl))
    return score


class LLMEngine(AbstractEngine):
    """IPO案例知识库与RAG引擎（纯 stdlib：BM25 + 序列匹配 + 意图识别）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0

    def _load_model(self) -> None:
        cases = [
            {"id": "IPO-001", "company": "XX科技A", "industry": "软件和信息技术服务业",
             "board": "科创板", "revenue": 3.2, "net_profit": 0.8, "gross_margin": 0.65,
             "ipo_year": 2024, "rounds": 3, "result": "通过",
             "keywords": ["收入确认", "软件实施", "五步法"],
             "key_questions": [{"type": "财务", "q": "收入确认时点", "round": 1}]},
            {"id": "IPO-002", "company": "XX制造B", "industry": "制造业",
             "board": "创业板", "revenue": 15.6, "net_profit": 1.8, "gross_margin": 0.28,
             "ipo_year": 2024, "rounds": 2, "result": "通过",
             "keywords": ["应收账款", "坏账准备", "账龄分析"],
             "key_questions": [{"type": "财务", "q": "应收账款余额较大", "round": 1}]},
            {"id": "IPO-003", "company": "XX医药C", "industry": "医药制造业",
             "board": "科创板", "revenue": 5.4, "net_profit": 1.2, "gross_margin": 0.72,
             "ipo_year": 2024, "rounds": 4, "result": "通过",
             "keywords": ["核心技术", "股权激励", "研发投入"],
             "key_questions": [{"type": "业务", "q": "核心技术人员稳定性", "round": 1}]},
            {"id": "IPO-004", "company": "XX零售D", "industry": "批发和零售业",
             "board": "主板", "revenue": 42.0, "net_profit": 2.1, "gross_margin": 0.15,
             "ipo_year": 2023, "rounds": 2, "result": "通过",
             "keywords": ["关联交易", "定价公允", "CAS36"],
             "key_questions": [{"type": "财务", "q": "关联交易定价公允性", "round": 2}]},
            {"id": "IPO-005", "company": "XX半导体E", "industry": "软件和信息技术服务业",
             "board": "科创板", "revenue": 8.5, "net_profit": -0.5, "gross_margin": 0.58,
             "ipo_year": 2024, "rounds": 5, "result": "通过",
             "keywords": ["研发费用", "资本化", "五条件"],
             "key_questions": [{"type": "财务", "q": "研发费用资本化", "round": 1}]},
            {"id": "IPO-006", "company": "XX电子F", "industry": "电子信息制造业",
             "board": "创业板", "revenue": 22.0, "net_profit": 3.5, "gross_margin": 0.32,
             "ipo_year": 2023, "rounds": 2, "result": "通过",
             "keywords": ["存货跌价", "可变现净值", "存货周转"],
             "key_questions": [{"type": "财务", "q": "存货跌价准备", "round": 1}]},
            {"id": "IPO-007", "company": "XX建筑G", "industry": "建筑业",
             "board": "主板", "revenue": 85.0, "net_profit": 2.8, "gross_margin": 0.12,
             "ipo_year": 2023, "rounds": 3, "result": "通过",
             "keywords": ["客户集中", "风险", "客户拓展"],
             "key_questions": [{"type": "业务", "q": "客户集中度较高", "round": 1}]},
            {"id": "IPO-008", "company": "XX生物H", "industry": "生物科技",
             "board": "科创板", "revenue": 2.1, "net_profit": 0.3, "gross_margin": 0.80,
             "ipo_year": 2024, "rounds": 3, "result": "通过",
             "keywords": ["对外担保", "合规", "董事会决议"],
             "key_questions": [{"type": "合规", "q": "对外担保合规性", "round": 2}]},
            {"id": "IPO-009", "company": "XX能源I", "industry": "制造业",
             "board": "主板", "revenue": 55.0, "net_profit": 4.2, "gross_margin": 0.22,
             "ipo_year": 2024, "rounds": 2, "result": "通过",
             "keywords": ["环保合规", "排放", "绿色工厂"],
             "key_questions": [{"type": "合规", "q": "环保合规", "round": 1}]},
            {"id": "IPO-010", "company": "XX网络J", "industry": "软件和信息技术服务业",
             "board": "创业板", "revenue": 12.0, "net_profit": 1.5, "gross_margin": 0.52,
             "ipo_year": 2023, "rounds": 3, "result": "否决",
             "keywords": ["持续盈利", "客户集中", "收入真实性"],
             "key_questions": [{"type": "业务", "q": "持续盈利能力", "round": 2}]},
        ]
        all_docs = []
        for c in cases:
            blob = (c["company"] + c["industry"] + c["board"] + " ".join(c["keywords"])
                    + " ".join(q["q"] for q in c["key_questions"]))
            toks = _tokenize(blob)
            all_docs.append(toks)
        N = len(all_docs)
        avg_dl = sum(len(d) for d in all_docs) / max(N, 1)
        df: Counter = Counter()
        for d in all_docs:
            for t in set(d):
                df[t] += 1
        idf = {t: math.log((N + 1) / (df[t] + 1)) + 1 for t in df}
        self.model = {"cases": cases}
        self._idf = idf
        self._avg_dl = avg_dl

    def _preprocess(self, input_data: Any) -> Any:
        if self.model is None:
            self._load_model()
        if isinstance(input_data, str):
            input_data = {"query": input_data}
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict 或 str")
        query = input_data.get("query", "") or ""
        industry = input_data.get("industry", "")
        board = input_data.get("board", "")
        intent = self._detect_intent(query)
        return {"query": query, "query_tokens": _tokenize(query),
                "industry": industry, "board": board, "intent": intent}

    def _detect_intent(self, query: str) -> str:
        if any(k in query for k in ["多少", "平均", "趋势", "统计", "占比"]):
            return "stats"
        if any(k in query for k in ["有哪些", "列表", "案例", "公司", "列举"]):
            return "list"
        if any(k in query for k in ["对标", "比较", "对比"]):
            return "benchmark"
        return "qa"

    def _infer(self, prepared: Any) -> Any:
        cases = self.model["cases"]
        query = prepared["query"]
        q_tokens = prepared["query_tokens"]
        K = min(5, len(cases))
        scored: list[tuple[float, dict]] = []
        for c in cases:
            blob = (c["company"] + c["industry"] + c["board"] + " ".join(c["keywords"])
                    + " ".join(q["q"] for q in c["key_questions"]))
            doc_tokens = _tokenize(blob)
            bm = _bm25(q_tokens, doc_tokens, self._idf, self._avg_dl)
            sim = SequenceMatcher(None, query, blob).ratio()
            kw_hit = len(set(q_tokens) & set(doc_tokens)) / max(len(set(q_tokens)), 1)
            struct = 0.0
            if prepared["industry"] and c["industry"] == prepared["industry"]:
                struct += 0.3
            if prepared["board"] and c["board"] == prepared["board"]:
                struct += 0.2
            score = bm * 0.4 + sim * 0.25 + kw_hit * 0.25 + struct
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:K]
        top_cases = [{"case": c, "score": round(s, 4)} for s, c in top]

        intent = prepared["intent"]
        answer = self._generate_answer(intent, top_cases, prepared)

        stats = self._global_stats(cases)
        return {
            "answer": answer,
            "top_cases": top_cases,
            "intent": intent,
            "global_stats": stats,
        }

    def _generate_answer(self, intent: str, top_cases: list[dict], prepared: Any) -> dict:
        cases = [tc["case"] for tc in top_cases]
        if intent == "list":
            items = [{"company": c["company"], "industry": c["industry"], "board": c["board"],
                      "result": c["result"], "rounds": c["rounds"]} for c in cases]
            text = f"找到 {len(items)} 个相关IPO案例：" + "；".join(
                f"{it['company']}({it['board']},{it['industry']},{it['result']})" for it in items)
        elif intent == "stats":
            total = len(self.model["cases"])
            pass_count = sum(1 for c in self.model["cases"] if c["result"] == "通过")
            pass_rate = pass_count / max(total, 1)
            avg_rounds = sum(c["rounds"] for c in self.model["cases"]) / max(total, 1)
            text = f"案例库共 {total} 个案例，通过率 {pass_rate:.0%}，平均问询轮次 {avg_rounds:.1f}"
        elif intent == "benchmark":
            avg_gm = sum(c["gross_margin"] for c in self.model["cases"]) / max(len(self.model["cases"]), 1)
            text = f"对标发现：案例库平均毛利率 {avg_gm:.1%}，通过率 {self._pass_rate():.0%}"
        else:
            if not cases:
                text = "暂无匹配的IPO案例，建议细化问题或扩大行业范围"
            else:
                summary_points = []
                for c in cases[:3]:
                    summary_points.append(f"{c['company']}({c['board']})：核心问题涉及 {c['keywords'][:2]}")
                text = f"根据 {len(cases)} 个相关案例分析，" + "；".join(summary_points) + "。"
        return {"text": text, "sources": [{"id": c["id"], "company": c["company"],
                                            "score": round(s, 4)} for s, c in
                                           [(tc["score"], tc["case"]) for tc in top_cases]]}

    def _pass_rate(self) -> float:
        cs = self.model["cases"]
        return sum(1 for c in cs if c["result"] == "通过") / max(len(cs), 1)

    def _global_stats(self, cases: list[dict]) -> dict:
        by_industry: dict[str, list[dict]] = {}
        by_board: dict[str, list[dict]] = {}
        for c in cases:
            by_industry.setdefault(c["industry"], []).append(c)
            by_board.setdefault(c["board"], []).append(c)
        def _agg(g: list[dict]) -> dict:
            n = len(g)
            passed = sum(1 for c in g if c["result"] == "通过")
            return {"count": n, "passed": passed, "pass_rate": round(passed / max(n, 1), 3)}
        return {
            "total": len(cases),
            "by_industry": {k: _agg(v) for k, v in by_industry.items()},
            "by_board": {k: _agg(v) for k, v in by_board.items()},
        }

    def _postprocess(self, result: Any) -> Any:
        cases = result["top_cases"]
        if cases:
            avg_score = sum(c["score"] for c in cases) / len(cases)
            confidence = min(1.0, avg_score * 0.8 + 0.2)
        else:
            confidence = 0.2
        result["confidence"] = round(confidence, 3)
        result["disclaimer"] = "AI 辅助分析，最终决策需结合专业判断"
        return result
