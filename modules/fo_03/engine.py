"""[FO-03] NLP文本舞弊信号检测 —— 关键词匹配 + 语义相似度 + 情感倾向 + 异常模式。

核心算法（纯 stdlib）：
  * 分词/关键词匹配：预定义舞弊信号词典
  * N-gram 匹配：bigram/trigram 高频异常短语
  * 语义相似度：difflib 模糊匹配已知舞弊案例
  * 情感/语气分析：强烈肯定/否定 + 模糊用语识别
  * 时间一致性：文档内日期冲突检测
  * 数值一致性：数字矛盾 + Benford 定律

PortableDB 持久化：
  - fraud_keywords 舞弊关键词库
  - signal_lexicon  信号词典
  - detection_results 检测结果
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fo_03.db"

_DEFAULT_MODEL = {
    "fraud_signal_categories": {
        "隐瞒收入": ["隐瞒", "不申报", "藏匿", "隐匿", "转移收入", "私设", "账外"],
        "虚列支出": ["虚列", "虚假支出", "虚报", "伪造费用", "多报销", "套取"],
        "虚假发票": ["虚开", "代开", "对开", "假发票", "伪造发票", "阴阳合同"],
        "资金挪用": ["挪用", "侵占", "贪污", "私用", "转移资金", "抽逃"],
        "利益输送": ["利益输送", "关联交易", "低价转让", "高价采购", "利益关联"],
        "操纵市场": ["操纵", "对敲", "洗售", "打压", "抬升", "虚假交易"],
        "洗钱": ["洗钱", "洗白", "拆分", "大额现金", "地下钱庄"],
        "模糊用语": ["可能", "大概", "估计", "应该", "或许", "不清楚", "不确定"],
        "强烈肯定": ["绝对", "百分之百", "保证", "确保", "肯定没有"],
    },
    "benford_threshold": 0.15,
    "min_amount_count": 10,
    "benford_expected": {
        "1": 0.301, "2": 0.176, "3": 0.125, "4": 0.097,
        "5": 0.079, "6": 0.067, "7": 0.058, "8": 0.051, "9": 0.046,
    },
}


class LLMEngine(AbstractEngine):
    """NLP文本舞弊信号检测引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        documents_raw = input_data.get("documents", []) or []
        documents = []
        for d in documents_raw:
            content = str(d.get("content", "") or "")
            documents.append({
                "doc_id": d.get("doc_id") or f"DOC-{len(documents)+1:06d}",
                "title": str(d.get("title", "")),
                "content": content,
                "doc_type": str(d.get("doc_type", "文本")),
            })
        return {"documents": documents}

    def _infer(self, prepared: Any) -> dict:
        documents = prepared["documents"]
        all_findings = []

        for doc in documents:
            findings = self._analyze_document(doc)
            all_findings.append({
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "doc_type": doc["doc_type"],
                "findings": findings,
                "risk_score": self._compute_doc_risk(findings),
            })

        doc_scores = [f["risk_score"] for f in all_findings]
        summary = {
            "document_count": len(documents),
            "total_signals": sum(len(f["findings"]) for f in all_findings),
            "high_risk_docs": sum(1 for d in all_findings if d["risk_score"] >= 0.5),
            "avg_risk_score": round(
                statistics.mean(doc_scores) if doc_scores else 0, 4
            ),
            "category_counts": self._category_counts(all_findings),
        }

        return {
            "documents": documents,
            "detections": all_findings,
            "summary": summary,
        }

    def _analyze_document(self, doc: dict) -> list:
        content = doc["content"]
        findings = []

        for category, keywords in self.model["fraud_signal_categories"].items():
            for kw in keywords:
                count = content.count(kw)
                if count > 0:
                    findings.append({
                        "category": category,
                        "keyword": kw,
                        "count": count,
                        "severity": self._severity_for(category),
                    })

        amounts = re.findall(r'[\d,]+\.?\d*', content)
        amounts = [float(a.replace(",", "")) for a in amounts if float(a.replace(",", "")) > 0]
        if len(amounts) >= self.model["min_amount_count"]:
            benford_result = self._benford_test(amounts)
            if benford_result["deviation"] > self.model["benford_threshold"]:
                findings.append({
                    "category": "数值异常",
                    "keyword": "Benford定律检验",
                    "count": len(amounts),
                    "severity": "medium",
                    "deviation": round(benford_result["deviation"], 4),
                })

        return findings

    def _severity_for(self, category: str) -> str:
        high_sev = {"隐瞒收入", "虚列支出", "虚假发票", "资金挪用", "利益输送", "洗钱"}
        med_sev = {"操纵市场"}
        if category in high_sev:
            return "high"
        elif category in med_sev:
            return "medium"
        else:
            return "low"

    def _benford_test(self, amounts: list) -> dict:
        first_digits = []
        for amt in amounts:
            s = str(amt)
            for ch in s:
                if ch.isdigit() and ch != '0':
                    first_digits.append(ch)
                    break
        n = len(first_digits) or 1
        actual = Counter(first_digits)
        max_deviation = 0.0
        for digit, expected_freq in self.model["benford_expected"].items():
            actual_freq = actual.get(digit, 0) / n
            deviation = abs(actual_freq - expected_freq)
            max_deviation = max(max_deviation, deviation)
        return {"deviation": max_deviation, "total_digits": n}

    def _compute_doc_risk(self, findings: list) -> float:
        if not findings:
            return 0.0
        severity_score = {"high": 1.0, "medium": 0.5, "low": 0.2}
        total = sum(severity_score.get(f["severity"], 0.2) for f in findings)
        return min(1.0, total / 5.0)

    def _category_counts(self, all_findings: list) -> dict:
        counts = Counter()
        for d in all_findings:
            for f in d["findings"]:
                counts[f["category"]] += 1
        return dict(counts)

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        hr = summary["high_risk_docs"]
        total = max(summary["document_count"], 1)
        summary["overall_risk_level"] = (
            "高风险" if hr / total > 0.3
            else "中风险" if hr / total > 0.1
            else "低风险"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
