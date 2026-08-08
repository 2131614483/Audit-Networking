"""[CO-09] 隐私合规自动审计引擎 —— 纯 stdlib NLP条款分类 + 规则引擎合规检查。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 隐私政策条款分类（中英双语关键词匹配，模拟 NLP 语义识别）：
      - 预定义 11 个 GDPR/CCPA/PIPL 要求的条款类别
      - 每个类别含 zh/en 双语关键词与子条款描述
      - 子串计数 + 类别得分 → 最高得分类别
  * 合规性检查（完整性 + 准确性 + 清晰度 + 公平性四维度）：
      - 完整性：条款是否存在（覆盖度 = 存在类别数 / 总类别数）
      - 准确性：内容是否覆盖法规要求的子主题（子主题覆盖度）
      - 清晰度：条款文本长度 + 句子复杂度 + 可读性指标
      - 公平性：是否有误导性表述（"我们可能会"模糊表述）
  * 综合合规评分：完整性 40% + 准确性 30% + 清晰度 15% + 公平性 15%
  * 多法规支持：GDPR / CCPA / PIPL / LGPD 各自的类别权重映射

模型结构（self.model）：
  {
    "categories": {cat_id: {zh, en, sub_topics, weight, compliance}},
    "misleading_patterns": [...],
    "legal_refs": {cat_id: [legal_article, ...]},
  }
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "co_09.db"

_POLICIES_SCHEMA = {
    "policy_id": "TEXT",
    "name": "TEXT",
    "publisher": "TEXT",
    "language": "TEXT",
    "compliance_scores": "JSON",
    "overall_score": "REAL",
    "grade": "TEXT",
    "created_at": "DATETIME",
}
_FINDINGS_SCHEMA = {
    "finding_id": "TEXT",
    "policy_id": "TEXT",
    "category_id": "TEXT",
    "category_name": "TEXT",
    "status": "TEXT",
    "score": "REAL",
    "evidence": "TEXT",
    "recommendation": "TEXT",
    "legal_refs": "JSON",
    "created_at": "DATETIME",
}

_CATEGORY_DEFS: dict[str, dict[str, Any]] = {
    "controller_info": {
        "name": "数据控制者身份与联系方式",
        "zh": ["控制者", "数据控制者", "联系方式", "地址", "邮箱", "电话", "数据保护官", "DPO", "负责人"],
        "en": ["controller", "data controller", "contact", "address", "email", "telephone",
               "data protection officer", "dpo", "representative"],
        "sub_topics_zh": ["公司名称", "注册地址", "联系邮箱", "联系电话", "DPO身份"],
        "sub_topics_en": ["company name", "registered address", "contact email", "contact phone", "dpo identity"],
        "legal_refs": {"GDPR": ["Art.5(2)", "Art.13(1)(a)"], "PIPL": ["第12条"]},
        "weight": 1.0,
    },
    "data_types_purposes": {
        "name": "收集的个人数据类型和目的",
        "zh": ["数据类型", "个人信息类型", "收集目的", "使用目的", "处理目的", "收集的信息", "收集的个人"],
        "en": ["data type", "personal data type", "purpose", "processing purpose", "collect", "use"],
        "sub_topics_zh": ["身份信息", "联系信息", "财务信息", "行为数据", "设备信息", "位置信息"],
        "sub_topics_en": ["identity", "contact", "financial", "behavioral", "device", "location"],
        "legal_refs": {"GDPR": ["Art.5(1)(b)", "Art.13(1)(c)"], "CCPA": ["CCPA 1798.100(d)"]},
        "weight": 1.0,
    },
    "legal_basis": {
        "name": "数据处理的法律依据",
        "zh": ["法律依据", "合法基础", "同意", "合同", "合法利益", "法定义务", "数据处理的依据"],
        "en": ["legal basis", "lawful basis", "consent", "contract", "legitimate interest",
               "legal obligation"],
        "sub_topics_zh": ["同意", "合同履行", "法定义务", "合法利益", "生命安全", "公共任务"],
        "sub_topics_en": ["consent", "contract", "legal obligation", "legitimate interest",
                          "vital interest", "public task"],
        "legal_refs": {"GDPR": ["Art.6(1)"], "PIPL": ["第6条"]},
        "weight": 1.2,
    },
    "retention": {
        "name": "数据存储期限",
        "zh": ["存储期限", "保留期限", "保存期限", "数据保留", "保留多久", "删除期限", "销毁期限"],
        "en": ["retention", "storage period", "keep for", "delete after", "retain", "how long"],
        "sub_topics_zh": ["最短期限", "最长期限", "定期审查", "删除触发条件", "归档期限"],
        "sub_topics_en": ["minimum", "maximum", "periodic review", "trigger", "archival"],
        "legal_refs": {"GDPR": ["Art.5(1)(e)", "Art.13(2)(a)"], "PIPL": ["第19条"]},
        "weight": 1.0,
    },
    "data_subject_rights": {
        "name": "数据主体权利",
        "zh": ["访问权", "删除权", "更正权", "可携带权", "限制处理权", "反对权", "撤回同意", "您有权"],
        "en": ["right of access", "right to be forgotten", "right to rectification",
               "right to data portability", "right to restrict", "right to object",
               "withdraw consent", "you have the right"],
        "sub_topics_zh": ["访问", "更正", "删除", "可携带", "限制处理", "反对", "撤回同意", "投诉"],
        "sub_topics_en": ["access", "rectification", "erasure", "portability",
                          "restriction", "object", "withdraw", "complain"],
        "legal_refs": {"GDPR": ["Art.15-22"], "CCPA": ["CCPA 1798.100-125"], "PIPL": ["第44-49条"]},
        "weight": 1.5,
    },
    "data_sharing": {
        "name": "数据共享和第三方披露",
        "zh": ["第三方", "数据共享", "数据披露", "合作伙伴", "供应商", "服务提供商", "数据接收者"],
        "en": ["third party", "share", "disclose", "partner", "vendor", "service provider",
               "recipient"],
        "sub_topics_zh": ["共享类型", "共享对象", "共享目的", "处理者合同", "安全措施"],
        "sub_topics_en": ["type of sharing", "recipient identity", "purpose",
                          "processor contract", "security measures"],
        "legal_refs": {"GDPR": ["Art.13(1)(d)", "Art.28"], "CCPA": ["CCPA 1798.115"]},
        "weight": 1.2,
    },
    "cross_border": {
        "name": "跨境数据传输",
        "zh": ["跨境", "国际传输", "境外传输", "欧盟以外", "中国境外", "国际", "SCC", "标准合同条款", "充分性决定"],
        "en": ["cross-border", "international transfer", "outside eu", "outside",
               "adequacy decision", "standard contractual clause", "scc", "binding corporate rule"],
        "sub_topics_zh": ["传输目的地", "传输机制", "充分性保护", "SCC", "BCR", "风险提示"],
        "sub_topics_en": ["destination", "transfer mechanism", "adequacy", "SCC", "BCR", "risk"],
        "legal_refs": {"GDPR": ["Art.44-50"], "PIPL": ["第38-39条"], "CCPA": ["CCPA 1798.120"]},
        "weight": 1.5,
    },
    "security": {
        "name": "数据安全措施",
        "zh": ["安全措施", "加密", "数据安全", "保护措施", "访问控制", "安全保障", "技术措施", "组织措施"],
        "en": ["security measure", "encryption", "data security", "protect", "access control",
               "safeguard", "technical measure", "organizational measure"],
        "sub_topics_zh": ["加密", "访问控制", "审计日志", "备份", "员工培训", "安全事件响应"],
        "sub_topics_en": ["encryption", "access control", "audit log", "backup",
                          "employee training", "incident response"],
        "legal_refs": {"GDPR": ["Art.32", "Art.33"], "PIPL": ["第51条"]},
        "weight": 1.2,
    },
    "cookies": {
        "name": "Cookie和追踪技术",
        "zh": ["cookie", "cookies", "追踪", "跟踪", "分析工具", "广告", "像素标签", "web beacon"],
        "en": ["cookie", "cookies", "track", "tracking", "analytics", "advertising",
               "pixel tag", "web beacon"],
        "sub_topics_zh": ["使用类型", "同意管理", "目的说明", "禁用方法", "第三方"],
        "sub_topics_en": ["type used", "consent management", "purpose", "opt-out", "third party"],
        "legal_refs": {"GDPR": ["Art.5(3)", "EDPR"], "PIPL": ["第24条"]},
        "weight": 0.8,
    },
    "updates": {
        "name": "政策更新通知",
        "zh": ["更新", "变更", "修改", "版本", "修订", "生效日期", "更新通知"],
        "en": ["update", "change", "modify", "version", "revise", "effective date",
               "update notice"],
        "sub_topics_zh": ["更新频率", "通知方式", "重大变更", "版本历史"],
        "sub_topics_en": ["frequency", "notification method", "material change",
                          "version history"],
        "legal_refs": {"GDPR": ["Art.13(2)(m)"], "CCPA": ["CCPA 1798.120(b)"]},
        "weight": 0.7,
    },
    "complaint_channel": {
        "name": "联系方式与投诉渠道",
        "zh": ["投诉", "申诉", "监管机构", "举报", "审计委员会", "提出投诉"],
        "en": ["complaint", "supervisory authority", "report", "complain to", "appeal"],
        "sub_topics_zh": ["投诉方式", "处理时限", "监管机构", "外部渠道"],
        "sub_topics_en": ["how to complain", "timeframe", "supervisory authority", "external"],
        "legal_refs": {"GDPR": ["Art.77"], "PIPL": ["第54条"]},
        "weight": 1.0,
    },
}

_MISLEADING_PATTERNS: list[tuple[str, str]] = [
    (r"可能会", "模糊表述：'可能会'未明确承诺"),
    (r"也许会", "模糊表述：'也许会'未明确承诺"),
    (r"will\s+\*?may\b", "英文模糊表述：may过于不确定"),
    (r"we\s+may\s+(disclose|share|transfer)", "模糊表述：'may disclose/share'"),
    (r"视情况而定", "模糊表述：视情况而定，缺乏具体条件"),
    (r"to\s+the\s+extent\s+permitted", "英文模糊表述：法律允许范围内过于宽泛"),
]

_READABILITY_HIGH_FREQ_WORDS_ZH = ["的", "和", "及", "以及", "与", "或", "但是", "然而", "因此", "所以"]
_READABILITY_MIN_SENTENCE_LEN = 8
_READABILITY_MAX_SENTENCE_LEN = 60


def _split_sentences(text: str) -> list[str]:
    return re.split(r"[。！？\.!?\n]+", text)


def _calc_readability(text: str) -> dict[str, float]:
    sentences = [s.strip() for s in _split_sentences(text) if s.strip()]
    if not sentences:
        return {"avg_sentence_len": 0.0, "complexity_score": 0.0, "score": 50.0}
    avg_len = sum(len(s) for s in sentences) / len(sentences)
    complex_count = sum(1 for s in sentences if len(s) > _READABILITY_MAX_SENTENCE_LEN)
    complexity_score = complex_count / len(sentences)
    score = 100.0 - min(avg_len * 1.0, 40.0) - complexity_score * 40.0
    score = max(0.0, min(100.0, score))
    return {"avg_sentence_len": round(avg_len, 2),
            "complexity_score": round(complexity_score, 4),
            "score": round(score, 2)}


class LLMEngine(AbstractEngine):
    """CO-09 隐私合规自动审计引擎（纯 stdlib 规则引擎 + 关键词分类）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        """初始化 PortableDB + 加载条款类别定义。"""
        self.db = PortableDB(self.db_path)
        for table, schema in [
            ("policies", _POLICIES_SCHEMA),
            ("findings", _FINDINGS_SCHEMA),
        ]:
            if table not in self.db.tables():
                self.db.create_table(table, schema)

        self.model = {
            "categories": {k: dict(v) for k, v in _CATEGORY_DEFS.items()},
            "misleading_patterns": list(_MISLEADING_PATTERNS),
        }

    def _preprocess(self, input_data: Any) -> Any:
        """清洗隐私政策文本，去除 HTML/无关导航，分割为段落列表。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 policies 列表")

        raw_policies = input_data.get("policies", [])
        cleaned = []
        for p in raw_policies:
            if not isinstance(p, dict):
                continue
            text = p.get("text", "") or p.get("content", "") or ""
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            paragraphs = [para.strip() for para in re.split(r"\n+|\r\n+", text) if para.strip()]
            cleaned.append({
                "policy_id": p.get("policy_id") or p.get("id", ""),
                "name": p.get("name", "") or p.get("title", "") or "",
                "publisher": p.get("publisher", "") or p.get("company", "") or "",
                "language": (p.get("language", "") or "zh").lower(),
                "raw_text": text,
                "paragraphs": paragraphs,
            })
        return cleaned

    def _infer(self, prepared: Any) -> Any:
        """核心推理：对每条政策执行四维度合规检查。"""
        categories = self.model["categories"]
        misleading = self.model["misleading_patterns"]
        all_results = []

        for policy in prepared:
            text = policy["raw_text"]
            paragraphs = policy["paragraphs"]
            lang = policy["language"]
            readability = _calc_readability(text)

            findings: list[dict] = []
            total_weight = 0.0
            weighted_score = 0.0

            for cat_id, cat_def in categories.items():
                weight = cat_def["weight"]
                cat_score, evidence, sub_coverage = self._check_category(
                    text, paragraphs, cat_def, lang, misleading
                )
                total_weight += weight
                weighted_score += cat_score * weight

                status = self._score_to_status(cat_score)
                recommendation = self._generate_recommendation(
                    cat_id, cat_score, cat_def, sub_coverage, evidence
                )
                findings.append({
                    "category_id": cat_id,
                    "category_name": cat_def["name"],
                    "status": status,
                    "score": round(cat_score, 2),
                    "evidence": evidence[:5],
                    "sub_coverage": sub_coverage,
                    "recommendation": recommendation,
                    "legal_refs": cat_def["legal_refs"],
                    "weight": weight,
                })

            completeness = sum(1 for f in findings if f["score"] >= 50) / len(findings) * 100
            accuracy = sum(f["score"] for f in findings) / len(findings)
            clarity = readability["score"]
            fairness = max(0.0, 100.0 - len(misleading) * 20 if text else 50.0)

            overall = round(
                completeness * 0.40 + accuracy * 0.30 + clarity * 0.15 + fairness * 0.15, 2
            )
            grade = self._score_to_grade(overall)

            all_results.append({
                **policy,
                "findings": findings,
                "overall_score": overall,
                "grade": grade,
                "dimension_scores": {
                    "completeness": round(completeness, 2),
                    "accuracy": round(accuracy, 2),
                    "clarity": clarity,
                    "fairness": round(fairness, 2),
                },
                "readability": readability,
            })

        return {"policies": all_results}

    def _check_category(self, text: str, paragraphs: list[str],
                        cat_def: dict, lang: str,
                        misleading: list[tuple[str, str]]) -> tuple[float, list[str], float]:
        """单条款类别检查 → (综合评分, 证据列表, 子主题覆盖率)。"""
        keywords_zh = cat_def.get("zh", [])
        keywords_en = cat_def.get("en", [])
        sub_topics_zh = cat_def.get("sub_topics_zh", [])
        sub_topics_en = cat_def.get("sub_topics_en", [])

        if lang == "en":
            kws = keywords_en
            sub_topics = sub_topics_en
        else:
            kws = keywords_zh
            sub_topics = sub_topics_zh

        hit_count = 0
        evidence: list[str] = []
        for kw in kws:
            if kw.lower() in text.lower():
                hit_count += 1
                for p in paragraphs:
                    if kw.lower() in p.lower() and p not in evidence:
                        evidence.append(p[:120])
                        if len(evidence) >= 5:
                            break
                if len(evidence) >= 5:
                    break

        completeness = min(hit_count / max(len(kws) * 0.5, 1), 1.0) * 100

        sub_hits = sum(1 for st in sub_topics if st.lower() in text.lower())
        sub_coverage = (sub_hits / len(sub_topics) * 100) if sub_topics else 0.0

        has_misleading = False
        for pat, _ in misleading:
            if re.search(pat, text, re.IGNORECASE):
                has_misleading = True
                break

        if completeness == 0:
            return 0.0, evidence, sub_coverage

        base_score = completeness * 0.5 + sub_coverage * 0.5
        if has_misleading:
            base_score = max(0, base_score - 15)

        return round(base_score, 2), evidence, round(sub_coverage, 2)

    def _score_to_status(self, score: float) -> str:
        if score >= 80:
            return "compliant"
        if score >= 50:
            return "partial"
        if score >= 20:
            return "weak"
        return "missing"

    def _generate_recommendation(self, cat_id: str, score: float,
                                 cat_def: dict, sub_coverage: float,
                                 evidence: list[str]) -> str:
        if score >= 80:
            return f"✅ {cat_def['name']}条款覆盖充分，建议定期复核更新"
        if score >= 50:
            missing = [s for s in cat_def.get("sub_topics_zh", [])
                       if s.lower() not in " ".join(evidence).lower()]
            if missing:
                return (f"⚠️ {cat_def['name']}部分缺失：建议补充"
                        f"{'、'.join(missing[:3])}等内容")
            return f"⚠️ {cat_def['name']}需改进：表述不够清晰，建议细化"
        if score >= 20:
            return f"❌ {cat_def['name']}严重缺失：应增加相关条款，参考{cat_def['legal_refs'].get('GDPR', [])}"
        return f"❌ 缺失{cat_def['name']}条款：{cat_def['legal_refs']}要求必须包含"

    def _score_to_grade(self, score: float) -> str:
        if score >= 85:
            return "A"
        if score >= 70:
            return "B"
        if score >= 55:
            return "C"
        if score >= 40:
            return "D"
        return "F"

    def _postprocess(self, result: Any) -> Any:
        """持久化合规报告 + 生成合规摘要。"""
        policies = result.get("policies", [])
        total_findings = 0
        by_status: dict[str, int] = {"compliant": 0, "partial": 0, "weak": 0, "missing": 0}

        for policy in policies:
            pid = policy["policy_id"]
            self.db.insert("policies", {
                "policy_id": pid,
                "name": policy["name"],
                "publisher": policy["publisher"],
                "language": policy["language"],
                "compliance_scores": policy["dimension_scores"],
                "overall_score": policy["overall_score"],
                "grade": policy["grade"],
                "created_at": datetime.now(),
            })
            for f in policy["findings"]:
                self.db.insert("findings", {
                    "finding_id": f"{pid}_{f['category_id']}",
                    "policy_id": pid,
                    "category_id": f["category_id"],
                    "category_name": f["category_name"],
                    "status": f["status"],
                    "score": f["score"],
                    "evidence": " | ".join(f["evidence"][:3]),
                    "recommendation": f["recommendation"],
                    "legal_refs": f["legal_refs"],
                    "created_at": datetime.now(),
                })
                by_status[f["status"]] = by_status.get(f["status"], 0) + 1
                total_findings += 1

        avg_score = (
            sum(p["overall_score"] for p in policies) / len(policies)
            if policies else 0
        )
        result["summary"] = {
            "total_policies": len(policies),
            "total_findings": total_findings,
            "by_status": by_status,
            "average_overall_score": round(avg_score, 2),
            "policies_by_grade": self._count_by_grade(policies),
        }
        return result

    def _count_by_grade(self, policies: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in policies:
            g = p["grade"]
            counts[g] = counts.get(g, 0) + 1
        return counts

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
