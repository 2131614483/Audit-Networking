"""[CB-03] 多法域合规知识库核心引擎 —— 纯 stdlib 倒排索引 + 多语言检索。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 倒排索引（Inverted Index）构建：
      - 对法规条目标注关键词（中英双语 + 法域标签）
      - 构建 term → [法规ID, ...] 倒排列表
      - 支持关键词权重（核心要求 > 一般提及）
  * 多语言检索（query 可中英混合）：
      - 中文：子串匹配 + 关键词词典扩展同义词
      - 英文：词边界匹配 + lowercasing
      - 支持法域/分类/发布机构过滤
  * 法规相似度（difflib + Jaccard）：
      - Jaccard 相似度：关键词集合交集/并集
      - difflib.SequenceMatcher 用于法规摘要相似度
  * 合规问答（规则驱动）：
      - 将 query 解析为 {法域, 主题, 关键词列表}
      - 召回 Top-K 相关法规 → 提取核心要求 → 生成结构化回答
  * 法规比对（diff 两段法规）：
      - 条款级别 diff（difflib.unified_diff）
      - 识别新增/修改/删除条款

模型结构（self.model）：
  {
    "regulations": [{reg_id, title, title_en, body, jurisdiction, category, ...}],
    "inverted_index": {term: [reg_ids]},
    "reg_keywords": {reg_id: [keywords]},
    "synonyms_zh": {term: [synonyms]},
    "synonyms_en": {term: [synonyms]},
    "jurisdictions": {code: name},
  }
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 内置法规知识库种子数据（覆盖主要法域 + 核心合规领域）
# ------------------------------------------------------------------

_SEED_REGULATIONS: list[dict] = [
    {
        "reg_id": "GDPR-001",
        "title": "通用数据保护条例",
        "title_en": "General Data Protection Regulation",
        "jurisdiction": "EU",
        "jurisdiction_name": "欧盟",
        "category": "data_protection",
        "agency": "欧盟议会和理事会",
        "effective_date": "2018-05-25",
        "summary": "欧盟数据保护框架核心法规，规定数据处理的合法性、数据主体权利、数据跨境传输、处罚标准等。",
        "core_requirements": [
            "数据处理的六项合法性基础（同意/合同/法定义务/ vital interests/公共任务/合法利益）",
            "数据主体权利：访问/更正/删除/限制处理/可携性/反对",
            "数据最小化原则：仅处理必要数据",
            "目的限制原则：仅用于明确合法目的",
            "问责原则：控制者对合规负责",
            "跨境传输需满足充分性认定或适当保障措施",
        ],
        "penalty": "最高2000万欧元或全球年营收4%，取较高者",
        "keywords_zh": ["数据保护", "GDPR", "个人信息", "数据跨境", "数据主体权利", "隐私", "合规"],
        "keywords_en": ["data protection", "GDPR", "personal data", "cross-border transfer", "data subject", "privacy", "consent"],
    },
    {
        "reg_id": "PIPL-001",
        "title": "中华人民共和国个人信息保护法",
        "title_en": "Personal Information Protection Law",
        "jurisdiction": "CN",
        "jurisdiction_name": "中国",
        "category": "data_protection",
        "agency": "全国人民代表大会常务委员会",
        "effective_date": "2021-11-01",
        "summary": "中国个人信息保护的基础性法律，规定个人信息处理规则、个人权利、跨境提供、法律责任。",
        "core_requirements": [
            "合法、正当、必要原则",
            "目的明确原则",
            "直接同意或法定例外处理个人信息",
            "告知同意：处理前告知处理目的、方式、范围",
            "敏感个人信息需取得单独同意",
            "跨境提供需通过安全评估或认证",
        ],
        "penalty": "最高5000万元或上一年度营业额5%，取较高者",
        "keywords_zh": ["个人信息", "数据保护", "个人信息保护法", "敏感信息", "数据出境", "同意"],
        "keywords_en": ["personal information", "data protection", "PIPL", "sensitive data", "cross-border transfer"],
    },
    {
        "reg_id": "CSL-001",
        "title": "中华人民共和国数据安全法",
        "title_en": "Data Security Law",
        "jurisdiction": "CN",
        "jurisdiction_name": "中国",
        "category": "data_security",
        "agency": "全国人民代表大会常务委员会",
        "effective_date": "2021-09-01",
        "summary": "中国数据安全治理的基础性法律，规定数据分类分级、安全审查、重要数据出境管制。",
        "core_requirements": [
            "数据分类分级：一般/重要/核心数据",
            "重要数据出境安全评估",
            "关键信息基础设施运营者需开展数据安全评估",
            "建立数据安全保护义务和责任",
        ],
        "penalty": "最高500万元罚款",
        "keywords_zh": ["数据安全", "数据分类", "数据分级", "安全评估", "重要数据", "关键信息基础设施"],
        "keywords_en": ["data security", "data classification", "security assessment", "important data"],
    },
    {
        "reg_id": "CCPA-001",
        "title": "加州消费者隐私法案",
        "title_en": "California Consumer Privacy Act",
        "jurisdiction": "US",
        "jurisdiction_name": "美国",
        "category": "data_protection",
        "agency": "加州州议会",
        "effective_date": "2020-01-01",
        "summary": "美国加州消费者隐私保护法案，规定消费者对个人信息的访问/删除/销售权。",
        "core_requirements": [
            "消费者知情权：收集什么信息、用于什么目的",
            "访问权：请求获取个人信息副本",
            "删除权：请求删除个人信息",
            "选择退出权：拒绝个人信息出售",
        ],
        "penalty": "每项违规最高7500美元",
        "keywords_zh": ["数据隐私", "个人信息", "消费者权利", "信息删除", "信息访问"],
        "keywords_en": ["CCPA", "privacy", "consumer rights", "right to know", "right to delete", "opt out"],
    },
    {
        "reg_id": "AMLD5-001",
        "title": "欧盟第五版反洗钱指令",
        "title_en": "5th Anti-Money Laundering Directive",
        "jurisdiction": "EU",
        "jurisdiction_name": "欧盟",
        "category": "aml",
        "agency": "欧盟议会和理事会",
        "effective_date": "2020-01-10",
        "summary": "欧盟反洗钱最新指令，加强虚拟资产监管、扩大受益人透明度、增强跨境合作。",
        "core_requirements": [
            "虚拟资产服务提供商纳入监管",
            "受益人所有权透明度登记",
            "高风险国家强化尽职调查",
            "加强金融情报单位合作",
        ],
        "penalty": "各成员国规定，通常按违规金额比例",
        "keywords_zh": ["反洗钱", "AML", "KYC", "虚拟资产", "受益所有人", "尽职调查"],
        "keywords_en": ["AML", "money laundering", "KYC", "beneficial owner", "virtual assets", "due diligence"],
    },
    {
        "reg_id": "IFRS-15",
        "title": "国际财务报告准则第15号 —— 客户合同收入",
        "title_en": "IFRS 15 Revenue from Contracts with Customers",
        "jurisdiction": "GLOBAL",
        "jurisdiction_name": "国际准则",
        "category": "accounting",
        "agency": "国际会计准则理事会",
        "effective_date": "2018-01-01",
        "summary": "全球统一的收入确认五步法模型，替代原IFRS 11和IFRS 18。",
        "core_requirements": [
            "五步法：识别合同→识别履约义务→确定交易价格→分摊交易价格→履行时确认收入",
            "合同合并与修改处理",
            "履约进度计量方法",
            "合同成本资本化",
        ],
        "penalty": "无直接处罚，但影响财务报告真实性",
        "keywords_zh": ["收入确认", "IFRS", "财务报告", "会计", "履约义务", "合同"],
        "keywords_en": ["IFRS 15", "revenue recognition", "financial reporting", "performance obligation", "contract"],
    },
]

# 同义词扩展（检索时自动扩展 query 关键词）
_SYNONYMS_ZH: dict[str, list[str]] = {
    "数据保护": ["个人信息保护", "隐私保护"],
    "数据跨境": ["跨境传输", "数据出境", "跨境提供"],
    "同意": ["授权", "许可"],
    "安全评估": ["出境评估", "风险评估"],
    "反洗钱": ["AML", "洗钱", "可疑交易"],
    "会计": ["会计准则", "财务报告", "审计"],
    "收入确认": ["营收", "营业额", "收入"],
}

_SYNONYMS_EN: dict[str, list[str]] = {
    "data protection": ["privacy", "personal data protection"],
    "cross-border": ["cross border", "international transfer", "data export"],
    "consent": ["authorization", "permission"],
    "assessment": ["evaluation", "review"],
    "aml": ["anti-money laundering", "money laundering"],
    "accounting": ["financial reporting", "GAAP", "accounting standards"],
}


def _tokenize_zh(text: str) -> list[str]:
    """中文粗粒度切分：2-gram + 字边界（无需 jieba）。"""
    if not text:
        return []
    text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", text).strip()
    tokens: list[str] = []
    # 中文 2-gram
    for i in range(len(text) - 1):
        if "\u4e00" <= text[i] <= "\u9fff" and "\u4e00" <= text[i + 1] <= "\u9fff":
            tokens.append(text[i:i + 2])
    # 英文/数字词
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9\-]{1,}", text):
        tokens.append(m.group(0).lower())
    return tokens


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class LLMEngine(AbstractEngine):
    """多法域合规知识库引擎（纯 stdlib 倒排索引 + 多语言检索 + 规则问答）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改。
    """

    # ------------------------------------------------------------------
    # 模型加载：构建倒排索引
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载内置法规知识库 + 构建倒排索引。"""
        regulations = list(_SEED_REGULATIONS)

        inverted_index: dict[str, list[str]] = defaultdict(list)
        reg_keywords: dict[str, set[str]] = {}

        for reg in regulations:
            rid = reg["reg_id"]
            kw_set: set[str] = set()
            for kw in reg.get("keywords_zh", []):
                inverted_index[kw].append(rid)
                kw_set.add(kw)
            for kw in reg.get("keywords_en", []):
                inverted_index[kw.lower()].append(rid)
                kw_set.add(kw.lower())
            # 摘要和要求也入索引（中文子串 + 英文词）
            body = reg.get("summary", "") + " " + " ".join(reg.get("core_requirements", []))
            for tok in _tokenize_zh(body):
                if tok not in kw_set:
                    inverted_index[tok].append(rid)
                    kw_set.add(tok)
            reg_keywords[rid] = kw_set

        # 去重
        for k in inverted_index:
            inverted_index[k] = list(dict.fromkeys(inverted_index[k]))

        jurisdictions: dict[str, str] = {}
        for reg in regulations:
            jurisdictions[reg["jurisdiction"]] = reg.get("jurisdiction_name", reg["jurisdiction"])

        self.model = {
            "regulations": regulations,
            "inverted_index": dict(inverted_index),
            "reg_keywords": reg_keywords,
            "synonyms_zh": dict(_SYNONYMS_ZH),
            "synonyms_en": dict(_SYNONYMS_EN),
            "jurisdictions": jurisdictions,
            "categories": sorted({r["category"] for r in regulations}),
        }

    # ------------------------------------------------------------------
    # 预处理：解析查询意图
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化查询输入。

        input_data 格式:
          {
            "query": "GDPR数据跨境传输要求",
            "action": "search" | "qa" | "compare",
            "jurisdiction": "EU",           # 可选过滤
            "category": "data_protection",  # 可选过滤
            "compare_with": "PIPL-001",     # compare 模式
            "top_k": 5,
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"query": input_data}
        elif not isinstance(input_data, dict):
            input_data = {"query": str(input_data)}

        query = str(input_data.get("query", "")).strip()
        action = input_data.get("action", "search")

        # 扩展查询关键词（同义词）
        query_terms: set[str] = set()
        for tok in _tokenize_zh(query):
            query_terms.add(tok)
            # 查同义词
            for syn in self.model["synonyms_zh"].get(tok, []):
                query_terms.add(syn)
            for syn in self.model["synonyms_en"].get(tok, []):
                query_terms.add(syn)

        # 英文词边界补充
        for m in re.finditer(r"[A-Za-z][A-Za-z0-9\-]{1,}", query):
            lw = m.group(0).lower()
            query_terms.add(lw)
            for syn in self.model["synonyms_en"].get(lw, []):
                query_terms.add(syn)

        return {
            "raw_query": query,
            "query_terms": query_terms,
            "action": action,
            "jurisdiction": (input_data.get("jurisdiction") or "").upper(),
            "category": input_data.get("category") or "",
            "top_k": int(input_data.get("top_k", 5)),
            "compare_with": input_data.get("compare_with"),
        }

    # ------------------------------------------------------------------
    # 推理：检索 / 问答 / 比对
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """根据 action 路由到不同推理逻辑。"""
        action = prepared["action"]
        if action == "compare":
            return self._compare_regulations(prepared)
        if action == "qa":
            return self._qa_answer(prepared)
        return self._search(prepared)

    # ------------------------------------------------------------------
    # 后处理：统一格式化输出
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """添加统计信息 + 时间戳。"""
        if "module" in result:
            return result

        regulations = result.get("regulations", [])
        by_jurisdiction = Counter()
        by_category = Counter()
        for r in regulations:
            by_jurisdiction[r.get("jurisdiction", "UNKNOWN")] += 1
            by_category[r.get("category", "unknown")] += 1

        result["summary"] = {
            "module": "CB-03",
            "family": "llm_rag",
            "total_results": len(regulations),
            "by_jurisdiction": dict(by_jurisdiction),
            "by_category": dict(by_category),
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 内部：检索（倒排索引 + Jaccard 重排序）
    # ------------------------------------------------------------------
    def _search(self, prepared: Any) -> dict:
        terms = prepared["query_terms"]
        inverted = self.model["inverted_index"]
        reg_keywords = self.model["reg_keywords"]
        all_regs = self.model["regulations"]

        # 收集候选
        candidate_ids: dict[str, int] = Counter()
        for term in terms:
            for rid in inverted.get(term, []):
                candidate_ids[rid] += 1

        if not candidate_ids:
            return {"regulations": [], "query": prepared["raw_query"], "note": "未找到匹配法规"}

        # 过滤 + 打分
        results: list[dict] = []
        for reg in all_regs:
            rid = reg["reg_id"]
            if rid not in candidate_ids:
                continue
            if prepared["jurisdiction"] and reg["jurisdiction"] != prepared["jurisdiction"]:
                continue
            if prepared["category"] and reg["category"] != prepared["category"]:
                continue

            # 评分：倒排匹配计数 + Jaccard 相似度 + 术语词典命中
            jacc = _jaccard(terms, reg_keywords.get(rid, set()))
            score = candidate_ids[rid] * 2 + jacc
            # 摘要相似度（SequenceMatcher）
            summary_sim = difflib.SequenceMatcher(
                None, prepared["raw_query"].lower(),
                (reg.get("summary") + " " + reg.get("title")).lower()
            ).ratio()
            score += summary_sim * 3

            results.append({
                **reg,
                "score": round(score, 4),
                "match_count": candidate_ids[rid],
                "jaccard": round(jacc, 4),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        top = results[:prepared["top_k"]]
        return {"regulations": top, "query": prepared["raw_query"]}

    # ------------------------------------------------------------------
    # 内部：合规问答（基于检索结果生成结构化回答）
    # ------------------------------------------------------------------
    def _qa_answer(self, prepared: Any) -> dict:
        search_result = self._search({**prepared, "action": "search", "top_k": 3})
        regs = search_result["regulations"]

        if not regs:
            return {
                "answer": "未找到相关法规。建议检查关键词或扩大法域范围。",
                "sources": [],
                "confidence": 0.0,
                "query": prepared["raw_query"],
            }

        # 汇总回答
        parts: list[str] = []
        all_requirements: list[dict] = []
        for reg in regs:
            parts.append(f"【{reg['jurisdiction_name']}】{reg['title']}（{reg['reg_id']}，{reg['effective_date']}生效）")
            parts.append(f"  摘要：{reg['summary']}")
            for req in reg.get("core_requirements", []):
                all_requirements.append({"reg_id": reg["reg_id"], "requirement": req})
                parts.append(f"  • {req}")
            if reg.get("penalty"):
                parts.append(f"  处罚：{reg['penalty']}")

        sources = [
            {"reg_id": r["reg_id"], "title": r["title"], "score": r["score"]}
            for r in regs
        ]
        confidence = max((r["score"] / 10 for r in regs), default=0.0)

        return {
            "answer": "\n".join(parts),
            "structured_requirements": all_requirements,
            "sources": sources,
            "confidence": round(min(confidence, 1.0), 4),
            "query": prepared["raw_query"],
        }

    # ------------------------------------------------------------------
    # 内部：法规比对（diff 条款级差异）
    # ------------------------------------------------------------------
    def _compare_regulations(self, prepared: Any) -> dict:
        regs_by_id = {r["reg_id"]: r for r in self.model["regulations"]}

        reg_a_id = prepared.get("compare_with") or (
            prepared["query_terms"] & set(regs_by_id.keys())
        )
        reg_b_id = None

        # 尝试从 query 中提取两个法规 ID
        terms_list = list(prepared["query_terms"])
        if isinstance(reg_a_id, set):
            reg_a_id = next(iter(reg_a_id), None)

        # 如果没有指定，取前两个检索结果
        if not reg_a_id:
            search = self._search({**prepared, "action": "search", "top_k": 2})
            if len(search["regulations"]) >= 2:
                reg_a_id = search["regulations"][0]["reg_id"]
                reg_b_id = search["regulations"][1]["reg_id"]

        if not reg_a_id or reg_a_id not in regs_by_id:
            return {"comparison": "未找到两个法规进行比对", "query": prepared["raw_query"]}

        if not reg_b_id:
            # 取另一个法域同分类法规
            reg_a = regs_by_id[reg_a_id]
            for r in self.model["regulations"]:
                if r["reg_id"] != reg_a_id and r["category"] == reg_a["category"]:
                    reg_b_id = r["reg_id"]
                    break

        if not reg_b_id or reg_b_id not in regs_by_id:
            return {"comparison": f"仅找到一个法规 {reg_a_id}，缺少第二个进行比对", "query": prepared["raw_query"]}

        reg_a = regs_by_id[reg_a_id]
        reg_b = regs_by_id[reg_b_id]

        # 关键词集合相似度
        ka = self.model["reg_keywords"].get(reg_a_id, set())
        kb = self.model["reg_keywords"].get(reg_b_id, set())
        common_kw = sorted(ka & kb)
        only_a = sorted(ka - kb)[:10]
        only_b = sorted(kb - ka)[:10]
        jacc = _jaccard(ka, kb)

        # 核心要求 diff
        req_a = reg_a.get("core_requirements", [])
        req_b = reg_b.get("core_requirements", [])
        diff_lines = list(difflib.unified_diff(
            req_a, req_b,
            fromfile=f"{reg_a_id} ({reg_a['title']})",
            tofile=f"{reg_b_id} ({reg_b['title']})",
            lineterm="",
        ))

        return {
            "regulation_a": {
                "reg_id": reg_a_id, "title": reg_a["title"],
                "jurisdiction": reg_a["jurisdiction_name"],
                "effective_date": reg_a["effective_date"],
            },
            "regulation_b": {
                "reg_id": reg_b_id, "title": reg_b["title"],
                "jurisdiction": reg_b["jurisdiction_name"],
                "effective_date": reg_b["effective_date"],
            },
            "keyword_similarity": round(jacc, 4),
            "common_keywords": common_kw,
            "unique_to_a": only_a,
            "unique_to_b": only_b,
            "requirement_diff": diff_lines,
            "comparison_summary": (
                f"{reg_a['title']}（{reg_a['jurisdiction_name']}）与"
                f"{reg_b['title']}（{reg_b['jurisdiction_name']}）关键词相似度 {round(jacc * 100, 1)}%。"
                f"共有关键词 {len(common_kw)} 个，{reg_a_id} 独有 {len(only_a)} 个，{reg_b_id} 独有 {len(only_b)} 个。"
            ),
        }
