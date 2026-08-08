"""[CB-04] AI多准则自动转换引擎 —— 纯 stdlib 准则差异匹配 + 调节表生成。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 准则差异知识库：
      - 内置 IFRS ↔ US GAAP ↔ China GAAP 三大体系的核心差异点
      - 每个差异点含 {会计领域, IFRS处理, GAAP处理, 差异类型, 计量公式, 披露要求}
  * 准则识别（关键词 + 准则特征匹配）：
      - 从财务报表/附注中识别使用的准则体系
      - 依据：准则引用（如 "IFRS 15"/"ASC 606"）+ 会计政策描述关键词
  * 差异匹配（语义相似度 + 关键词权重）：
      - 将报表中的会计政策描述与准则差异库匹配
      - difflib.SequenceMatcher 计算语义相似度
      - 提取需要调整的科目和金额
  * 调节表生成：
      - 按资产负债表/利润表/现金流量表分类
      - 自动汇总各项差异的影响金额
      - 生成结构化调节分录（借/贷方向 + 金额）
  * 转换报告：
      - 差异清单（按影响金额排序）
      - 调节后关键财务指标对比
      - 重要性评估 + 审计提示

模型结构（self.model）：
  {
    "standards": {"IFRS": {...}, "US_GAAP": {...}, "CN_GAAP": {...}},
    "differences": [{领域, IFRS处理, GAAP处理, 差异类型, 关键词, ...}],
    "accounts": {"科目编码": {"name": ..., "category": ...}},
    "key_ratios": [财务指标定义],
  }
"""
from __future__ import annotations

import difflib
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 三大准则体系标识 + 核心关键词
# ------------------------------------------------------------------

_STANDARD_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "IFRS": {
        "zh": ["国际财务报告准则", "IFRS", "国际会计准则", "IAS", "国际准则"],
        "en": ["IFRS", "International Financial Reporting Standards", "IAS", "International Accounting Standard"],
    },
    "US_GAAP": {
        "zh": ["美国公认会计原则", "US GAAP", "ASC", "公认会计原则", "SEC"],
        "en": ["US GAAP", "Generally Accepted Accounting Principles", "ASC", "codification"],
    },
    "CN_GAAP": {
        "zh": ["企业会计准则", "中国会计准则", "CAS", "财政部", "财会"],
        "en": ["Chinese Accounting Standards", "CAS", "Ministry of Finance"],
    },
}

# 三大体系识别特征短语
_STANDARD_PHRASES: dict[str, list[str]] = {
    "IFRS": [
        "fair value through profit or loss", "fair value through OCI",
        "other comprehensive income", "statement of changes in equity",
        "impairment of assets", "borrowing costs",
    ],
    "US_GAAP": [
        "available for sale", "held to maturity", "trading securities",
        "accumulated other comprehensive income", "comprehensive income",
        "goodwill impairment", "ASC 350", "FASB",
    ],
    "CN_GAAP": [
        "公允价值变动损益", "资本公积", "其他综合收益",
        "资产减值损失", "递延所得税资产", "会计政策变更",
        "财政部", "企业会计准则第",
    ],
}

# ------------------------------------------------------------------
# 准则差异知识库（核心差异点）
# ------------------------------------------------------------------

_DIFF_TYPES = {
    "recognition": "确认差异",
    "measurement": "计量差异",
    "presentation": "列报差异",
    "disclosure": "披露差异",
    "consolidation": "合并差异",
}

_SEED_DIFFERENCES: list[dict] = [
    {
        "diff_id": "DIF-001",
        "area": "收入确认",
        "standards": ["IFRS", "US_GAAP"],
        "ifrs_ref": "IFRS 15",
        "gaap_ref": "ASC 606",
        "diff_type": "recognition",
        "ifrs_treatment": "五步法模型（识别合同/识别履约义务/确定交易价格/分摊/履行时确认）",
        "gaap_treatment": "六步法模型（相似但在合同合并、可变对价约束、许可收入等方面有差异）",
        "key_differences": [
            "合同合并条件：IFRS 15 更宽松（商业实质即可），ASC 606 需同一商业实质且关联方紧密相关",
            "可变对价：IFRS 15 采用'极可能不发生重大转回'约束；ASC 606 采用'很可能不发生显著转回'",
            "许可收入：IFRS 15 基于'是否提供持续服务'；ASC 606 基于'功能性/象征性'二分法",
        ],
        "keywords_zh": ["收入确认", "五步法", "履约义务", "可变对价", "合同合并", "许可"],
        "keywords_en": ["revenue recognition", "five step", "performance obligation", "variable consideration"],
        "affected_accounts": ["营业收入", "合同负债", "应收帐款", "递延收入"],
        "impact_level": "high",
    },
    {
        "diff_id": "DIF-002",
        "area": "资产减值",
        "standards": ["IFRS", "US_GAAP"],
        "ifrs_ref": "IAS 36",
        "gaap_ref": "ASC 350-20",
        "diff_type": "measurement",
        "ifrs_treatment": "可收回金额=max(公允价值-处置费用, 使用价值)；资产组层面",
        "gaap_treatment": "两步法：先检查是否减值（账面价值>未折现现金流），再按公允价值计量；报告单元层面",
        "key_differences": [
            "减值触发不同：IFRS 每年评估是否有迹象；GAAP 仅在触发事件时评估",
            "计量基础不同：IFRS 用可收回金额；GAAP 仅在第一步通过后用公允价值",
            "计量单元不同：IFRS 资产组；GAAP 报告单元",
        ],
        "keywords_zh": ["资产减值", "减值测试", "可收回金额", "使用价值", "公允价值", "减值损失"],
        "keywords_en": ["impairment", "recoverable amount", "value in use", "impairment loss"],
        "affected_accounts": ["资产减值损失", "商誉减值", "固定资产"],
        "impact_level": "high",
    },
    {
        "diff_id": "DIF-003",
        "area": "金融工具分类与计量",
        "standards": ["IFRS", "US_GAAP"],
        "ifrs_ref": "IFRS 9",
        "gaap_ref": "ASC 320/326",
        "diff_type": "measurement",
        "ifrs_treatment": "三分类：摊余成本 / FVOCI / FVTPL；预期信用损失三阶段模型",
        "gaap_treatment": "三分类：Held-to-Maturity / Available-for-Sale / Trading；已发生损失模型",
        "key_differences": [
            "分类逻辑不同：IFRS 9 基于业务模式；GAAP 基于管理层意图",
            "减值模型：IFRS 9 预期信用损失（三阶段）；GAAP 已发生损失（ASC 326 CECL 已过渡）",
            "权益工具：IFRS 9 可选 FVOCI（不可转回）；GAAP（CECL）FVPL",
        ],
        "keywords_zh": ["金融资产", "公允价值", "摊余成本", "信用损失", "减值"],
        "keywords_en": ["financial asset", "fair value", "amortized cost", "credit loss"],
        "affected_accounts": ["金融资产", "其他综合收益", "减值准备"],
        "impact_level": "high",
    },
    {
        "diff_id": "DIF-004",
        "area": "租赁",
        "standards": ["IFRS", "US_GAAP"],
        "ifrs_ref": "IFRS 16",
        "gaap_ref": "ASC 842",
        "diff_type": "recognition",
        "ifrs_treatment": "承租人模型统一：所有租赁入表（使用权资产+租赁负债）",
        "gaap_treatment": "承租人二分法：经营租赁（表外）/融资租赁（表内）",
        "key_differences": [
            "IFRS 16 经营租赁也入表；ASC 842 经营租赁仍表外（仅确认使用权资产和租赁负债但租赁费用为直线法摊销）",
            "识别标准不同：IFRS 看资产控制权；ASC 842 看风险报酬是否转移",
        ],
        "keywords_zh": ["租赁", "经营租赁", "融资租赁", "使用权资产", "租赁负债"],
        "keywords_en": ["lease", "operating lease", "finance lease", "right of use", "lease liability"],
        "affected_accounts": ["使用权资产", "租赁负债", "租金费用", "财务费用"],
        "impact_level": "high",
    },
    {
        "diff_id": "DIF-005",
        "area": "合并财务报表",
        "standards": ["IFRS", "US_GAAP"],
        "ifrs_ref": "IFRS 10",
        "gaap_ref": "ASC 810",
        "diff_type": "consolidation",
        "ifrs_treatment": "控制模型：投资方享有可变回报 + 利用权力影响回报金额",
        "gaap_treatment": "可变利益实体(VIE)模型 + 表决权模型双重判断",
        "key_differences": [
            "IFRS 10 单一控制模型；ASC 810 VIE模型优先级高于表决权模型",
            "VIE识别：ASC 810 更侧重可变利益；IFRS 10 更侧重权力与回报",
        ],
        "keywords_zh": ["合并", "控制", "子公司", "VIE", "可变利益实体", "表决权"],
        "keywords_en": ["consolidation", "control", "subsidiary", "VIE", "variable interest"],
        "affected_accounts": ["长期股权投资", "合并报表", "少数股东权益"],
        "impact_level": "medium",
    },
    {
        "diff_id": "DIF-006",
        "area": "所得税",
        "standards": ["IFRS", "CN_GAAP"],
        "ifrs_ref": "IAS 12",
        "gaap_ref": "CAS 18",
        "diff_type": "measurement",
        "ifrs_treatment": "负债法；按未来转回时税率计量",
        "gaap_treatment": "资产负债表债务法；按现行税率计量（CAS 18 基本与 IAS 12 趋同，但部分细节差异）",
        "key_differences": [
            "税率选择：IFRS/IAS 12 用'预期转回时'；CAS 18 用'现行税率'（实际趋同但表述差异）",
            "亏损抵扣处理：IAS 12 有详细规定；CAS 18 简化处理",
        ],
        "keywords_zh": ["递延所得税", "所得税费用", "暂时性差异", "资产负债表债务法"],
        "keywords_en": ["deferred tax", "temporary difference", "income tax"],
        "affected_accounts": ["递延所得税资产", "递延所得税负债", "所得税费用"],
        "impact_level": "medium",
    },
    {
        "diff_id": "DIF-007",
        "area": "关联方交易",
        "standards": ["IFRS", "CN_GAAP"],
        "ifrs_ref": "IAS 24",
        "gaap_ref": "CAS 36",
        "diff_type": "disclosure",
        "ifrs_treatment": "强制披露关联方交易；豁免条件严格",
        "gaap_treatment": "披露要求与 IAS 24 基本一致；国有企业间交易豁免披露（CAS 36 第6条）",
        "key_differences": [
            "CAS 36 国有企业间豁免；IAS 24 无此豁免（需判断是否关联方）",
            "定义差异：IAS 24 关联方定义更广泛（包括关键管理人员近亲属）",
        ],
        "keywords_zh": ["关联方", "关联交易", "关联方关系", "披露"],
        "keywords_en": ["related party", "related transaction", "related party disclosure"],
        "affected_accounts": ["资本公积", "其他应收款", "其他应付款"],
        "impact_level": "medium",
    },
]

# 科目影响方向（准则转换时的典型调整方向）
_ADJUSTMENT_DIRECTIONS: dict[str, str] = {
    "营业收入": "credit_decrease",
    "合同负债": "credit_increase",
    "金融资产": "debit_increase",
    "其他综合收益": "credit_decrease",
    "使用权资产": "debit_increase",
    "租赁负债": "credit_increase",
    "租金费用": "debit_decrease",
    "财务费用": "debit_increase",
    "资产减值损失": "debit_increase",
    "商誉减值": "debit_increase",
    "递延所得税资产": "debit_increase",
    "递延所得税负债": "credit_increase",
}


def _count_text(text: str, patterns: list[str], lang: str = "zh") -> int:
    """统计多个关键词在文本中的累计出现次数。"""
    text_low = text.lower()
    total = 0
    for p in patterns:
        if not p:
            continue
        p_low = p.lower()
        if lang == "zh":
            # 中文用子串计数
            count = 0
            start = 0
            while True:
                idx = text_low.find(p_low, start)
                if idx == -1:
                    break
                count += 1
                start = idx + len(p_low)
            total += count
        else:
            total += len(re.findall(r"\b" + re.escape(p_low) + r"\b", text_low))
    return total


class LLMEngine(AbstractEngine):
    """AI多准则自动转换引擎（纯 stdlib 准则差异匹配 + 调节表生成）。"""

    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        self.model = {
            "standard_keywords": _STANDARD_KEYWORDS,
            "standard_phrases": _STANDARD_PHRASES,
            "differences": list(_SEED_DIFFERENCES),
            "diff_types": _DIFF_TYPES,
            "adjustment_directions": dict(_ADJUSTMENT_DIRECTIONS),
        }

    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """标准化输入。

        input_data 格式：
          {
            "from_standard": "IFRS",        # 源准则
            "to_standard": "US_GAAP",       # 目标准则
            "financial_statements": {...},   # 财务数据（可选，用于金额调整）
            "accounting_policies": [...],   # 会计政策描述列表（必填，用于差异识别）
            "notes": "附注全文",            # 附注/财务报告全文（可选）
            "industry": "制造业",           # 行业（可选）
          }
        """
        if self.model is None:
            self._load_model()

        if isinstance(input_data, str):
            input_data = {"from_standard": "IFRS", "to_standard": "US_GAAP", "notes": input_data}

        from_std = (input_data.get("from_standard") or "").upper()
        to_std = (input_data.get("to_standard") or "").upper()

        # 自动识别准则（如果未指定）
        notes = input_data.get("notes", "") or ""
        policies = input_data.get("accounting_policies", []) or []
        if isinstance(policies, str):
            policies = [policies]
        combined_text = " ".join([notes] + policies)

        if not from_std or from_std not in ("IFRS", "US_GAAP", "CN_GAAP"):
            from_std = self._detect_standard(combined_text)
        if not to_std or to_std not in ("IFRS", "US_GAAP", "CN_GAAP"):
            to_std = self._next_standard(from_std)

        return {
            "from_standard": from_std,
            "to_standard": to_std,
            "financial_statements": input_data.get("financial_statements", {}) or {},
            "accounting_policies": policies,
            "notes": notes,
            "combined_text": combined_text,
            "industry": input_data.get("industry", "") or "",
        }

    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """三步推理：准则识别 → 差异匹配 → 调节表生成。"""
        from_std = prepared["from_standard"]
        to_std = prepared["to_standard"]

        # ① 检测准则（双重验证）
        detected = self._detect_standard(prepared["combined_text"])
        if detected and detected != from_std:
            from_std = detected

        # ② 匹配差异
        matched_diffs = self._match_differences(
            prepared["combined_text"], from_std, to_std
        )

        # ③ 为每个匹配的差异生成调节分录模板
        adjustments: list[dict] = []
        for diff in matched_diffs:
            adj = self._generate_adjustment(diff, from_std, to_std, prepared["financial_statements"])
            adjustments.append(adj)

        # ④ 汇总调节表
        total_debit = sum(a.get("estimated_amount", 0) for a in adjustments if a.get("direction", "").startswith("debit"))
        total_credit = sum(a.get("estimated_amount", 0) for a in adjustments if a.get("direction", "").startswith("credit"))

        return {
            "from_standard": from_std,
            "to_standard": to_std,
            "detected_standard": detected,
            "matched_differences": matched_diffs,
            "adjustments": adjustments,
            "summary": {
                "total_differences": len(matched_diffs),
                "estimated_debit_adjustment": round(total_debit, 2),
                "estimated_credit_adjustment": round(total_credit, 2),
                "net_impact": round(total_debit - total_credit, 2),
                "by_impact_level": Counter(d["impact_level"] for d in matched_diffs),
                "by_diff_type": Counter(self.model["diff_types"].get(d["diff_type"], d["diff_type"]) for d in matched_diffs),
            },
        }

    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """添加审计视角 + 重要性分级 + 审计计划建议。"""
        matched = result.get("matched_differences", [])
        adjustments = result.get("adjustments", [])

        # 按影响等级排序
        impact_order = {"high": 0, "medium": 1, "low": 2}
        result["matched_differences"] = sorted(
            matched, key=lambda d: impact_order.get(d.get("impact_level", "low"), 99)
        )
        result["adjustments"] = sorted(
            adjustments, key=lambda a: -a.get("estimated_amount", 0)
        )

        # 审计计划建议
        audit_steps: list[str] = []
        if any(d["impact_level"] == "high" for d in matched):
            audit_steps.append("✓ 识别重大差异项目，安排专业人员进行逐项验证")
        if any(d["diff_type"] == "recognition" for d in matched):
            audit_steps.append("✓ 重新评估关键交易的确认时点是否符合目标准则")
        if any(d["diff_type"] == "measurement" for d in matched):
            audit_steps.append("✓ 重新计量关键资产负债表项目（减值/租赁/金融工具等）")
        audit_steps.append("✓ 编制完整的准则转换调节表，确保借贷平衡")
        audit_steps.append("✓ 评估转换后财务指标的重要性和报告影响")
        audit_steps.append("✓ 保留完整转换记录，支持审计追溯")

        result["audit_plan"] = {
            "module": "CB-04",
            "family": "llm_rag",
            "conversion_scope": f"{result['from_standard']} → {result['to_standard']}",
            "audit_steps": audit_steps,
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 内部：准则识别
    # ------------------------------------------------------------------
    def _detect_standard(self, text: str) -> str:
        if not text:
            return ""
        scores: dict[str, float] = {}
        for std, kws in self.model["standard_keywords"].items():
            zh_score = _count_text(text, kws["zh"], "zh") * 1.0
            en_score = _count_text(text, kws["en"], "en") * 1.5
            phrase_score = sum(1 for p in self.model["standard_phrases"].get(std, [])
                              if p.lower() in text.lower()) * 2.0
            scores[std] = zh_score + en_score + phrase_score
        if not scores:
            return ""
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else ""

    def _next_standard(self, current: str) -> str:
        """默认目标准则（用于双向转换）。"""
        mapping = {
            "IFRS": "US_GAAP",
            "US_GAAP": "IFRS",
            "CN_GAAP": "IFRS",
        }
        return mapping.get(current, "US_GAAP")

    # ------------------------------------------------------------------
    # 内部：差异匹配（关键词 + 语义相似度）
    # ------------------------------------------------------------------
    def _match_differences(self, text: str, from_std: str, to_std: str) -> list[dict]:
        matched: list[dict] = []
        for diff in self.model["differences"]:
            if from_std not in diff["standards"] and to_std not in diff["standards"]:
                continue

            keywords = diff.get("keywords_zh", []) + diff.get("keywords_en", [])
            keyword_hits = 0
            for kw in keywords:
                if kw.lower() in text.lower():
                    keyword_hits += 1

            # 语义相似度（用会计政策区域匹配）
            area_zh = diff["area"]
            area_sim = difflib.SequenceMatcher(None, text[:5000], area_zh).ratio()

            # 综合评分
            score = keyword_hits * 1.0 + area_sim * 5.0

            if score >= 1.0 or keyword_hits > 0:
                entry = {
                    **diff,
                    "match_score": round(score, 4),
                    "keyword_hits": keyword_hits,
                    "semantic_similarity": round(area_sim, 4),
                    "relevant_to_conversion": from_std in diff["standards"] and to_std in diff["standards"],
                }
                matched.append(entry)

        matched.sort(key=lambda d: -d["match_score"])
        return matched

    # ------------------------------------------------------------------
    # 内部：生成调节分录模板
    # ------------------------------------------------------------------
    def _generate_adjustment(self, diff: dict, from_std: str, to_std: str, fs: dict) -> dict:
        area = diff["area"]
        affected = diff.get("affected_accounts", [])
        direction_map = self.model["adjustment_directions"]

        # 从财务数据估算调整金额（如提供了报表数据）
        estimated = 0.0
        for acc in affected:
            bal = fs.get("balance_sheet", {}).get(acc) or fs.get("income_statement", {}).get(acc) or 0
            try:
                bal_num = float(bal)
                # 假设 5-15% 差异影响比例
                pct = {"high": 0.12, "medium": 0.06, "low": 0.03}.get(diff.get("impact_level", "low"), 0.05)
                estimated += abs(bal_num) * pct
            except (ValueError, TypeError):
                continue

        # 生成借/贷分录
        debit_accounts: list[dict] = []
        credit_accounts: list[dict] = []
        for acc in affected:
            direction = direction_map.get(acc, "")
            amount = round(estimated / max(len(affected), 1), 2)
            if "debit_increase" in direction or "debit_decrease" in direction:
                debit_accounts.append({"account": acc, "amount": amount})
            elif "credit_increase" in direction or "credit_decrease" in direction:
                credit_accounts.append({"account": acc, "amount": amount})
            else:
                # 默认为借方增加（资产类）
                debit_accounts.append({"account": acc, "amount": amount})

        return {
            "diff_id": diff["diff_id"],
            "area": area,
            "from_treatment": diff.get("ifrs_treatment") if from_std == "IFRS" else diff.get("gaap_treatment"),
            "to_treatment": diff.get("ifrs_treatment") if to_std == "IFRS" else diff.get("gaap_treatment"),
            "estimated_amount": round(estimated, 2),
            "direction": diff.get("impact_level", "medium"),
            "debit_accounts": debit_accounts,
            "credit_accounts": credit_accounts,
            "adjustment_note": (
                f"因 {area} 在 {from_std} 与 {to_std} 的处理差异"
                f"（{self.model['diff_types'].get(diff['diff_type'], diff['diff_type'])}）"
                f"，建议上述账户调整"
            ),
        }
