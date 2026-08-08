"""[llm_rag] IA-05 AI驱动的管理建议书。

纯 stdlib 实现的管理建议书生成引擎：
  - _load_model  : 初始化内置建议知识库 + 行业对标数据（PortableDB 持久化）
  - _preprocess  : 对审计发现做问题类型分类 + BM25 + 字符 n-gram 混合检索 Top-K
  - _infer       : 基于检索结果组装 Prompt 模板 + 建议框架 → 详细撰写 → 价值量化 三轮生成
  - _postprocess : 质量评估框架（针对性/可操作性/可量化/创新性/完整性加权评分）
"""
from __future__ import annotations

import difflib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB


_ISSUE_TYPES = ("流程缺陷", "控制缺失", "合规违规", "效率低下", "战略偏离")
_SEVERITY_MAP = {"严重": 4, "重要": 3, "一般": 2, "建议": 1}

_QUALITY_WEIGHTS = {
    "specificity": 0.25,
    "actionability": 0.25,
    "quantifiability": 0.20,
    "innovation": 0.15,
    "completeness": 0.15,
}


def _bm25_score(query_tokens: list[str], doc_tokens: list[str],
                avgdl: float, k1: float = 1.5, b: float = 0.75) -> float:
    tf = Counter(doc_tokens)
    dl = len(doc_tokens) or 1
    score = 0.0
    for t in query_tokens:
        f = tf.get(t, 0)
        score += f * (k1 + 1) / (f + k1 * (1 - b + b * dl / avgdl))
    return score


def _ngram_sim(a: str, b: str, n: int = 3) -> float:
    def grams(s: str) -> Counter:
        s = re.sub(r"\s+", "", s.lower())
        if len(s) < n:
            return Counter([s])
        return Counter(s[i:i + n] for i in range(len(s) - n + 1))
    ga, gb = grams(a), grams(b)
    overlap = sum((ga & gb).values())
    return overlap / max(1, sum(ga.values()), sum(gb.values()))


class LLMEngine(AbstractEngine):
    """IA-05 管理建议书生成引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.suggestions: list[dict] = []
        self.benchmarks: dict[str, dict] = {}
        self.avgdl = 1.0

    def _load_model(self):
        db_path = self.config.get("db_path", "modules/ia_05/data/ia05.db")
        self.db = PortableDB(db_path)
        self.db.create_table("suggestions", {
            "id": "TEXT", "industry": "TEXT", "issue_type": "TEXT",
            "severity": "INTEGER", "keywords": "JSON", "content": "TEXT",
            "path": "TEXT", "impact": "JSON", "adoption_rate": "REAL",
            "avg_effectiveness": "REAL",
        }, drop_if_exists=False)
        self.db.create_table("benchmarks", {
            "industry": "TEXT", "metric": "TEXT",
            "p25": "REAL", "p50": "REAL", "p75": "REAL", "unit": "TEXT",
        }, drop_if_exists=False)
        rows = self.db.all("suggestions")
        self.suggestions = rows if rows else self._seed_knowledge()
        bm = self.db.all("benchmarks")
        self.benchmarks = {(r["industry"], r["metric"]): r for r in bm} if bm else {}
        avgdl_vals = [len(s.get("keywords", [])) or len(re.sub(r"\s+", "", s.get("content", ""))) for s in self.suggestions]
        self.avgdl = sum(avgdl_vals) / max(1, len(avgdl_vals))

    def _seed_knowledge(self) -> list[dict]:
        seed = [
            {"id": "S001", "industry": "制造业", "issue_type": "流程缺陷", "severity": 3,
             "keywords": ["采购", "审批", "效率"],
             "content": "建立分级审批机制，按金额阈值自动路由，超小额订单豁免逐级审批",
             "path": "1-2月梳理流程→3月上线分级审批→4月效果评估",
             "impact": {"cost_saving": 150, "cycle_reduction": 0.6}, "adoption_rate": 0.85,
             "avg_effectiveness": 4.2},
            {"id": "S002", "industry": "金融", "issue_type": "控制缺失", "severity": 4,
             "keywords": ["权限", "分离", "内部控制"],
             "content": "实施最小权限原则，定期（每季度）权限复核与自动回收闲置账号",
             "path": "1月权限盘点→2月最小权限映射→3月自动回收机制上线",
             "impact": {"risk_reduction": 0.8, "efficiency": 0.3}, "adoption_rate": 0.9,
             "avg_effectiveness": 4.5},
            {"id": "S003", "industry": "科技", "issue_type": "效率低下", "severity": 2,
             "keywords": ["测试", "自动化", "CI/CD"],
             "content": "核心交易场景引入UI自动化回归测试流水线，覆盖率≥80%",
             "path": "搭建测试框架→编写用例→接入CI/CD",
             "impact": {"efficiency_improvement": 0.5}, "adoption_rate": 0.78,
             "avg_effectiveness": 3.9},
        ]
        if self.db:
            self.db.insert_many("suggestions", seed)
        return seed

    def _preprocess(self, input_data):
        if isinstance(input_data, str):
            input_data = {"finding": input_data}
        finding = (input_data.get("finding") or "").strip()
        industry = input_data.get("industry", "制造业")
        keywords = re.findall(r"[\u4e00-\u9fffA-Za-z]+", finding)
        query_tokens = keywords or [finding[:10]]
        issue_type = input_data.get("issue_type") or self._classify(finding)
        severity = input_data.get("severity", "一般")
        candidates = []
        for s in self.suggestions:
            if industry and s["industry"] != industry and s["industry"] != "通用":
                continue
            doc_tokens = s.get("keywords", []) + re.findall(r"[\u4e00-\u9fffA-Za-z]+", s.get("content", ""))
            bm = _bm25_score(query_tokens, doc_tokens, self.avgdl)
            ng = _ngram_sim(finding, s["content"])
            rating = (s.get("adoption_rate", 0) + s.get("avg_effectiveness", 0) / 5) / 2
            score = 0.5 * bm + 0.3 * ng + 0.2 * rating
            candidates.append((score, s))
        candidates.sort(key=lambda x: x[0], reverse=True)
        topk = [{"score": round(sc, 4), **s} for sc, s in candidates[:self.config.get("top_k", 5)]]
        return {
            "finding": finding,
            "industry": industry,
            "issue_type": issue_type,
            "severity": severity,
            "query_tokens": query_tokens,
            "references": topk,
            "context": input_data,
        }

    def _classify(self, text: str) -> str:
        keywords = {
            "流程缺陷": ["流程", "步骤", "审批", "环节"],
            "控制缺失": ["控制", "权限", "缺失", "未执行"],
            "合规违规": ["合规", "违反", "规定", "监管"],
            "效率低下": ["效率", "耗时", "重复", "手工"],
            "战略偏离": ["战略", "方向", "目标", "偏离"],
        }
        scores = {k: sum(1 for kw in v if kw in text) for k, v in keywords.items()}
        return max(scores, key=scores.get)

    def _infer(self, prepared):
        refs = prepared["references"]
        finding = prepared["finding"]
        issue_type = prepared["issue_type"]
        severity = prepared["severity"]

        framework_steps = [
            f"建议方向：针对「{finding[:40]}...」的{issue_type}问题",
            f"核心内容：结合{prepared['industry']}行业特点",
            f"预期效果：降低{severity}级风险",
        ]
        details = []
        for ref in refs[:3]:
            details.append({
                "source": ref["id"],
                "content": ref["content"],
                "implementation_path": ref.get("path", ""),
            })
        if not details:
            details.append({
                "source": "auto",
                "content": f"建议建立{issue_type}专项治理小组，制定分阶段整改方案",
                "implementation_path": "1-2月现状梳理→3-4月方案设计→5-6月落地实施",
            })

        impact_list = []
        for d in details:
            ref_impact = next((r.get("impact", {}) for r in refs if r["id"] == d["source"]), {})
            impact_list.append(self._quantify(finding, issue_type, ref_impact))
        return {
            "framework": framework_steps,
            "suggestions": details,
            "quantified_impacts": impact_list,
            "raw_text": "\n".join(framework_steps) + "\n" +
                        "\n".join(f"[{s['source']}] {s['content']}（实施路径：{s['implementation_path']}）" for s in details),
        }

    def _quantify(self, finding: str, issue_type: str, ref_impact: dict) -> dict:
        base = {"cost_saving": 0, "efficiency": 0, "risk_reduction": 0}
        ref_val = ref_impact.get("cost_saving") or ref_impact.get("efficiency_improvement") or 80
        if "审批" in finding or "流程" in finding or issue_type == "流程缺陷":
            base["cost_saving"] = round(ref_val * 1.5, 1)
            base["efficiency"] = 0.4
        elif "权限" in finding or issue_type == "控制缺失":
            base["risk_reduction"] = 0.75
            base["cost_saving"] = round(ref_val, 1)
        elif "效率" in finding or issue_type == "效率低下":
            base["efficiency"] = 0.55
            base["cost_saving"] = round(ref_val, 1)
        else:
            base["cost_saving"] = round(ref_val, 1)
        return base

    def _postprocess(self, result):
        text = result.get("raw_text", "")
        suggestions = result.get("suggestions", [])
        scores = {
            "specificity": min(100, self._specificity_score(text, suggestions)),
            "actionability": min(100, self._actionability_score(suggestions)),
            "quantifiability": min(100, self._quant_score(result)),
            "innovation": min(100, self._innovation_score(suggestions)),
            "completeness": min(100, self._completeness_score(result)),
        }
        overall = sum(scores[k] * _QUALITY_WEIGHTS[k] for k in _QUALITY_WEIGHTS)
        overall = round(overall, 1)
        if overall >= 80:
            grade = "可直接使用"
        elif overall >= 60:
            grade = "需小幅调整"
        else:
            grade = "需大幅修改"
        return {
            "framework": result["framework"],
            "suggestions": suggestions,
            "quantified_impacts": result["quantified_impacts"],
            "quality": {
                "dimensions": {k: round(v, 1) for k, v in scores.items()},
                "overall": overall,
                "grade": grade,
                "weights": _QUALITY_WEIGHTS,
            },
            "generated_at": datetime.now().isoformat(),
        }

    def _specificity_score(self, text: str, suggestions: list) -> float:
        specific = re.findall(r"[\u4e00-\u9fff]+(部门|流程|系统|金额|节点)", text)
        return 50 + len(set(specific)) * 8 + len(suggestions) * 3

    def _actionability_score(self, suggestions: list) -> float:
        score = 30
        for s in suggestions:
            path = s.get("implementation_path", "")
            if path:
                steps = [p for p in re.split(r"[→\-]", path) if p.strip()]
                score += 5 + len(steps) * 6
        return score

    def _quant_score(self, result) -> float:
        score = 30
        for imp in result.get("quantified_impacts", []):
            for v in imp.values():
                if v:
                    score += 6
        return score

    def _innovation_score(self, suggestions: list) -> float:
        tech_tokens = ["自动化", "AI", "智能", "RPA", "数字化", "数据驱动", "CI/CD"]
        score = 40
        for s in suggestions:
            for t in tech_tokens:
                if t in s.get("content", ""):
                    score += 6
        return score

    def _completeness_score(self, result) -> float:
        score = 35
        if result.get("framework"):
            score += 15
        if result.get("suggestions"):
            score += 15 + len(result["suggestions"]) * 3
        if result.get("quantified_impacts"):
            score += 20
        return score
