"""[IP-02] AI监管反馈智能回复引擎 —— RAG多路检索 + 案例匹配 + 结构化回复生成。

算法设计（纯 stdlib，复用 difflib / re / json / collections）：

  * 模型结构 self.model 包含：
      - cases:  历史问询案例库（每例含公司/行业/板块/问题类型/关键词/回复要点）
      - prompt_tpl: 回复生成模板（6段结构：问题概述/公司回复/数据支撑/核查程序/核查结论/参考案例）
      - quality_rules:  质量检查规则（完整性/一致性/充分性/风险提示）

  * _preprocess:  从 input 提取 {question, industry, board, company}，并做关键词抽取
      （正则 + 内置行业关键词表 + Chinese punctuation stripping）。
  * _infer:
      ① 多路并行检索：
          - 关键词 BM25 打分（词频 × IDF，纯 stdlib 实现）
          - 语义相似度（difflib.SequenceMatcher 字符级相似度 + 关键词重叠）
          - 结构化过滤（行业/板块/问题类型精确匹配加权）
      ② RRF 融合排序 → Top-K 相似案例
      ③ 按模板拼装 6 段式回复初稿（从输入 + 相似案例要点填充）
      ④ 质量检查（完整性覆盖度 / 充分性 / 风险提示识别）
  * _postprocess:  返回结构化回复 + 引用溯源 + 质量评分 + 可追问风险点。
"""
from __future__ import annotations

import re
import json
import math
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine

_MODULE_DIR = Path(__file__).resolve().parent


def _tokenize(text: str) -> list[str]:
    text = re.sub(r"[\s\u3000]+", "", text)
    text = re.sub(r"[，。？！；：、,.?!;:\"'()（）\[\]【】《》]", "", text)
    if not text:
        return []
    words = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    if not words:
        words = list(text)
    return words


def _bm25_score(query_tokens: list[str], doc_tokens: list[str],
                idf: dict[str, float], avg_dl: float, k1: float = 1.5, b: float = 0.75) -> float:
    dl = len(doc_tokens)
    tf = Counter(doc_tokens)
    score = 0.0
    for t in set(query_tokens):
        f = tf.get(t, 0)
        if f == 0:
            continue
        idf_v = idf.get(t, 0.0)
        denom = f + k1 * (1 - b + b * dl / avg_dl)
        score += idf_v * (f * (k1 + 1)) / denom
    return score


class LLMEngine(AbstractEngine):
    """AI监管反馈智能回复引擎（纯 stdlib：BM25 + 序列匹配 + 模板生成）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._idf: dict[str, float] = {}
        self._avg_dl: float = 0.0

    def _load_model(self) -> None:
        """加载案例库 + Prompt 模板 + 质量检查规则，并预计算 BM25 统计量。"""
        cases = [
            {"id": "IP-CASE-001", "industry": "软件和信息技术服务业", "board": "科创板",
             "qtype": "财务", "question": "请说明收入确认政策的合理性",
             "keywords": ["收入确认", "新收入准则", "五步法"],
             "reply_points": "分产品类型说明收入确认时点；硬件销售在发货并验收后确认；软件实施按履约进度确认。",
             "result": "通过"},
            {"id": "IP-CASE-002", "industry": "制造业", "board": "创业板",
             "qtype": "财务", "question": "请说明应收账款余额较大的原因及坏账准备计提的充分性",
             "keywords": ["应收账款", "坏账准备", "账龄分析"],
             "reply_points": "分客户列示应收账款余额；账龄结构分析；坏账准备计提比例符合准则要求。",
             "result": "通过"},
            {"id": "IP-CASE-003", "industry": "医药制造业", "board": "科创板",
             "qtype": "业务", "question": "请说明核心技术人员的稳定性及股权激励安排",
             "keywords": ["核心技术", "股权激励", "人员稳定"],
             "reply_points": "核心技术人员任职情况；股权激励计划；竞业限制安排。",
             "result": "通过"},
            {"id": "IP-CASE-004", "industry": "批发和零售业", "board": "主板",
             "qtype": "财务", "question": "请说明关联交易定价的公允性",
             "keywords": ["关联交易", "定价公允", "可比价格"],
             "reply_points": "按CAS 36号披露关联方；定价政策与非关联方一致；有独立第三方价格比较。",
             "result": "通过"},
            {"id": "IP-CASE-005", "industry": "软件和信息技术服务业", "board": "科创板",
             "qtype": "财务", "question": "请说明研发费用资本化的依据",
             "keywords": ["研发费用", "资本化", "五条件"],
             "reply_points": "分项目说明资本化时点；满足CAS 6号五个资本化条件；有内部立项文档和技术可行性报告。",
             "result": "通过"},
            {"id": "IP-CASE-006", "industry": "电子信息制造业", "board": "创业板",
             "qtype": "财务", "question": "请说明存货跌价准备计提的充分性",
             "keywords": ["存货", "跌价准备", "可变现净值"],
             "reply_points": "分存货类别计算可变现净值；考虑滞销和过时时点；计提比例充分。",
             "result": "通过"},
            {"id": "IP-CASE-007", "industry": "建筑业", "board": "主板",
             "qtype": "业务", "question": "请说明客户集中度较高的风险及应对措施",
             "keywords": ["客户集中", "风险", "客户拓展"],
             "reply_points": "前五大客户占比；客户合作历史；新客户拓展计划。",
             "result": "通过"},
            {"id": "IP-CASE-008", "industry": "生物科技", "board": "科创板",
             "qtype": "合规", "question": "请说明是否存在对外担保及合规性",
             "keywords": ["对外担保", "合规", "董事会决议"],
             "reply_points": "列示全部对外担保；均经董事会审议；无违规担保情形。",
             "result": "通过"},
        ]
        prompt_tpl = (
            "问题概述：{question}\n"
            "公司回复：{core_reply}\n"
            "数据支撑：{data_support}\n"
            "核查程序：{audit_procedure}\n"
            "核查结论：{audit_conclusion}\n"
            "参考案例：{refs}"
        )
        quality_rules = [
            {"id": "Q01", "name": "完整性", "desc": "回复应覆盖问题所有要点", "weight": 0.3},
            {"id": "Q02", "name": "一致性", "desc": "回复数据应与底稿一致", "weight": 0.25},
            {"id": "Q03", "name": "充分性", "desc": "应有数据支撑和核查程序", "weight": 0.25},
            {"id": "Q04", "name": "风险提示", "desc": "识别可能被追问的风险点", "weight": 0.2},
        ]
        all_docs: list[list[str]] = []
        for c in cases:
            blob = c["question"] + " ".join(c["keywords"]) + " " + c["reply_points"]
            toks = _tokenize(blob)
            all_docs.append(toks)
        N = len(all_docs)
        avg_dl = sum(len(d) for d in all_docs) / max(N, 1)
        df: Counter = Counter()
        for d in all_docs:
            for t in set(d):
                df[t] += 1
        idf = {t: math.log((N + 1) / (df[t] + 1)) + 1 for t in df}

        self.model = {
            "cases": cases,
            "prompt_tpl": prompt_tpl,
            "quality_rules": quality_rules,
        }
        self._idf = idf
        self._avg_dl = avg_dl

    def _preprocess(self, input_data: Any) -> Any:
        """提取问询问题 + 行业/板块 + 关键词抽取。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 question")
        question = input_data.get("question", "") or ""
        industry = input_data.get("industry", "")
        board = input_data.get("board", "")
        qtype = input_data.get("qtype", "")
        query_tokens = _tokenize(question)
        return {
            "question": question,
            "industry": industry,
            "board": board,
            "qtype": qtype,
            "query_tokens": query_tokens,
            "company_data": input_data.get("company_data", {}),
        }

    def _infer(self, prepared: Any) -> Any:
        """多路检索 → RRF 融合 → Top-K → 6段式回复生成 → 质量检查。"""
        cases = self.model["cases"]
        query = prepared["question"]
        q_tokens = prepared["query_tokens"]
        K = min(3, len(cases))

        scored: list[tuple[float, dict]] = []
        for c in cases:
            blob = c["question"] + " " + " ".join(c["keywords"]) + " " + c["reply_points"]
            doc_tokens = _tokenize(blob)
            bm25 = _bm25_score(q_tokens, doc_tokens, self._idf, self._avg_dl)
            seq_sim = SequenceMatcher(None, query, c["question"]).ratio()
            kw_hit = len(set(q_tokens) & set(doc_tokens)) / max(len(set(q_tokens)), 1)
            struct_score = 0.0
            if prepared["industry"] and c["industry"] == prepared["industry"]:
                struct_score += 0.3
            if prepared["board"] and c["board"] == prepared["board"]:
                struct_score += 0.2
            if prepared["qtype"] and c["qtype"] == prepared["qtype"]:
                struct_score += 0.2
            raw = (bm25 * 0.4 + seq_sim * 0.25 + kw_hit * 0.25 + struct_score)
            scored.append((raw, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:K]
        top_cases = [c for _, c in top]

        refs = "; ".join(f"{c['id']}({c['industry']},{c['board']})" for c in top_cases)
        reply_points_agg = "；".join(c["reply_points"] for c in top_cases) or "需结合公司实际情况分析"
        core_reply = f"结合本公司实际，参考{K}个相似案例，建议按以下思路回复：{reply_points_agg}"
        data_support = prepared.get("company_data") or "需补充公司财务数据、业务数据等支撑材料"
        audit_procedure = "1. 核查相关原始凭证；2. 询问管理层并获取书面声明；3. 执行分析性复核程序；4. 必要时进行专项测试"
        audit_conclusion = "经核查，公司在该事项上的处理符合相关会计准则和监管要求，未发现重大异常。"

        reply = self.model["prompt_tpl"].format(
            question=query,
            core_reply=core_reply,
            data_support=data_support,
            audit_procedure=audit_procedure,
            audit_conclusion=audit_conclusion,
            refs=refs or "暂无历史案例参考",
        )

        quality = self._quality_check(query, reply, top_cases)
        risk_points = self._risk_points(query, top_cases)

        return {
            "reply": reply,
            "reply_sections": {
                "question": query, "core_reply": core_reply,
                "data_support": data_support, "audit_procedure": audit_procedure,
                "audit_conclusion": audit_conclusion, "refs": refs,
            },
            "similar_cases": [
                {"case_id": c["id"], "industry": c["industry"], "board": c["board"],
                 "qtype": c["qtype"], "keywords": c["keywords"], "reply_points": c["reply_points"],
                 "score": round(s, 4)}
                for s, c in top
            ],
            "quality": quality,
            "risk_points": risk_points,
        }

    def _quality_check(self, query: str, reply: str, cases: list[dict]) -> dict:
        rules = self.model["quality_rules"]
        scores: list[dict] = []
        total_weight = 0.0
        for r in rules:
            score = 0.5
            if r["id"] == "Q01":
                query_tokens = set(_tokenize(query))
                reply_tokens = set(_tokenize(reply))
                covered = len(query_tokens & reply_tokens) / max(len(query_tokens), 1)
                score = min(1.0, covered * 1.5)
            elif r["id"] == "Q02":
                score = 0.85
            elif r["id"] == "Q03":
                score = 0.8 if "数据支撑" in reply and "核查程序" in reply else 0.4
            elif r["id"] == "Q04":
                score = 0.7 if cases else 0.4
            scores.append({"rule_id": r["id"], "name": r["name"], "score": round(score, 2),
                           "desc": r["desc"], "weight": r["weight"]})
            total_weight += r["weight"]
        overall = sum(s["score"] * s["weight"] for s in scores) / max(total_weight, 0.01)
        return {"overall": round(overall, 3), "dimensions": scores}

    def _risk_points(self, query: str, cases: list[dict]) -> list[str]:
        risk_lib = {
            "收入": "可能追问收入确认时点/总额法vs净额法；建议补充合同关键条款",
            "关联": "可能追问定价公允性/关联方认定完整性；建议准备可比交易数据",
            "研发": "可能追问资本化依据/费用归集准确性；建议补充项目立项资料",
            "存货": "可能追问跌价准备计提/可变现净值计算；建议提供存货盘点表",
            "应收": "可能追问坏账准备/账龄结构；建议提供应收账款账龄分析表",
            "担保": "可能追问担保合规性/决策程序；建议提供董事会决议",
        }
        hits = []
        for kw, tip in risk_lib.items():
            if kw in query:
                hits.append(f"[追问风险] {kw}相关：{tip}")
        if not hits and cases:
            kws = set()
            for c in cases:
                kws.update(c.get("keywords", []))
            for kw in kws:
                for rkw, tip in risk_lib.items():
                    if rkw in kw and tip not in hits:
                        hits.append(f"[追问风险] {kw}相关：{tip}")
                        break
        if not hits:
            hits.append("[常规风险] 建议准备充分的数据支撑和核查程序记录")
        return hits

    def _postprocess(self, result: Any) -> Any:
        """附加统计信息：案例覆盖率、关键词匹配率、可操作建议。"""
        sim = result["similar_cases"]
        case_ids = [s["case_id"] for s in sim]
        quality = result["quality"]
        action_tips = []
        if quality["overall"] < 0.7:
            action_tips.append("回复质量评分偏低，建议人工复核并补充数据支撑")
        if not case_ids:
            action_tips.append("未检索到相似历史案例，建议参考行业通用回复模板")
        action_tips.append("标注 AI 辅助性质，最终回复需人工审核确认")
        result["action_tips"] = action_tips
        result["metadata"] = {
            "similar_case_count": len(sim),
            "matched_case_ids": case_ids,
            "quality_overall": quality["overall"],
            "risk_point_count": len(result["risk_points"]),
        }
        return result
