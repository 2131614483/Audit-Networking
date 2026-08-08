"""[CO-01] 全球法规智能监控平台核心引擎 —— 纯 stdlib 法规监控算法。

算法设计（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，不引入任何第三方依赖）：

  * 多语言法规分类（关键词词典 + TF-IDF，纯 math 实现）：
      - 中英双语关键词词典（category_keywords.jsonl）：每个分类含 zh/en 关键词
      - 中文关键词用子串计数（无分词依赖），英文关键词用词边界匹配（大小写不敏感）
      - TF = 关键词在法规文本中的出现次数；IDF = log((N+1)/(df+1)) + 1，
        N 为分类总数，df 为含该关键词的分类数（跨分类区分度）
      - 分类得分 = Σ(TF * IDF)，归一化为置信度；取最高得分分类，无命中则归 "other"
  * 法规影响评估（基于分类 + 关键词 + 企业行业匹配）：
      - 相关性评分 relevance = 0.50*cat_conf + 0.25*country_match
                              + 0.15*industry_match + 0.10*scope_match
        （industry_match：1.0 命中本行业 / 0.5 通用法规 / 0.0 无关）
      - 基础影响等级：高 ≥0.7 / 中 0.4–0.7 / 低 <0.4
  * 多语言处理：中英双语关键词同时匹配；识别适用范围（国家/行业/企业规模）
  * 订阅匹配：对照企业订阅规则（行业/国家/关注分类），命中则标记推送

execute() 模板方法不可修改：预处理 → 推理 → 后处理。
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# 模块根目录（定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "co_01.db"

# 分类 → 适用行业映射（用于行业相关性匹配）
# "all" 表示通用法规（适用所有行业，industry_match 取 0.5）
_CATEGORY_INDUSTRIES: dict[str, list[str]] = {
    "tax": ["all"],
    "finance": ["finance", "banking", "insurance", "securities"],
    "environmental": ["manufacturing", "mining", "energy", "chemical", "all"],
    "data_security": ["technology", "finance", "telecom", "all"],
    "labor": ["all"],
    "antitrust": ["all"],
    "accounting": ["all"],
}

# 证券类关键词（用于上市企业强制推送判定；仅保留强信号词，剔除 disclosure/信息披露
# 等通用词，避免误判 ESG / 会计准则类法规为证券法规）
_SECURITIES_KEYWORDS_ZH = {"证券", "上市公司", "招股说明书"}
_SECURITIES_KEYWORDS_EN = {"securities", "listed company", "prospectus"}

# ---------- 表 schema ----------
_REGULATIONS_SCHEMA = {
    "reg_id": "TEXT",
    "title": "TEXT",
    "title_en": "TEXT",
    "body": "TEXT",
    "agency": "TEXT",
    "country": "TEXT",
    "country_name": "TEXT",
    "language": "TEXT",
    "publish_date": "TEXT",
    "effective_date": "TEXT",
    "url": "TEXT",
    "applicable_size": "TEXT",
    "source": "TEXT",
    "created_at": "DATETIME",
}
_REGULATION_CATEGORIES_SCHEMA = {
    "reg_id": "TEXT",
    "category": "TEXT",
    "confidence": "REAL",
    "matched_keywords": "JSON",
    "created_at": "DATETIME",
}
_IMPACT_ASSESSMENTS_SCHEMA = {
    "reg_id": "TEXT",
    "impact_level": "TEXT",
    "relevance": "REAL",
    "country_match": "INTEGER",
    "industry_match": "REAL",
    "scope_match": "INTEGER",
    "applicable_industries": "JSON",
    "applicable_scope": "TEXT",
    "push": "INTEGER",
    "matched_rules": "JSON",
    "reason": "TEXT",
    "created_at": "DATETIME",
}
_SUBSCRIPTION_RULES_SCHEMA = {
    "rule_id": "TEXT",
    "industry": "TEXT",
    "country": "TEXT",
    "categories": "JSON",
    "priority": "TEXT",
    "desc": "TEXT",
    "created_at": "DATETIME",
}

# HTML 标签清洗正则
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# 多空白合一
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """去除 HTML 标签并将多空白合一。"""
    if not isinstance(text, str):
        text = str(text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _normalize_date(raw: Any) -> str:
    """日期归一化为 ISO 格式 YYYY-MM-DD。

    支持 YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD / YYYY年MM月DD日 等。
    无法解析时返回原始字符串。
    """
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    # YYYY年MM月DD日
    m = re.match(r"^(\d{4})\D(\d{1,2})\D(\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        try:
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        except ValueError:
            return s
    return s


def _count_substring(text: str, sub: str) -> int:
    """统计子串在文本中的非重叠出现次数（中文关键词用）。"""
    if not sub:
        return 0
    count = 0
    start = 0
    while True:
        idx = text.find(sub, start)
        if idx == -1:
            break
        count += 1
        start = idx + len(sub)
    return count


def _count_word(text: str, word: str) -> int:
    """英文单词/短语在文本中的词边界匹配次数（大小写不敏感）。"""
    if not word:
        return 0
    pattern = r"\b" + re.escape(word) + r"\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))


class KGEngine(AbstractEngine):
    """全球法规智能监控引擎（纯 stdlib 实现）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        # 允许 config 覆盖 fixtures / db 路径，便于测试隔离
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载法规分类体系 + 订阅规则，初始化 PortableDB（建表 + 种子导入）。

        数据来源：
          1. tests/fixtures/category_keywords.jsonl  分类关键词词典
          2. tests/fixtures/subscription_rules.jsonl 企业订阅规则
          3. PortableDB subscription_rules 表（人工维护，最高优先级）
        """
        # 1. 初始化 PortableDB（中心化公用辐射）
        self.db = PortableDB(self.db_path)

        # 2. 建表（若不存在）
        if "regulations" not in self.db.tables():
            self.db.create_table("regulations", _REGULATIONS_SCHEMA)
        if "regulation_categories" not in self.db.tables():
            self.db.create_table("regulation_categories", _REGULATION_CATEGORIES_SCHEMA)
        if "impact_assessments" not in self.db.tables():
            self.db.create_table("impact_assessments", _IMPACT_ASSESSMENTS_SCHEMA)
        if "subscription_rules" not in self.db.tables():
            self.db.create_table("subscription_rules", _SUBSCRIPTION_RULES_SCHEMA)

        # 3. 若 subscription_rules 表为空，从 fixtures 导入种子数据（仅首次）
        if self.db.count("subscription_rules") == 0:
            sub_fixture = self.fixtures_dir / "subscription_rules.jsonl"
            if sub_fixture.exists():
                self.db.import_jsonl(
                    "subscription_rules", sub_fixture,
                    schema=_SUBSCRIPTION_RULES_SCHEMA, drop_if_exists=False,
                )

        # 4. 加载分类关键词词典（内存模型，每次加载读取最新 fixtures）
        category_keywords: dict[str, dict] = {}
        kw_fixture = self.fixtures_dir / "category_keywords.jsonl"
        if kw_fixture.exists():
            with open(kw_fixture, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json_loads(line)
                    cat = row.get("category")
                    if cat:
                        category_keywords[cat] = {
                            "category_zh": row.get("category_zh", cat),
                            "keywords_zh": list(row.get("keywords_zh", [])),
                            "keywords_en": list(row.get("keywords_en", [])),
                        }

        # 5. 预计算 IDF：df = 含该关键词的分类数；N = 分类总数
        n_categories = len(category_keywords)
        keyword_idf: dict[tuple[str, str], float] = {}
        df_counter: dict[tuple[str, str], int] = {}
        for cat, kws in category_keywords.items():
            for kw in kws.get("keywords_zh", []):
                key = ("zh", kw)
                df_counter[key] = df_counter.get(key, 0) + 1
            for kw in kws.get("keywords_en", []):
                key = ("en", kw)
                df_counter[key] = df_counter.get(key, 0) + 1
        for key, df in df_counter.items():
            keyword_idf[key] = math.log((n_categories + 1) / (df + 1)) + 1

        # 6. 加载订阅规则（DB 表 → 内存，含人工增量）
        subscription_rules: list[dict] = []
        for row in self.db.all("subscription_rules"):
            subscription_rules.append({
                "rule_id": row.get("rule_id"),
                "industry": row.get("industry", "all"),
                "country": row.get("country", "all"),
                "categories": row.get("categories") or [],
                "priority": row.get("priority", "medium"),
                "desc": row.get("desc", ""),
            })

        self.model = {
            "category_keywords": category_keywords,
            "keyword_idf": keyword_idf,
            "n_categories": n_categories,
            "subscription_rules": subscription_rules,
        }

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """提取法规列表与企业画像，清洗文本（去 HTML、统一标题、日期归一化）。"""
        # 懒加载：若未显式 setup()，execute() 时自动加载模型
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 regulations 列表与 enterprise 画像")

        enterprise = input_data.get("enterprise", {}) or {}
        raw_regs = input_data.get("regulations", [])
        if not isinstance(raw_regs, list):
            raise ValueError("input_data['regulations'] 必须为列表")

        cleaned_regs = []
        for r in raw_regs:
            if not isinstance(r, dict):
                continue
            reg_id = r.get("reg_id") or r.get("id") or ""
            title = r.get("title", "") or ""
            title_en = r.get("title_en", "") or ""
            body = _strip_html(r.get("body", "") or "")
            # 拼接分类用文本：标题（中英）+ 正文，统一小写用于英文匹配
            combined = " ".join([title, title_en, body])
            cleaned_regs.append({
                "reg_id": reg_id,
                "title": title.strip(),
                "title_en": title_en.strip(),
                "body": body,
                "combined_text": combined,
                "agency": r.get("agency", "") or "",
                "country": (r.get("country", "") or "").upper(),
                "country_name": r.get("country_name", "") or "",
                "language": (r.get("language", "") or "").lower(),
                "publish_date": _normalize_date(r.get("publish_date")),
                "effective_date": _normalize_date(r.get("effective_date")),
                "url": r.get("url", "") or "",
                "applicable_size": r.get("applicable_size", "all") or "all",
                "source": r.get("source", input_data.get("source", "monitor")) or "monitor",
            })

        return {
            "enterprise": enterprise,
            "regulations": cleaned_regs,
            "source": input_data.get("source", "monitor"),
        }

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """四步推理：① 法规分类 ② 影响评估 ③ 多语言/适用范围 ④ 订阅匹配。"""
        model = self.model or {}
        category_keywords = model.get("category_keywords", {})
        keyword_idf = model.get("keyword_idf", {})
        subscription_rules = model.get("subscription_rules", [])

        enterprise = prepared.get("enterprise", {}) or {}
        ent_industries = [i.lower() for i in enterprise.get("industries", [])]
        ent_countries = [c.upper() for c in enterprise.get("countries", [])]
        ent_size = (enterprise.get("size", "all") or "all").lower()

        results = []
        for reg in prepared["regulations"]:
            text = reg["combined_text"]

            # ① 法规分类（关键词词典 + TF-IDF）
            category, confidence, matched_keywords = self._classify(
                text, category_keywords, keyword_idf
            )

            # ③ 多语言适用范围识别
            applicable_industries = _CATEGORY_INDUSTRIES.get(category, ["all"])
            applicable_scope = reg.get("applicable_size", "all")
            scope_match = self._scope_match(applicable_scope, ent_size)

            # ② 影响评估：相关性评分 + 影响等级
            country_match = 1 if reg["country"] in ent_countries else 0
            industry_match = self._industry_match(category, applicable_industries, ent_industries)
            relevance = round(
                0.50 * confidence
                + 0.25 * country_match
                + 0.15 * industry_match
                + 0.10 * scope_match,
                4,
            )
            impact_level = self._impact_level(relevance)

            # ④ 订阅匹配：对照企业订阅规则
            matched_rules = self._match_subscription(
                category, reg["country"], ent_industries, subscription_rules
            )
            subscription_match = len(matched_rules) > 0

            # 证券类法规标记（供 custom_rules 上市企业强制推送使用）
            is_securities = self._is_securities(text)

            results.append({
                "reg_id": reg["reg_id"],
                "title": reg["title"],
                "title_en": reg["title_en"],
                "body": reg["body"],
                "agency": reg["agency"],
                "country": reg["country"],
                "country_name": reg["country_name"],
                "language": reg["language"],
                "publish_date": reg["publish_date"],
                "effective_date": reg["effective_date"],
                "url": reg["url"],
                "applicable_size": reg["applicable_size"],
                "source": reg["source"],
                # 分类结果
                "category": category,
                "category_confidence": confidence,
                "matched_keywords": matched_keywords,
                # 影响评估
                "relevance": relevance,
                "impact_level": impact_level,
                "country_match": country_match,
                "industry_match": industry_match,
                "scope_match": scope_match,
                "applicable_industries": applicable_industries,
                "applicable_scope": applicable_scope,
                # 订阅匹配
                "subscription_match": subscription_match,
                "matched_rules": matched_rules,
                # 推送建议（基础：订阅命中即推送；阈值/业务规则在 custom 层增强）
                "push": subscription_match,
                "push_reasons": ["subscription_match"] if subscription_match else [],
                # 辅助标记
                "is_securities": is_securities,
            })
        return {
            "enterprise": enterprise,
            "regulations": results,
            "source": prepared.get("source"),
        }

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """汇总法规监控报告 + 统计（总数/各分类/各等级/推送数/覆盖国家）。"""
        regs = result.get("regulations", [])

        by_category: dict[str, int] = {}
        by_impact: dict[str, int] = {}
        covered_countries: set[str] = set()
        push_count = 0
        for r in regs:
            cat = r.get("category", "other")
            by_category[cat] = by_category.get(cat, 0) + 1
            lvl = r.get("impact_level", "low")
            by_impact[lvl] = by_impact.get(lvl, 0) + 1
            if r.get("country"):
                covered_countries.add(r["country"])
            if r.get("push"):
                push_count += 1

        result["statistics"] = {
            "total": len(regs),
            "by_category": by_category,
            "by_impact": by_impact,
            "push_count": push_count,
            "covered_countries": sorted(covered_countries),
        }
        return result

    # ------------------------------------------------------------------
    # 内部算法：分类 / 影响评估 / 订阅匹配
    # ------------------------------------------------------------------
    def _classify(
        self, text: str,
        category_keywords: dict[str, dict],
        keyword_idf: dict[tuple[str, str], float],
    ) -> tuple[str, float, list[str]]:
        """TF-IDF 关键词分类，返回 (分类, 置信度, 命中关键词列表)。

        分类得分 = Σ(tf * idf)（仅命中关键词计入）；置信度 = 该分类得分 / 总得分。
        """
        if not text or not category_keywords:
            return "other", 0.0, []

        scores: dict[str, float] = {}
        matched: dict[str, list[str]] = {}
        for cat, kws in category_keywords.items():
            raw_score = 0.0
            cat_matched: list[str] = []
            # 中文关键词：子串计数
            for kw in kws.get("keywords_zh", []):
                tf = _count_substring(text, kw)
                if tf > 0:
                    idf = keyword_idf.get(("zh", kw), 1.0)
                    raw_score += tf * idf
                    cat_matched.append(kw)
            # 英文关键词：词边界匹配（对原始大小写文本用 findall 不敏感）
            for kw in kws.get("keywords_en", []):
                tf = _count_word(text, kw)
                if tf > 0:
                    idf = keyword_idf.get(("en", kw), 1.0)
                    raw_score += tf * idf
                    cat_matched.append(kw)
            scores[cat] = raw_score
            matched[cat] = cat_matched

        total = sum(scores.values())
        if total <= 0:
            return "other", 0.0, []

        best_cat = max(scores, key=lambda c: scores[c])
        confidence = round(scores[best_cat] / total, 4)
        return best_cat, confidence, matched[best_cat]

    def _scope_match(self, applicable_scope: str, ent_size: str) -> int:
        """企业规模适用范围匹配：1 命中 / 0 不命中。"""
        scope = (applicable_scope or "all").lower()
        if scope == "all":
            return 1
        if scope == ent_size:
            return 1
        # large 范围包含 large 企业；all 范围包含所有
        if scope == "large" and ent_size == "large":
            return 1
        return 0

    def _industry_match(
        self, category: str,
        applicable_industries: list[str],
        ent_industries: list[str],
    ) -> float:
        """行业相关性：1.0 命中本行业 / 0.5 通用法规(all) / 0.0 无关。

        优先匹配具体行业（data_security 同时含 technology/finance 与 all，
        命中具体行业应取 1.0），仅在无具体命中时回退到通用 0.5。
        """
        for ind in ent_industries:
            if ind in applicable_industries:
                return 1.0
        if not applicable_industries or "all" in applicable_industries:
            return 0.5
        return 0.0

    def _impact_level(self, relevance: float) -> str:
        """基础影响等级：高 ≥0.7 / 中 0.4–0.7 / 低 <0.4。"""
        if relevance >= 0.7:
            return "high"
        if relevance >= 0.4:
            return "medium"
        return "low"

    def _match_subscription(
        self, category: str, country: str,
        ent_industries: list[str],
        subscription_rules: list[dict],
    ) -> list[str]:
        """订阅匹配：返回命中的规则 rule_id 列表。

        匹配条件：规则分类含该法规分类 AND（规则国家=all 或 命中法规国家）
                  AND（规则行业=all 或 命中企业任一行业）。
        """
        matched: list[str] = []
        for rule in subscription_rules:
            rule_cats = rule.get("categories", [])
            if category not in rule_cats:
                continue
            rule_country = (rule.get("country", "all") or "all").upper()
            if rule_country != "ALL" and rule_country != country:
                continue
            rule_industry = (rule.get("industry", "all") or "all").lower()
            if rule_industry != "all":
                if rule_industry not in ent_industries:
                    continue
            matched.append(rule.get("rule_id", ""))
        return matched

    def _is_securities(self, text: str) -> bool:
        """判断是否为证券类法规（上市企业强制推送用）。"""
        for kw in _SECURITIES_KEYWORDS_ZH:
            if kw in text:
                return True
        low = text.lower()
        for kw in _SECURITIES_KEYWORDS_EN:
            if kw in low:
                return True
        return False

    # ------------------------------------------------------------------
    # 订阅规则增量维护（人工维护 → PortableDB 持久化 + 内存即时合并）
    # ------------------------------------------------------------------
    def add_subscription_rule(
        self, rule_id: str, industry: str, country: str,
        categories: list[str], priority: str = "medium", desc: str = "",
    ) -> bool:
        """新增订阅规则 → 写入 PortableDB，并合并进当前内存模型。"""
        if self.db is None:
            self._load_model()
        assert self.db is not None
        self.db.insert("subscription_rules", {
            "rule_id": rule_id,
            "industry": industry,
            "country": country,
            "categories": categories,
            "priority": priority,
            "desc": desc,
            "created_at": datetime.now(),
        })
        model = self.model or {
            "category_keywords": {}, "keyword_idf": {}, "n_categories": 0,
            "subscription_rules": [],
        }
        model["subscription_rules"].append({
            "rule_id": rule_id,
            "industry": industry,
            "country": country,
            "categories": categories,
            "priority": priority,
            "desc": desc,
        })
        self.model = model
        return True

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 PortableDB 连接。"""
        if self.db is not None:
            self.db.close()
            self.db = None


# 模块内复用的 json 解析（避免重复 import）
def json_loads(line: str) -> dict:
    import json
    return json.loads(line)
