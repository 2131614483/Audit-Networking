"""ModuleMeta 数据类 + 家族分类 + 依赖/平台推断 + slug 派生。

零第三方依赖，纯标准库。被 parser.py / renderers.py / generate.py 复用。
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------- 业务域 → category 映射 ----------
CATEGORY_MAP = {
    "财务报表审计": "financial_audit",
    "内部审计": "internal_audit",
    "合规审计": "compliance_audit",
    "IT审计": "it_audit",
    "法务审计": "legal_audit",
    "税务审计": "tax_audit",
    "供应链审计": "supply_chain_audit",
    "ESG审计": "esg_audit",
    "IPO审计": "ipo_audit",
    "金融审计": "financial_services_audit",
    "跨境审计": "cross_border_audit",
    "持续审计": "continuous_audit",
}

# ---------- 家族分类规则（按优先级，先命中先返回） ----------
# (family_key, [触发关键词])
FAMILY_RULES = [
    ("federation", ["联邦学习"]),
    ("blockchain", ["区块链"]),
    ("cv", ["CV", "OCR", "计算机视觉", "卫星"]),
    ("kg_gnn", ["知识图谱", "GNN", "图神经"]),
    ("llm_rag", ["LLM", "大语言", "RAG"]),
    ("streaming", ["实时流", "流处理", "Kafka", "Flink"]),
    ("rpa", ["RPA"]),
    ("ml_nlp", ["ML", "XGBoost", "BERT", "NLP", "机器学习", "LightGBM",
                "Isolation", "Benford", "scikit", "GMM"]),
]

# 家族元信息：展示名、venv 名、引擎类名后缀
FAMILY_META = {
    "federation": {"display": "Federation Learning", "venv": "federation",
                   "engine_class": "FederationEngine"},
    "blockchain": {"display": "Blockchain", "venv": "blockchain",
                   "engine_class": "BlockchainEngine"},
    "cv": {"display": "Computer Vision", "venv": "cv",
           "engine_class": "CVEngine"},
    "kg_gnn": {"display": "Knowledge Graph / GNN", "venv": "kg",
               "engine_class": "KGEngine"},
    "llm_rag": {"display": "LLM / RAG", "venv": "llm",
                "engine_class": "LLMEngine"},
    "streaming": {"display": "Streaming", "venv": "streaming",
                  "engine_class": "StreamingEngine"},
    "rpa": {"display": "RPA", "venv": "rpa",
            "engine_class": "RPAEngine"},
    "ml_nlp": {"display": "ML / NLP", "venv": "ml",
               "engine_class": "MLEngine"},
}

# ---------- 平台依赖推断 ----------
# (关键词, 平台代号)  —— 5 大共享平台：adl/akg/lsb/rop/bce
PLATFORM_RULES = [
    (["知识图谱", "GNN", "图神经"], "akg"),
    (["LLM", "大语言", "RAG"], "lsb"),
    (["RPA"], "rop"),
    (["区块链"], "bce"),
    (["实时流", "Kafka", "Flink", "流处理"], "adl"),
]

PRIORITY_MAP = {"🔴": "high", "🟡": "medium", "🟢": "low"}


@dataclass
class ModuleMeta:
    """从一份方案 .md 解析出的模块元数据。"""
    id: str                       # "FA-02"
    name: str                     # "多源数据自动标准化"
    name_en: str                  # "fa_02"（slug 派生，作英文名占位）
    slug: str                     # 包名/目录名 "fa_02"
    category: str                 # "financial_audit"
    category_zh: str              # "财务报表审计"
    tech_stack_raw: str           # "BERT + XGBoost + NLP + 增量学习"
    tech_components: list = field(default_factory=list)   # ["BERT","XGBoost",...]
    family: str = "ml_nlp"        # 家族 key
    difficulty: int = 3           # ⭐ 数量
    priority: str = "medium"      # high/medium/low
    roi: str = ""                 # "0.5-1年"
    duration: str = ""            # 实施周期（schema B：如 "6个月"）
    budget: str = ""              # 投入预算（schema B：如 "约420万元"）
    description: str = ""         # 1.3 方案摘要
    dependencies: list = field(default_factory=list)      # ["FA-01","FA-03"]
    platforms: list = field(default_factory=list)         # ["adl","rop"]
    architecture_text: str = ""   # 二、技术架构设计 章节文本
    source_path: str = ""         # 原 .md 路径

    @property
    def family_display(self) -> str:
        return FAMILY_META.get(self.family, {}).get("display", self.family)

    @property
    def engine_class(self) -> str:
        return FAMILY_META.get(self.family, {}).get("engine_class", "MLEngine")

    @property
    def venv_name(self) -> str:
        return FAMILY_META.get(self.family, {}).get("venv", "ml")


def make_slug(module_id: str) -> str:
    """FA-02 → fa_02 （Python 合法标识符，可作包名）。"""
    return module_id.strip().lower().replace("-", "_")


def classify_family(tech_stack_raw: str, name: str = "") -> str:
    """按优先级匹配技术栈关键词（兼查模块名），返回家族 key。

    兼查模块名可修复 FA-05「区块链银行函证」这类技术栈字段未写"区块链"
    但名称点明家族的情况。
    """
    haystack = f"{tech_stack_raw} {name}"
    for family, keywords in FAMILY_RULES:
        if any(k in haystack for k in keywords):
            return family
    return "ml_nlp"


def split_tech_components(tech_stack_raw: str) -> list:
    """'BERT + XGBoost + NLP + 增量学习' → ['BERT','XGBoost','NLP','增量学习']。"""
    import re
    parts = re.split(r"[+、，,/\s]+", tech_stack_raw)
    return [p.strip() for p in parts if p.strip()]


def infer_platforms(tech_stack_raw: str) -> list:
    """由技术栈推断依赖的共享平台。默认 adl（数据湖是根基）。"""
    platforms = set()
    for keywords, plat in PLATFORM_RULES:
        if any(k in tech_stack_raw for k in keywords):
            platforms.add(plat)
    if not platforms:
        platforms.add("adl")
    return sorted(platforms)


def map_category(category_zh: str) -> str:
    """'财务报表审计（IPO审计、年度审计）' → 'financial_audit'。取首个匹配。"""
    for zh, en in CATEGORY_MAP.items():
        if zh in category_zh:
            return en
    return "other"


def map_priority(priority_raw: str) -> str:
    """'🔴 高' → 'high'。"""
    for emoji, val in PRIORITY_MAP.items():
        if emoji in priority_raw:
            return val
    return "medium"


def count_difficulty(difficulty_raw: str) -> int:
    """'⭐⭐⭐（中等）' → 3；schema B '6个月' → 按周期映射 1-5。"""
    stars = difficulty_raw.count("⭐")
    if stars:
        return stars
    import re
    m = re.search(r"(\d+)\s*个?\s*月", difficulty_raw)
    if m:
        months = int(m.group(1))
        if months <= 3:
            return 2
        if months <= 6:
            return 3
        if months <= 12:
            return 4
        return 5
    return 0
