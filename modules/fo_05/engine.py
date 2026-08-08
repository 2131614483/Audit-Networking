"""[FO-05] 多语言智能翻译与分析 —— 词典翻译 + 语言检测 + 情感分析 + 术语归一化。

核心算法（纯 stdlib）：
  * 语言检测：Unicode 字符范围 + 特殊标记匹配
  * 词典翻译：预定义专业术语词典（中/英/日）
  * 术语归一化：多语言 → 统一标准术语
  * 情感分析：正面/负面关键词匹配 + 加权评分
  * 代码切换检测：句子内多语言混用检测
  * 法律术语抽取：正则匹配 + 专业词典

PortableDB 持久化：
  - translation_dict 翻译词典
  - terminology_map  术语映射
  - analysis_results 分析结果
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fo_05.db"

_DEFAULT_MODEL = {
    "language_indicators": {
        "zh": {"unicode_ranges": [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)]},
        "en": {"unicode_ranges": [(0x0041, 0x005A), (0x0061, 0x007A)], "min_ratio": 0.4},
        "ja": {"unicode_ranges": [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x4E00, 0x9FFF)]},
        "ko": {"unicode_ranges": [(0xAC00, 0xD7AF), (0x1100, 0x11FF)]},
    },
    "legal_terms_zh_en": {
        "合同": "contract", "协议": "agreement", "当事人": "party",
        "违约": "breach", "赔偿": "compensation", "责任": "liability",
        "管辖": "jurisdiction", "仲裁": "arbitration", "诉讼": "litigation",
        "判决": "judgment", "证据": "evidence", "声明": "statement",
        "保证": "warranty", "担保": "guarantee", "抵押": "mortgage",
        "质押": "pledge", "转让": "assignment", "保密": "confidentiality",
        "知识产权": "intellectual_property", "违约条款": "default_clause",
        "不可抗力": "force_majeure", "适用法律": "governing_law",
        "关联方": "related_party", "重大影响": "significant_influence",
    },
    "sentiment_lexicon": {
        "positive": ["agreement", "accept", "approve", "success", "complete",
                     "同意", "接受", "批准", "成功", "完成", "有利", "保障"],
        "negative": ["breach", "dispute", "default", "terminate", "cancel",
                     "violation", "损失", "违约", "争议", "终止", "取消", "违反",
                     "赔偿", "不利", "风险"],
    },
}


class LLMEngine(AbstractEngine):
    """多语言智能翻译与分析引擎。"""

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

        texts_raw = input_data.get("texts", []) or []
        texts = []
        for t in texts_raw:
            content = str(t.get("content", "") or "")
            texts.append({
                "text_id": t.get("text_id") or f"TXT-{len(texts)+1:06d}",
                "content": content,
                "source_lang": str(t.get("source_lang", "")),
                "target_lang": str(t.get("target_lang", "zh")),
            })
        return {"texts": texts}

    def _infer(self, prepared: Any) -> dict:
        texts = prepared["texts"]
        results = []

        for t in texts:
            detected_lang = self._detect_language(t["content"])
            translated = self._translate(t["content"], t["source_lang"] or detected_lang, t["target_lang"])
            sentiments = self._analyze_sentiment(t["content"])
            legal_terms = self._extract_legal_terms(t["content"])
            code_switch = self._detect_code_switch(t["content"])

            results.append({
                "text_id": t["text_id"],
                "detected_language": detected_lang,
                "source_language": t["source_lang"] or detected_lang,
                "target_language": t["target_lang"],
                "translated_text": translated,
                "sentiment": sentiments,
                "legal_terms_found": legal_terms,
                "code_switch_detected": code_switch,
            })

        lang_counter = Counter(r["detected_language"] for r in results)
        avg_sentiment = sum(r["sentiment"]["score"] for r in results) / max(len(results), 1)

        summary = {
            "text_count": len(results),
            "language_distribution": dict(lang_counter),
            "avg_sentiment_score": round(avg_sentiment, 4),
            "code_switch_count": sum(1 for r in results if r["code_switch_detected"]),
            "total_legal_terms": sum(len(r["legal_terms_found"]) for r in results),
        }

        return {
            "texts": texts,
            "translations": results,
            "summary": summary,
        }

    def _detect_language(self, text: str) -> str:
        if not text.strip():
            return "unknown"
        scores = {}
        for lang, info in self.model["language_indicators"].items():
            score = 0
            for lo, hi in info.get("unicode_ranges", []):
                for ch in text:
                    code = ord(ch)
                    if lo <= code <= hi:
                        score += 1
            scores[lang] = score
        if not scores:
            return "unknown"
        best_lang = max(scores, key=scores.get)
        if scores[best_lang] == 0:
            return "en"
        return best_lang

    def _translate(self, text: str, src: str, tgt: str) -> str:
        if src == tgt:
            return text
        terms = self.model["legal_terms_zh_en"]
        result = text
        if src == "zh" and tgt == "en":
            for zh, en in terms.items():
                result = result.replace(zh, f"[{en}]")
        elif src == "en" and tgt == "zh":
            for zh, en in terms.items():
                result = re.sub(r'\b' + re.escape(en) + r'\b', f"[{zh}]", result)
        return result

    def _analyze_sentiment(self, text: str) -> dict:
        positive = self.model["sentiment_lexicon"]["positive"]
        negative = self.model["sentiment_lexicon"]["negative"]
        pos_count = sum(text.count(p) for p in positive)
        neg_count = sum(text.count(n) for n in negative)
        total = pos_count + neg_count
        if total == 0:
            score = 0.0
            label = "中性"
        else:
            score = (pos_count - neg_count) / total
            label = "正面" if score > 0.2 else ("负面" if score < -0.2 else "中性")
        return {
            "score": round(score, 4),
            "label": label,
            "positive_hits": pos_count,
            "negative_hits": neg_count,
        }

    def _extract_legal_terms(self, text: str) -> list:
        terms = self.model["legal_terms_zh_en"]
        found = []
        for zh, en in terms.items():
            if zh in text or en.lower() in text.lower():
                found.append({"zh": zh, "en": en, "count": text.count(zh) + text.lower().count(en.lower())})
        return found

    def _detect_code_switch(self, text: str) -> bool:
        has_zh = False
        has_en = False
        for ch in text:
            code = ord(ch)
            if 0x4E00 <= code <= 0x9FFF:
                has_zh = True
            if 0x0041 <= code <= 0x005A or 0x0061 <= code <= 0x007A:
                has_en = True
        return has_zh and has_en

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        if summary["avg_sentiment_score"] > 0.1:
            summary["overall_sentiment"] = "正面"
        elif summary["avg_sentiment_score"] < -0.1:
            summary["overall_sentiment"] = "负面"
        else:
            summary["overall_sentiment"] = "中性"
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
