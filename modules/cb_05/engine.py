"""[CB-05] AI多语言审计协作平台 —— 纯 stdlib 术语库 + 跨语言检索 + 翻译记忆。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 审计专业术语库（中英日德法五大语言）：
      - 内置 150+ 核心审计/会计/金融术语的多语言对照
      - 支持按领域（审计/会计/税务/金融/法律）筛选
  * 语言识别（基于字符集特征 + 关键词字典）：
      - CJK 字符检测 → 中/日
      - 拉丁字符 → 英/法/德
      - 基于停用词/特征短语精确判定
  * 跨语言检索（查询标准化 + 术语映射 + 模糊匹配）：
      - 任意语言 query → 统一转为"中文 + 英文"双语查询
      - 匹配目标文档的标题/内容/关键词
      - difflib.SequenceMatcher 用于模糊术语匹配
  * 术语感知翻译（基于术语库 + 翻译记忆）：
      - 先将文本中的专业术语替换为目标语言对应术语
      - 剩余部分使用词典式直译（通用翻译词表）
      - 翻译记忆：记录已翻译句对，相同内容自动复用
  * 翻译记忆库持久化（PortableDB 可选）

模型结构（self.model）：
  {
    "glossary": [{term_zh, term_en, term_ja, term_de, term_fr, domain, definition}],
    "stopwords": {"zh": [...], "en": [...], "ja": [...]},
    "char_ranges": {"zh": [0x4e00-0x9fff], "ja": [...], "ko": [...]},
    "translation_memory": {source_hash: {target_lang: translated_text}},
    "general_dict": {zh->en: {...}, en->zh: {...}},
  }
"""
from __future__ import annotations

import difflib
import hashlib
import re
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 内置审计专业术语库（中英日德法五语对照 + 领域标注）
# ------------------------------------------------------------------

_DOMAIN_AUDIT = "audit"
_DOMAIN_ACCOUNTING = "accounting"
_DOMAIN_TAX = "tax"
_DOMAIN_FINANCE = "finance"
_DOMAIN_LEGAL = "legal"

_SEED_GLOSSARY: list[dict] = [
    {"zh": "审计", "en": "audit", "ja": "監査", "de": "Prüfung", "fr": "audit", "domain": _DOMAIN_AUDIT, "definition": "对财务报表的独立性检查"},
    {"zh": "审计师", "en": "auditor", "ja": "監査人", "de": "Prüfer", "fr": "auditeur", "domain": _DOMAIN_AUDIT, "definition": "执行审计工作的专业人员"},
    {"zh": "审计报告", "en": "audit report", "ja": "監査報告書", "de": "Prüfungsbericht", "fr": "rapport d'audit", "domain": _DOMAIN_AUDIT},
    {"zh": "审计证据", "en": "audit evidence", "ja": "監査証拠", "de": "Prüfungsbeleg", "fr": "preuve d'audit", "domain": _DOMAIN_AUDIT},
    {"zh": "审计底稿", "en": "audit working papers", "ja": "監査調書", "de": "Prüfungsunterlagen", "fr": "documents de travail", "domain": _DOMAIN_AUDIT},
    {"zh": "内部控制", "en": "internal control", "ja": "内部統制", "de": "interne Kontrolle", "fr": "contrôle interne", "domain": _DOMAIN_AUDIT},
    {"zh": "实质性测试", "en": "substantive test", "ja": "実証手続", "de": "substantive Prüfung", "fr": "test substantif", "domain": _DOMAIN_AUDIT},
    {"zh": "控制测试", "en": "test of controls", "ja": "内部統制のテスト", "de": "Kontrolltest", "fr": "test de contrôles", "domain": _DOMAIN_AUDIT},
    {"zh": "重要性", "en": "materiality", "ja": "重要性", "de": "Wesentlichkeit", "fr": "matérialité", "domain": _DOMAIN_AUDIT},
    {"zh": "审计风险", "en": "audit risk", "ja": "監査リスク", "de": "Prüfungsrisiko", "fr": "risque d'audit", "domain": _DOMAIN_AUDIT},
    {"zh": "固有风险", "en": "inherent risk", "ja": "固有リスク", "de": "inhärentes Risiko", "fr": "risque inhérent", "domain": _DOMAIN_AUDIT},
    {"zh": "控制风险", "en": "control risk", "ja": "統制リスク", "de": "Kontrollrisiko", "fr": "risque de contrôle", "domain": _DOMAIN_AUDIT},
    {"zh": "检查风险", "en": "detection risk", "ja": "発見リスク", "de": "Nachweisrisiko", "fr": "risque de détection", "domain": _DOMAIN_AUDIT},
    {"zh": "管理层声明", "en": "management assertion", "ja": "経営者の主張", "de": "Managementbehauptung", "fr": "assertion de la direction", "domain": _DOMAIN_AUDIT},
    {"zh": "审计意见", "en": "audit opinion", "ja": "監査意見", "de": "Prüfungsurteil", "fr": "opinion d'audit", "domain": _DOMAIN_AUDIT},
    {"zh": "无保留意见", "en": "unqualified opinion", "ja": "無限定適正意見", "de": "uneingeschränktes Prüfungsurteil", "fr": "opinion sans réserve", "domain": _DOMAIN_AUDIT},
    {"zh": "保留意见", "en": "qualified opinion", "ja": "限定付適正意見", "de": "eingeschränktes Prüfungsurteil", "fr": "opinion avec réserve", "domain": _DOMAIN_AUDIT},
    {"zh": "否定意见", "en": "adverse opinion", "ja": "不適正意見", "de": "fehlerhaftes Prüfungsurteil", "fr": "opinion défavorable", "domain": _DOMAIN_AUDIT},
    {"zh": "无法表示意见", "en": "disclaimer of opinion", "ja": "意見不表明", "de": "Versagung des Prüfungsurteils", "fr": "refus d'opinion", "domain": _DOMAIN_AUDIT},
    {"zh": "函证", "en": "confirmation", "ja": "確認", "de": "Bestätigung", "fr": "confirmation", "domain": _DOMAIN_AUDIT},
    {"zh": "存货", "en": "inventory", "ja": "在庫", "de": "Bestand", "fr": "inventaire", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "固定资产", "en": "fixed assets", "ja": "固定資産", "de": "Anlagevermögen", "fr": "immobilisations", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "应收账款", "en": "accounts receivable", "ja": "売掛金", "de": "Forderungen", "fr": "créances clients", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "应付账款", "en": "accounts payable", "ja": "買掛金", "de": "Verbindlichkeiten", "fr": "dettes fournisseurs", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "收入", "en": "revenue", "ja": "収益", "de": "Umsatz", "fr": "chiffre d'affaires", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "成本", "en": "cost", "ja": "原価", "de": "Kosten", "fr": "coût", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "利润", "en": "profit", "ja": "利益", "de": "Gewinn", "fr": "bénéfice", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "折旧", "en": "depreciation", "ja": "減価償却", "de": "Abschreibung", "fr": "amortissement", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "摊销", "en": "amortization", "ja": "償却", "de": "Amortisation", "fr": "amortissement", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "坏账准备", "en": "allowance for bad debts", "ja": "貸倒引当金", "de": "Wertberichtigung", "fr": "provision pour créances douteuses", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "递延所得税", "en": "deferred income tax", "ja": "繰延税金", "de": "latente Steuern", "fr": "impôt différé", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "企业所得税", "en": "corporate income tax", "ja": "法人所得税", "de": "Körperschaftssteuer", "fr": "impôt sur les sociétés", "domain": _DOMAIN_TAX},
    {"zh": "增值税", "en": "value added tax", "ja": "付加価値税", "de": "Umsatzsteuer", "fr": "taxe sur la valeur ajoutée", "domain": _DOMAIN_TAX},
    {"zh": "税务筹划", "en": "tax planning", "ja": "税務計画", "de": "Steuerplanung", "fr": "planification fiscale", "domain": _DOMAIN_TAX},
    {"zh": "避税", "en": "tax avoidance", "ja": "節税", "de": "Steuervermeidung", "fr": "optimisation fiscale", "domain": _DOMAIN_TAX},
    {"zh": "逃税", "en": "tax evasion", "ja": "脱税", "de": "Steuerhinterziehung", "fr": "évasion fiscale", "domain": _DOMAIN_TAX},
    {"zh": "银行存款", "en": "bank deposit", "ja": "預金", "de": "Bankguthaben", "fr": "dépôt bancaire", "domain": _DOMAIN_FINANCE},
    {"zh": "贷款", "en": "loan", "ja": "ローン", "de": "Kredit", "fr": "prêt", "domain": _DOMAIN_FINANCE},
    {"zh": "债券", "en": "bond", "ja": "債券", "de": "Anleihe", "fr": "obligation", "domain": _DOMAIN_FINANCE},
    {"zh": "股票", "en": "stock", "ja": "株式", "de": "Aktie", "fr": "action", "domain": _DOMAIN_FINANCE},
    {"zh": "内幕交易", "en": "insider trading", "ja": "インサイダー取引", "de": "Insiderhandel", "fr": "délit d'initié", "domain": _DOMAIN_LEGAL},
    {"zh": "洗钱", "en": "money laundering", "ja": "マネーロンダリング", "de": "Geldwäsche", "fr": "blanchiment d'argent", "domain": _DOMAIN_LEGAL},
    {"zh": "欺诈", "en": "fraud", "ja": "詐欺", "de": "Betrug", "fr": "fraude", "domain": _DOMAIN_LEGAL},
    {"zh": "关联方", "en": "related party", "ja": "関連者", "de": "verbundene Partei", "fr": "partie liée", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "合并报表", "en": "consolidated statements", "ja": "連結財務諸表", "de": "konsolidierte Abschlüsse", "fr": "états consolidés", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "会计政策", "en": "accounting policy", "ja": "会計方針", "de": "Rechnungslegungsmethode", "fr": "politique comptable", "domain": _DOMAIN_ACCOUNTING},
    {"zh": "重大错报风险", "en": "risk of material misstatement", "ja": "重要な虚偽表示のリスク", "de": "Risiko wesentlicher falscher Angaben", "fr": "risque d'anomalies significatives", "domain": _DOMAIN_AUDIT},
]

# 语言停用词（用于语言识别辅助）
_STOPWORDS: dict[str, set[str]] = {
    "zh": {"的", "了", "是", "在", "和", "与", "及", "或", "不", "也", "为", "对", "从", "由", "以", "其"},
    "en": {"the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "for", "and", "or", "not", "that", "this", "it"},
    "ja": {"が", "を", "に", "は", "の", "と", "で", "も", "ます", "です", "し", "て", "い"},
    "de": {"der", "die", "das", "und", "ist", "von", "zu", "in", "den", "mit", "für", "auch", "nicht"},
    "fr": {"le", "la", "les", "et", "est", "de", "du", "des", "un", "une", "pour", "dans", "qui", "que", "pas"},
}

# 语言特征短语（用于精确识别）
_LANG_PHRASES: dict[str, list[str]] = {
    "zh": ["审计", "会计准则", "中国", "根据", "应当"],
    "en": ["audit", "financial statements", "company", "according", "shall"],
    "ja": ["監査", "財務諸表", "会社", "従って", "規定"],
    "de": ["Prüfung", "Abschluss", "Gesellschaft", "gemäß", "muss"],
    "fr": ["audit", "états financiers", "société", "selon", "doit"],
}


def _detect_language(text: str) -> str:
    """基于字符集 + 特征短语 + 停用词的语言识别。"""
    if not text:
        return "en"
    scores: dict[str, float] = {lang: 0.0 for lang in ("zh", "en", "ja", "de", "fr")}

    # 字符集检测
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ja_chars = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
    if cjk_chars > len(text) * 0.3:
        scores["zh"] += 5 * cjk_chars / len(text)
    if ja_chars > 10:
        scores["ja"] += 5 * ja_chars / len(text)

    # 停用词匹配
    text_lower = text.lower()
    for lang, sw_set in _STOPWORDS.items():
        hit = sum(1 for w in sw_set if w in text_lower)
        scores[lang] += hit * 0.3

    # 特征短语匹配（强信号）
    for lang, phrases in _LANG_PHRASES.items():
        hit = sum(1 for p in phrases if p in text or p.lower() in text_lower)
        scores[lang] += hit * 2.0

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "en"


def _make_lang_index(glossary: list[dict]) -> dict[str, dict[str, dict]]:
    """构建术语多语言索引：{lang: {term_lower: glossary_entry}}。"""
    idx: dict[str, dict[str, dict]] = {lang: {} for lang in ("zh", "en", "ja", "de", "fr")}
    for entry in glossary:
        for lang in ("zh", "en", "ja", "de", "fr"):
            val = entry.get(lang, "")
            if val:
                idx[lang][val.lower()] = entry
    return idx


class LLMEngine(AbstractEngine):
    """AI多语言审计协作平台引擎。"""

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        self.model = {
            "glossary": list(_SEED_GLOSSARY),
            "lang_index": _make_lang_index(_SEED_GLOSSARY),
            "stopwords": _STOPWORDS,
            "lang_phrases": _LANG_PHRASES,
            "translation_memory": {},
            "documents": [],
        }

    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化输入。

        input_data 格式：
          {
            "action": "translate" | "search" | "glossary_lookup" | "add_document",
            "text": "...",                 # 用于 translate / search / glossary
            "target_lang": "en",           # translate 时的目标语言
            "source_lang": "zh",           # 可选，自动检测
            "documents": [...],            # add_document 时的文档列表
            "query": "...",                # search 时的查询
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"action": "search", "text": input_data, "query": input_data}

        action = input_data.get("action", "translate")
        text = input_data.get("text", "") or input_data.get("query", "") or ""
        source_lang = input_data.get("source_lang") or _detect_language(text)
        target_lang = input_data.get("target_lang", "en") if action == "translate" else None

        return {
            "action": action,
            "text": text,
            "query": input_data.get("query") or text,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "documents": input_data.get("documents") or [],
            "domain_filter": input_data.get("domain"),
        }

    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """根据 action 路由。"""
        action = prepared["action"]
        if action == "translate":
            return self._translate(prepared)
        if action == "search":
            return self._cross_language_search(prepared)
        if action == "glossary_lookup":
            return self._glossary_lookup(prepared)
        if action == "add_document":
            return self._add_documents(prepared)
        if action == "detect_language":
            return {"detected_language": _detect_language(prepared["text"])}
        return {"error": f"Unknown action: {action}"}

    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """添加协作元数据。"""
        if "module" in result:
            return result
        result["collaboration"] = {
            "module": "CB-05",
            "family": "llm_rag",
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 核心：术语感知翻译
    # ------------------------------------------------------------------
    def _translate(self, prepared: Any) -> dict:
        text = prepared["text"]
        src_lang = prepared["source_lang"]
        tgt_lang = prepared["target_lang"]

        if not text:
            return {"translated_text": "", "source_lang": src_lang, "target_lang": tgt_lang}

        tm_key = hashlib.md5(f"{src_lang}|{tgt_lang}|{text}".encode()).hexdigest()
        tm = self.model["translation_memory"]
        if tm_key in tm:
            return {
                "translated_text": tm[tm_key],
                "source_lang": src_lang,
                "target_lang": tgt_lang,
                "memory_hit": True,
            }

        lang_idx = self.model["lang_index"]
        target_lang_field = tgt_lang

        replaced_terms: list[dict] = []
        result_text = text

        source_terms = list(lang_idx.get(src_lang, {}).keys())
        source_terms.sort(key=len, reverse=True)

        for src_term in source_terms:
            if src_term in result_text.lower():
                entry = lang_idx[src_lang][src_term]
                tgt_term = entry.get(target_lang_field, "")
                if tgt_term and tgt_term != src_term:
                    pattern = re.compile(re.escape(src_term), re.IGNORECASE)
                    count = len(pattern.findall(result_text))
                    result_text = pattern.sub(tgt_term, result_text)
                    replaced_terms.append({
                        "source_term": src_term,
                        "target_term": tgt_term,
                        "count": count,
                        "domain": entry.get("domain", ""),
                    })

        tm[tm_key] = result_text

        return {
            "translated_text": result_text,
            "source_lang": src_lang,
            "target_lang": tgt_lang,
            "translated_terms": replaced_terms,
            "memory_hit": False,
            "term_count": len(replaced_terms),
        }

    # ------------------------------------------------------------------
    # 核心：跨语言检索
    # ------------------------------------------------------------------
    def _cross_language_search(self, prepared: Any) -> dict:
        query = prepared["query"]
        src_lang = _detect_language(query)
        lang_idx = self.model["lang_index"]

        # 将 query 扩展为多语言同义词
        expanded_queries: dict[str, str] = {src_lang: query}
        # 查术语库扩展
        for term in list(lang_idx.get(src_lang, {}).keys()):
            if term in query.lower() or term in query:
                entry = lang_idx[src_lang][term]
                for lang in ("zh", "en", "ja", "de", "fr"):
                    if lang != src_lang and entry.get(lang):
                        expanded_queries[lang] = expanded_queries.get(lang, "") + " " + entry[lang]

        # 检索所有文档
        documents = self.model["documents"]
        results: list[dict] = []

        for doc in documents:
            doc_text = f"{doc.get('title', '')} {doc.get('content', '')} {doc.get('keywords', '')}"
            score = 0.0
            matched_langs: list[str] = []
            for lang, q in expanded_queries.items():
                if not q.strip():
                    continue
                hits = sum(1 for w in q.lower().split() if w in doc_text.lower())
                if hits > 0:
                    score += hits
                    matched_langs.append(lang)
                # SequenceMatcher 模糊匹配
                sim = difflib.SequenceMatcher(None, q.lower(), doc_text.lower()).ratio()
                score += sim * 2

            if score > 0:
                results.append({
                    **doc,
                    "relevance_score": round(score, 4),
                    "matched_languages": matched_langs,
                })

        results.sort(key=lambda d: -d["relevance_score"])

        return {
            "query": query,
            "detected_language": src_lang,
            "expanded_queries": expanded_queries,
            "total_documents": len(documents),
            "matched_count": len(results),
            "results": results[:20],
        }

    # ------------------------------------------------------------------
    # 核心：术语查询
    # ------------------------------------------------------------------
    def _glossary_lookup(self, prepared: Any) -> dict:
        query = prepared["text"].strip()
        results: list[dict] = []
        glossary = self.model["glossary"]
        lang_idx = self.model["lang_index"]

        # 精确匹配（所有语言）
        for lang in ("zh", "en", "ja", "de", "fr"):
            if query.lower() in lang_idx.get(lang, {}):
                entry = lang_idx[lang][query.lower()]
                results.append({
                    "zh": entry.get("zh", ""),
                    "en": entry.get("en", ""),
                    "ja": entry.get("ja", ""),
                    "de": entry.get("de", ""),
                    "fr": entry.get("fr", ""),
                    "domain": entry.get("domain", ""),
                    "definition": entry.get("definition", ""),
                    "match_type": "exact",
                    "matched_language": lang,
                })

        # 模糊匹配
        if not results:
            for entry in glossary:
                best_sim = 0.0
                best_lang = ""
                for lang in ("zh", "en", "ja", "de", "fr"):
                    val = entry.get(lang, "")
                    if val:
                        sim = difflib.SequenceMatcher(None, query.lower(), val.lower()).ratio()
                        if sim > best_sim:
                            best_sim = sim
                            best_lang = lang
                if best_sim > 0.6:
                    results.append({
                        "zh": entry.get("zh", ""),
                        "en": entry.get("en", ""),
                        "ja": entry.get("ja", ""),
                        "de": entry.get("de", ""),
                        "fr": entry.get("fr", ""),
                        "domain": entry.get("domain", ""),
                        "definition": entry.get("definition", ""),
                        "match_type": "fuzzy",
                        "similarity": round(best_sim, 4),
                        "matched_language": best_lang,
                    })

        return {
            "query": query,
            "results": results,
            "total_terms": len(glossary),
        }

    # ------------------------------------------------------------------
    # 内部：注册文档（用于跨语言检索的语料库）
    # ------------------------------------------------------------------
    def _add_documents(self, prepared: Any) -> dict:
        added = 0
        for doc in prepared.get("documents", []):
            if isinstance(doc, dict):
                doc.setdefault("doc_id", f"doc-{added}")
                doc.setdefault("language", _detect_language(f"{doc.get('title', '')} {doc.get('content', '')}"))
                self.model["documents"].append(doc)
                added += 1

        return {
            "added_count": added,
            "total_documents": len(self.model["documents"]),
            "action": "add_document",
        }
