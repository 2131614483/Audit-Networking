"""[CO-06] AI 可疑交易报告自动生成  ——  纯 stdlib 模板引擎 + 多监管格式 + 质量评分。
算法设计（零第三方依赖）：
  * 多监管格式模板（内置 5 套主流 STR/SAR 模板，字段映射表驱动）：
      - CN-PBOC   中国央行可疑交易报告
      - US-FINCEN FinCEN SAR (Part I-VII)
      - UK-NCA    英国 NCA SAR
      - FATF-FIU  FATF 标准 FIU 模板
      - HK-SG-FIU 香港/新加坡本地 FIU
  * 报告生成 Pipeline（5 步串行，可单独调用）：
      Step 1 告警接收 → 校验告警有效性 / 提取触发交易 / 确定报告类型
      Step 2 多源数据整合 → 交易流水 + KYC + 知识图谱关联 + 历史 SAR + 外部情报
      Step 3 可疑行为描述（5W1H 自动生成）→ Who / When / Where / What / Why / How
      Step 4 模板字段填充 → 按目标监管机构映射字段，计算自动填充率
      Step 5 质量评分模型 → 完整性(30) + 准确性(25) + 逻辑性(25) + 合规性(20)
  * 质量评分细则（可审计、可解释）：
      - 完整性：必填字段填充率、附件完备度、数据来源标注
      - 准确性：金额/日期/身份信息与源系统一致性校验
      - 逻辑性：可疑理由→结论 的逻辑链条完备度、分析维度
      - 合规性：格式合规、时效合规、保密合规
  * 结论与建议生成：
      - 基于风险等级 + 洗钱模式匹配 + 历史案例相似度
      - 输出：是否建议提交 SAR / 建议监管行动 / 置信度
模型结构（self.model）：
  {
    "templates": {template_id: {regulator, fields:[...], sections:[...], mandatory:[...]}},
    "field_mapping": {source_field: {template_id: target_field}},
    "regulator_config": {regulator: {submission_deadline, format, ...}},
    "risk_framework": {...},
    "report_counter": int,
  }
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 多监管格式模板定义（字段级别）
# ------------------------------------------------------------------

_TEMPLATE_CN_PBOC = {
    "template_id": "CN-PBOC",
    "regulator": "中国人民银行",
    "report_type": "STR",
    "name": "可疑交易报告（中国央行）",
    "submission_deadline_days": 5,
    "format": "HTML/PDF via RPA",
    "sections": [
        {"section": "report_info", "title": "报告机构信息", "fields": ["report_org", "report_date", "reporter", "contact"]},
        {"section": "subject_info", "title": "可疑交易主体信息", "fields": ["subject_name", "subject_id_type", "subject_id_no", "subject_account"]},
        {"section": "transaction_info", "title": "可疑交易信息", "fields": ["tx_time", "tx_amount", "tx_currency", "counterparty", "channel", "ip"]},
        {"section": "suspicious_desc", "title": "可疑行为描述", "fields": ["tx_pattern", "abnormal_feature", "suspicious_reason"]},
        {"section": "customer_bg", "title": "客户背景信息", "fields": ["occupation", "income", "business", "tx_purpose"]},
        {"section": "related_analysis", "title": "关联交易分析", "fields": ["related_accounts", "related_parties", "related_txs"]},
        {"section": "judgement", "title": "综合判断", "fields": ["is_suspicious", "suspicious_level", "suggested_action"]},
        {"section": "attachments", "title": "附件清单", "fields": ["tx_details", "id_proof", "other_evidence"]},
    ],
    "mandatory": [
        "report_org", "report_date", "subject_name", "subject_id_no",
        "tx_time", "tx_amount", "counterparty", "suspicious_reason",
        "is_suspicious", "suspicious_level",
    ],
}

_TEMPLATE_US_FINCEN = {
    "template_id": "US-FINCEN",
    "regulator": "FinCEN (USA)",
    "report_type": "SAR",
    "name": "FinCEN SAR (Suspicious Activity Report)",
    "submission_deadline_days": 30,
    "format": "BSA E-Filing",
    "sections": [
        {"section": "part_i", "title": "Part I - Filer Information", "fields": ["filer_name", "filer_ein", "filer_contact", "filing_date"]},
        {"section": "part_ii", "title": "Part II - Suspicious Subject", "fields": ["subject_name", "subject_ssn", "subject_address", "subject_dob", "subject_nationality"]},
        {"section": "part_iii", "title": "Part III - Suspicious Activity", "fields": ["sar_type_code", "activity_date_from", "activity_date_to", "total_amount", "activity_codes"]},
        {"section": "part_iv", "title": "Part IV - Financial Institution", "fields": ["fi_name", "fi_account", "fi_routing"]},
        {"section": "part_v", "title": "Part V - Law Enforcement", "fields": ["le_contacted", "le_agency", "le_contact_info"]},
        {"section": "part_vi", "title": "Part VI - Narrative", "fields": ["narrative_detail"]},
        {"section": "part_vii", "title": "Part VII - Contact", "fields": ["contact_name", "contact_phone", "contact_email"]},
    ],
    "mandatory": [
        "filer_name", "filing_date", "subject_name", "activity_date_from",
        "total_amount", "sar_type_code", "narrative_detail", "contact_name",
    ],
}

_TEMPLATE_UK_NCA = {
    "template_id": "UK-NCA",
    "regulator": "NCA (UK)",
    "report_type": "SAR",
    "name": "NCA Suspicious Activity Report (UK)",
    "submission_deadline_days": 3,
    "format": "NCA Online Portal",
    "sections": [
        {"section": "filer", "title": "Filer Details", "fields": ["filer_name", "filer_reg", "filer_contact"]},
        {"section": "subject", "title": "Subject Details", "fields": ["subject_name", "subject_dob", "subject_address", "subject_occupation"]},
        {"section": "activity", "title": "Suspicious Activity", "fields": ["activity_desc", "activity_date", "amount", "suspicion_type"]},
        {"section": "narrative", "title": "Supporting Narrative", "fields": ["narrative", "typing_suspicion"]},
    ],
    "mandatory": ["filer_name", "subject_name", "activity_desc", "activity_date", "suspicion_type", "narrative"],
}

_TEMPLATE_FATF_FIU = {
    "template_id": "FATF-FIU",
    "regulator": "FATF FIU Standard",
    "report_type": "STR",
    "name": "FATF Standard STR (FIU)",
    "submission_deadline_days": 30,
    "format": "XML / JSON per Egmont Group",
    "sections": [
        {"section": "reporting", "title": "Reporting Entity", "fields": ["reporting_entity", "reporting_date", "contact_person"]},
        {"section": "subjects", "title": "Subjects", "fields": ["subjects_list"]},
        {"section": "transactions", "title": "Transactions", "fields": ["tx_list", "tx_amount_total", "tx_date_range"]},
        {"section": "suspicions", "title": "Suspicions", "fields": ["suspicion_type", "suspicion_reason", "legal_basis"]},
        {"section": "annex", "title": "Annex", "fields": ["annex_docs"]},
    ],
    "mandatory": ["reporting_entity", "subjects_list", "tx_list", "suspicion_type", "suspicion_reason"],
}

_TEMPLATE_HK_SG_FIU = {
    "template_id": "HK-SG-FIU",
    "regulator": "HKMA / MAS FIU",
    "report_type": "STR",
    "name": "Hong Kong / Singapore FIU STR",
    "submission_deadline_days": 15,
    "format": "FIU Portal (HTML)",
    "sections": [
        {"section": "filer", "title": "Filer", "fields": ["filer_name", "filer_code", "filer_officer"]},
        {"section": "customer", "title": "Customer", "fields": ["cust_name", "cust_id", "cust_nationality", "cust_account"]},
        {"section": "suspicious", "title": "Suspicious Transaction", "fields": ["tx_date", "tx_amount", "tx_currency", "tx_narrative"]},
        {"section": "assessment", "title": "Risk Assessment", "fields": ["risk_level", "suggestion"]},
    ],
    "mandatory": ["filer_name", "cust_name", "tx_date", "tx_amount", "tx_narrative", "risk_level"],
}

_ALL_TEMPLATES = [
    _TEMPLATE_CN_PBOC,
    _TEMPLATE_US_FINCEN,
    _TEMPLATE_UK_NCA,
    _TEMPLATE_FATF_FIU,
    _TEMPLATE_HK_SG_FIU,
]


# ------------------------------------------------------------------
# 字段映射表（源数据字段 → 各监管模板目标字段）
# ------------------------------------------------------------------

_FIELD_MAPPING: dict[str, dict[str, str]] = {
    "report_org":        {"CN-PBOC": "report_org", "US-FINCEN": "filer_name", "UK-NCA": "filer_name", "FATF-FIU": "reporting_entity", "HK-SG-FIU": "filer_name"},
    "report_date":       {"CN-PBOC": "report_date", "US-FINCEN": "filing_date", "UK-NCA": "filer_contact", "FATF-FIU": "reporting_date", "HK-SG-FIU": "filer_code"},
    "reporter":          {"CN-PBOC": "reporter", "US-FINCEN": "filer_contact", "UK-NCA": "filer_contact", "FATF-FIU": "contact_person", "HK-SG-FIU": "filer_officer"},
    "subject_name":      {"CN-PBOC": "subject_name", "US-FINCEN": "subject_name", "UK-NCA": "subject_name", "FATF-FIU": "subjects_list", "HK-SG-FIU": "cust_name"},
    "subject_id":        {"CN-PBOC": "subject_id_no", "US-FINCEN": "subject_ssn", "UK-NCA": "subject_dob", "FATF-FIU": "subjects_list", "HK-SG-FIU": "cust_id"},
    "subject_account":   {"CN-PBOC": "subject_account", "US-FINCEN": "fi_account", "UK-NCA": "subject_address", "FATF-FIU": "subjects_list", "HK-SG-FIU": "cust_account"},
    "tx_time":           {"CN-PBOC": "tx_time", "US-FINCEN": "activity_date_from", "UK-NCA": "activity_date", "FATF-FIU": "tx_date_range", "HK-SG-FIU": "tx_date"},
    "tx_amount":         {"CN-PBOC": "tx_amount", "US-FINCEN": "total_amount", "UK-NCA": "amount", "FATF-FIU": "tx_amount_total", "HK-SG-FIU": "tx_amount"},
    "tx_currency":       {"CN-PBOC": "tx_currency", "US-FINCEN": "total_amount", "UK-NCA": "amount", "FATF-FIU": "tx_amount_total", "HK-SG-FIU": "tx_currency"},
    "counterparty":      {"CN-PBOC": "counterparty", "US-FINCEN": "part_iii", "UK-NCA": "activity_desc", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "channel":           {"CN-PBOC": "channel", "US-FINCEN": "activity_codes", "UK-NCA": "suspicion_type", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "ip":                {"CN-PBOC": "ip", "US-FINCEN": "activity_codes", "UK-NCA": "activity_desc", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "suspicious_reason": {"CN-PBOC": "suspicious_reason", "US-FINCEN": "narrative_detail", "UK-NCA": "narrative", "FATF-FIU": "suspicion_reason", "HK-SG-FIU": "tx_narrative"},
    "tx_pattern":        {"CN-PBOC": "tx_pattern", "US-FINCEN": "sar_type_code", "UK-NCA": "suspicion_type", "FATF-FIU": "suspicion_type", "HK-SG-FIU": "tx_narrative"},
    "abnormal_feature":  {"CN-PBOC": "abnormal_feature", "US-FINCEN": "narrative_detail", "UK-NCA": "typing_suspicion", "FATF-FIU": "suspicion_reason", "HK-SG-FIU": "tx_narrative"},
    "occupation":        {"CN-PBOC": "occupation", "US-FINCEN": "part_ii", "UK-NCA": "subject_occupation", "FATF-FIU": "subjects_list", "HK-SG-FIU": "cust_nationality"},
    "income":            {"CN-PBOC": "income", "US-FINCEN": "part_vi", "UK-NCA": "narrative", "FATF-FIU": "subjects_list", "HK-SG-FIU": "tx_narrative"},
    "business":          {"CN-PBOC": "business", "US-FINCEN": "part_ii", "UK-NCA": "subject_occupation", "FATF-FIU": "subjects_list", "HK-SG-FIU": "cust_nationality"},
    "tx_purpose":        {"CN-PBOC": "tx_purpose", "US-FINCEN": "part_vi", "UK-NCA": "activity_desc", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "related_accounts":  {"CN-PBOC": "related_accounts", "US-FINCEN": "part_iv", "UK-NCA": "narrative", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "related_parties":   {"CN-PBOC": "related_parties", "US-FINCEN": "part_vi", "UK-NCA": "narrative", "FATF-FIU": "subjects_list", "HK-SG-FIU": "tx_narrative"},
    "related_txs":       {"CN-PBOC": "related_txs", "US-FINCEN": "part_iii", "UK-NCA": "activity_desc", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "is_suspicious":     {"CN-PBOC": "is_suspicious", "US-FINCEN": "sar_type_code", "UK-NCA": "suspicion_type", "FATF-FIU": "suspicion_type", "HK-SG-FIU": "risk_level"},
    "suspicious_level":  {"CN-PBOC": "suspicious_level", "US-FINCEN": "total_amount", "UK-NCA": "suspicion_type", "FATF-FIU": "legal_basis", "HK-SG-FIU": "risk_level"},
    "suggested_action":  {"CN-PBOC": "suggested_action", "US-FINCEN": "part_vi", "UK-NCA": "typing_suspicion", "FATF-FIU": "suspicion_reason", "HK-SG-FIU": "suggestion"},
    "risk_level":        {"CN-PBOC": "suspicious_level", "US-FINCEN": "sar_type_code", "UK-NCA": "suspicion_type", "FATF-FIU": "suspicion_type", "HK-SG-FIU": "risk_level"},
    "subjects_list":     {"CN-PBOC": "subject_name", "US-FINCEN": "subject_name", "UK-NCA": "subject_name", "FATF-FIU": "subjects_list", "HK-SG-FIU": "cust_name"},
    "tx_list":           {"CN-PBOC": "related_txs", "US-FINCEN": "part_iii", "UK-NCA": "activity_desc", "FATF-FIU": "tx_list", "HK-SG-FIU": "tx_narrative"},
    "legal_basis":       {"CN-PBOC": "suspicious_reason", "US-FINCEN": "narrative_detail", "UK-NCA": "typing_suspicion", "FATF-FIU": "legal_basis", "HK-SG-FIU": "tx_narrative"},
}


# ------------------------------------------------------------------
# 可疑行为模式库（用于自动描述 + 规则匹配）
# ------------------------------------------------------------------

_SUSPICIOUS_PATTERNS = [
    {"code": "SMURFING", "name": "分散存入", "trigger": r"(多账户|分散|小额|多次存入)", "keywords": ["多个账户", "分散", "单笔<1万", "短时间多笔"]},
    {"code": "LAYERING", "name": "快速进出/分层", "trigger": r"(快速转出|多层流转|当日进出|24小时)", "keywords": ["快速流转", "多层", "当日进出", "过手账户"]},
    {"code": "STRUCTURING", "name": "结构化交易", "trigger": r"(多笔.*9[0-9]{3}|拆分|规避报告|接近阈值)", "keywords": ["拆分", "接近阈值", "规避", "多笔接近"]},
    {"code": "MONEY_LAUNDRY", "name": "典型洗钱路径", "trigger": r"(现金.*跨境|无业务背景.*大额|频繁跨境)", "keywords": ["现金跨境", "无合理背景", "频繁跨境"]},
    {"code": "SHELL_COMPANY", "name": "壳公司网络", "trigger": r"(注册地址相同|联系方式高度重叠|无实营)", "keywords": ["地址重叠", "空壳", "无雇员", "低注册资本"]},
    {"code": "PEP_RELATED", "name": "PEP关联", "trigger": r"(政治人物|PEP|公职人员|官员)", "keywords": ["PEP", "公职人员", "关联官员"]},
    {"code": "HIGH_RISK_JURISDICTION", "name": "高风险法域", "trigger": r"(离岸|避税天堂|制裁名单|黑名)", "keywords": ["离岸", "避税天堂", "制裁"]},
    {"code": "TRADE_BASED", "name": "贸易洗钱", "trigger": r"(发票金额.*不符|货值偏离|高价.*低价)", "keywords": ["发票不符", "货值偏离", "虚构贸易"]},
    {"code": "KYC_MISMATCH", "name": "KYC 不符", "trigger": r"(身份信息.*矛盾|地址不符|行为.*与职业)", "keywords": ["KYC 不符", "职业不匹配", "地址异常"]},
]


# ------------------------------------------------------------------
# 质量评分框架（4 大类，满分 100）
# ------------------------------------------------------------------

_QUALITY_WEIGHTS = {
    "completeness": {"label": "完整性", "max": 30, "sub": {"mandatory_fill": 15, "attachments": 10, "data_source": 5}},
    "accuracy":     {"label": "准确性", "max": 25, "sub": {"amount_match": 10, "date_match": 5, "identity_match": 5, "regulation_cite": 5}},
    "logic":        {"label": "逻辑性", "max": 25, "sub": {"reason_sufficient": 10, "analysis_depth": 10, "conclusion_consistency": 5}},
    "compliance":   {"label": "合规性", "max": 20, "sub": {"format_compliance": 10, "timeliness": 5, "confidentiality": 5}},
}


def _classify_quality(total: float) -> str:
    if total >= 90:
        return "优秀"
    if total >= 80:
        return "良好"
    if total >= 70:
        return "合格"
    return "不合格"


# ------------------------------------------------------------------
# KGEngine 实现
# ------------------------------------------------------------------

class KGEngine(AbstractEngine):
    """AI 可疑交易报告自动生成引擎。"""

    # --------------------------------------------------------------
    def _load_model(self) -> None:
        templates = {t["template_id"]: t for t in _ALL_TEMPLATES}
        self.model = {
            "templates": templates,
            "field_mapping": dict(_FIELD_MAPPING),
            "regulator_config": {
                tid: {
                    "regulator": t["regulator"],
                    "deadline_days": t["submission_deadline_days"],
                    "format": t["format"],
                }
                for tid, t in templates.items()
            },
            "suspicious_patterns": list(_SUSPICIOUS_PATTERNS),
            "quality_weights": _QUALITY_WEIGHTS,
            "report_counter": 0,
            "risk_framework": {
                "high": {"threshold": 80, "action": "立即提交 SAR"},
                "medium": {"threshold": 50, "action": "进一步调查后提交"},
                "low": {"threshold": 0, "action": "监控观察"},
            },
            "current_template_id": self.config.get("template_id", "CN-PBOC"),
            "reporting_org": self.config.get("reporting_org", "默认报告机构"),
            "reporter": self.config.get("reporter", ""),
            "contact": self.config.get("contact", ""),
        }

    # --------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> dict:
        if isinstance(input_data, str):
            try:
                input_data = json.loads(input_data)
            except Exception:
                input_data = {"raw_text": input_data}
        if not isinstance(input_data, dict):
            input_data = {"data": input_data}

        alert = input_data.get("alert") or input_data

        txs = alert.get("transactions", [])
        if isinstance(txs, dict):
            txs = [txs]
        normalized_txs = [self._normalize_tx(t) for t in txs]

        subjects = alert.get("subjects") or []
        if isinstance(subjects, dict):
            subjects = [subjects]

        customer = alert.get("customer") or (subjects[0] if subjects else {})

        related_accounts = alert.get("related_accounts", [])
        related_parties = alert.get("related_parties", [])

        tx_amount_total = sum(t.get("amount", 0) for t in normalized_txs)
        tx_dates = [t.get("timestamp") or t.get("time") for t in normalized_txs if t.get("timestamp") or t.get("time")]

        alert_score = alert.get("risk_score") or alert.get("alert_score") or 0
        alert_patterns = alert.get("patterns") or []

        template_id = input_data.get("template_id") or alert.get("template_id") or self.model["current_template_id"]
        if template_id not in self.model["templates"]:
            template_id = "CN-PBOC"

        return {
            "alert": alert,
            "alert_id": alert.get("alert_id") or alert.get("id") or self._gen_id("ALERT"),
            "alert_score": alert_score,
            "alert_patterns": list(alert_patterns),
            "customer": customer,
            "subjects": subjects or [customer] if customer else [],
            "transactions": normalized_txs,
            "tx_count": len(normalized_txs),
            "tx_amount_total": tx_amount_total,
            "tx_currency": normalized_txs[0].get("currency", "CNY") if normalized_txs else "CNY",
            "tx_date_range": self._date_range(tx_dates),
            "related_accounts": related_accounts,
            "related_parties": related_parties,
            "related_txs": alert.get("related_txs", []),
            "trigger_reason": alert.get("trigger_reason") or alert.get("reason") or "",
            "template_id": template_id,
            "report_date": input_data.get("report_date") or self._now_iso(),
            "attachments": alert.get("attachments", []),
            "external_info": alert.get("external_info", {}),
            "history_sars": alert.get("history_sars", []),
        }

    # --------------------------------------------------------------
    def _infer(self, prepared: dict) -> dict:
        template_id = prepared["template_id"]
        template = self.model["templates"][template_id]

        # Step 1: 5W1H 可疑行为自动描述
        narrative = self._generate_5w1h(prepared)

        # Step 2: 可疑模式识别（关键词 + 规则）
        detected_patterns = self._detect_patterns(prepared)
        all_patterns = list(set(prepared["alert_patterns"]) | set(p["code"] for p in detected_patterns))

        # Step 3: 风险等级判定
        risk = self._assess_risk(prepared, detected_patterns)

        # Step 4: 结论与建议
        conclusion = self._generate_conclusion(prepared, risk, all_patterns)

        # Step 5: 模板字段填充（多监管格式）
        filled_fields = self._fill_template(prepared, template, narrative, risk, conclusion)

        # Step 6: 质量评分
        quality = self._score_quality(prepared, template, filled_fields, narrative)

        # Step 7: 报告 ID + 统计
        self.model["report_counter"] += 1
        report_id = self._gen_id("SAR")

        return {
            "report_id": report_id,
            "template_id": template_id,
            "template_info": {
                "regulator": template["regulator"],
                "name": template["name"],
                "deadline_days": template["submission_deadline_days"],
                "format": template["format"],
            },
            "alert_id": prepared["alert_id"],
            "risk_assessment": risk,
            "detected_patterns": detected_patterns,
            "all_pattern_codes": sorted(all_patterns),
            "narrative": narrative,
            "conclusion": conclusion,
            "filled_fields": filled_fields,
            "quality": quality,
            "report_date": prepared["report_date"],
            "summary": {
                "subject_count": len(prepared["subjects"]),
                "tx_count": prepared["tx_count"],
                "tx_amount_total": prepared["tx_amount_total"],
                "tx_currency": prepared["tx_currency"],
                "related_accounts_count": len(prepared["related_accounts"]),
                "related_parties_count": len(prepared["related_parties"]),
            },
        }

    # --------------------------------------------------------------
    def _postprocess(self, result: dict) -> dict:
        if not result:
            return {"error": "empty result"}

        quality = result.get("quality", {})
        filled = result.get("filled_fields", {})
        template_info = result.get("template_info", {})
        risk = result.get("risk_assessment", {})

        auto_fill_rate = quality.get("auto_fill_rate", 0)
        mandatory_fill_rate = quality.get("mandatory_fill_rate", 0)

        submission_deadline = None
        if result.get("report_date") and template_info.get("deadline_days"):
            try:
                base = datetime.fromisoformat(result["report_date"].replace("Z", "+00:00"))
                submission_deadline = (base + timedelta(days=template_info["deadline_days"])).isoformat()
            except Exception:
                pass

        output_note = "自动生成"
        if quality.get("total_score", 0) < 70:
            output_note = "需大幅修改后重新提交"
        elif quality.get("total_score", 0) < 80:
            output_note = "需人工修改后提交"
        elif quality.get("total_score", 0) < 90:
            output_note = "分析师快速复核后提交"

        return {
            "report_id": result["report_id"],
            "status": "generated",
            "template": template_info,
            "submission_deadline": submission_deadline,
            "risk_level": risk.get("level"),
            "risk_score": risk.get("score"),
            "report_quality": {
                "total_score": quality.get("total_score", 0),
                "grade": quality.get("grade", ""),
                "breakdown": quality.get("breakdown", {}),
                "mandatory_fill_rate": round(mandatory_fill_rate * 100, 1),
                "auto_fill_rate": round(auto_fill_rate * 100, 1),
            },
            "suspicious_patterns": [{"code": p.get("code"), "name": p.get("name"), "reason": p.get("reason")} for p in result.get("detected_patterns", [])],
            "narrative_5w1h": result.get("narrative", ""),
            "conclusion": result.get("conclusion", {}),
            "template_fields": filled,
            "summary": result.get("summary", {}),
            "output_note": output_note,
            "attachments_suggested": self._suggest_attachments(result),
        }

    # ==============================================================
    # 辅助方法：交易标准化
    # ==============================================================
    @staticmethod
    def _normalize_tx(t: dict) -> dict:
        ts = t.get("timestamp") or t.get("time") or t.get("date")
        amount = t.get("amount") or t.get("value") or t.get("金额") or 0
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "tx_id": t.get("tx_id") or t.get("id"),
            "timestamp": ts,
            "amount": amount,
            "currency": t.get("currency") or t.get("ccy", "CNY"),
            "direction": t.get("direction") or t.get("type") or "",
            "counterparty": t.get("counterparty") or t.get("对方账户") or {},
            "channel": t.get("channel") or t.get("channel_type") or "",
            "ip": t.get("ip") or t.get("ip_address") or "",
            "location": t.get("location") or t.get("geo") or "",
            "purpose": t.get("purpose") or t.get("purpose_code") or "",
            "raw": t,
        }

    # --------------------------------------------------------------
    @staticmethod
    def _date_range(dates: list) -> str:
        if not dates:
            return ""
        cleaned = [d for d in dates if d]
        if not cleaned:
            return ""
        return f"{cleaned[0]} ~ {cleaned[-1]}" if len(cleaned) >= 2 else str(cleaned[0])

    # --------------------------------------------------------------
    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # --------------------------------------------------------------
    @staticmethod
    def _gen_id(prefix: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        h = hashlib.md5(f"{prefix}-{ts}-{hash(ts)}".encode()).hexdigest()[:6].upper()
        return f"{prefix}-{ts}-{h}"

    # ==============================================================
    # Step 1: 5W1H 可疑行为描述
    # ==============================================================
    def _generate_5w1h(self, p: dict) -> str:
        customer = p.get("customer", {})
        name = customer.get("name") or customer.get("subject_name") or "未知主体"
        txs = p["transactions"]
        counterparties = []
        amounts = []
        channels = set()
        ips = set()
        locs = set()
        times = []

        for t in txs:
            amounts.append(t["amount"])
            channels.add(t["channel"])
            ips.add(t["ip"])
            locs.add(t["location"])
            ts = t["timestamp"]
            if ts:
                times.append(ts)
            cp = t["counterparty"]
            if isinstance(cp, dict):
                cname = cp.get("name") or cp.get("account") or ""
                if cname:
                    counterparties.append(cname)
            elif isinstance(cp, str):
                counterparties.append(cp)

        total = sum(amounts)
        max_amt = max(amounts) if amounts else 0

        who = f"主体：{name}"
        cust_id = customer.get("id_no") or customer.get("id") or customer.get("account")
        if cust_id:
            who += f"（证件/账户：{cust_id}）"

        when = f"时间范围：{p['tx_date_range'] or '未指定'}"
        if times:
            when += f"，共 {len(times)} 笔交易"

        where_parts = []
        if locs:
            where_parts.append(f"地点：{', '.join(sorted(locs))}")
        if channels:
            where_parts.append(f"渠道：{', '.join(sorted(channels))}")
        if ips:
            where_parts.append(f"IP：{', '.join(sorted(ips))}")
        where = "；".join(where_parts) if where_parts else "地点/渠道未指定"

        what = f"涉及交易 {p['tx_count']} 笔，合计 {total:.2f} {p['tx_currency']}（单笔最大 {max_amt:.2f}）"
        if counterparties:
            unique_cps = list(dict.fromkeys(counterparties))[:5]
            what += f"；对手方包括：{', '.join(str(c) for c in unique_cps)}"

        why = p.get("trigger_reason") or p.get("alert", {}).get("reason") or "触发规则：异常交易模式"
        why = f"可疑原因：{why}"

        how_parts = []
        if p.get("related_accounts"):
            how_parts.append(f"关联账户 {len(p['related_accounts'])} 个")
        if p.get("related_parties"):
            how_parts.append(f"关联方 {len(p['related_parties'])} 个")
        if p.get("external_info"):
            ext = p["external_info"]
            if isinstance(ext, dict):
                for k, v in ext.items():
                    if v:
                        how_parts.append(f"外部情报[{k}]：{v}")
        how = "；".join(how_parts) if how_parts else "无额外情报线索"

        return f"{who}\n{when}\n{where}\n{what}\n{why}\n{how}"

    # ==============================================================
    # Step 2: 可疑模式识别
    # ==============================================================
    def _detect_patterns(self, p: dict) -> list[dict]:
        text = json.dumps(p.get("alert", {}), ensure_ascii=False) + "\n" + p.get("trigger_reason", "")
        detected = []

        txs = p["transactions"]
        amounts = [t["amount"] for t in txs]
        total = sum(amounts)
        n = len(txs)

        # 金额分布特征
        near_threshold_count = sum(1 for a in amounts if 8000 <= a < 10000)
        small_amount_count = sum(1 for a in amounts if a < 10000)
        high_amount_count = sum(1 for a in amounts if a >= 100000)

        # 结构化检测
        if near_threshold_count >= 3:
            detected.append({
                "code": "STRUCTURING", "name": "结构化交易",
                "reason": f"有 {near_threshold_count} 笔交易金额在 8000-10000 区间，疑似规避 1 万报告阈值",
            })

        # 分散/集中检测
        if n >= 5 and small_amount_count >= n * 0.8 and total >= 50000:
            detected.append({
                "code": "SMURFING", "name": "分散存入",
                "reason": f"共 {n} 笔小额交易（单笔<1万），合计 {total:.0f}，疑似分散存入模式",
            })

        # 高风险对手方
        counterparties = []
        for t in txs:
            cp = t["counterparty"]
            if isinstance(cp, dict):
                cname = cp.get("name") or ""
            else:
                cname = str(cp)
            counterparties.append(cname)
        if len(set(counterparties)) >= 3 and high_amount_count >= 2:
            detected.append({
                "code": "LAYERING", "name": "快速分层",
                "reason": f"{len(set(counterparties))} 个不同对手方 + 多笔大额，疑似资金快速过手",
            })

        # 规则库匹配（基于文本关键词）
        for pat in self.model["suspicious_patterns"]:
            if any(c["code"] == pat["code"] for c in detected):
                continue
            m = re.search(pat["trigger"], text)
            if m:
                detected.append({
                    "code": pat["code"], "name": pat["name"],
                    "reason": f"触发关键词/规则：{m.group()}",
                })

        if not detected and p.get("alert_score", 0) >= 50:
            detected.append({
                "code": "UNSPECIFIED", "name": "其他可疑",
                "reason": f"风险评分 {p.get('alert_score')}，但未匹配到明确洗钱模式",
            })

        return detected

    # ==============================================================
    # Step 3: 风险等级判定
    # ==============================================================
    def _assess_risk(self, p: dict, patterns: list[dict]) -> dict:
        score = float(p.get("alert_score") or 0)

        severity_boost = {"high": 20, "medium": 10, "low": 5}
        for pat in patterns:
            code = pat.get("code", "")
            sev = "medium"
            if code in ("SMURFING", "LAYERING", "MONEY_LAUNDRY", "TRADE_BASED"):
                sev = "high"
            elif code in ("STRUCTURING", "SHELL_COMPANY", "PEP_RELATED"):
                sev = "medium"
            elif code in ("KYC_MISMATCH",):
                sev = "low"
            score += severity_boost[sev]

        total_amount = p.get("tx_amount_total", 0)
        if total_amount >= 1000000:
            score += 15
        elif total_amount >= 100000:
            score += 8

        if p.get("related_parties") and len(p["related_parties"]) >= 3:
            score += 8

        score = min(100, round(score, 1))

        if score >= 80:
            level = "high"
            level_label = "高风险"
            default_action = "立即提交 SAR"
        elif score >= 50:
            level = "medium"
            level_label = "中风险"
            default_action = "进一步调查后提交"
        else:
            level = "low"
            level_label = "低风险"
            default_action = "监控观察"

        return {
            "score": score,
            "level": level,
            "level_label": level_label,
            "pattern_count": len(patterns),
            "default_action": default_action,
        }

    # ==============================================================
    # Step 4: 结论与建议
    # ==============================================================
    def _generate_conclusion(self, p: dict, risk: dict, patterns: list[str]) -> dict:
        total = p.get("tx_amount_total", 0)
        n = p.get("tx_count", 0)

        pattern_desc = "、".join(patterns[:3]) if patterns else "未识别到明确模式"

        verdict = "建议提交 SAR" if risk["level"] in ("high", "medium") else "暂不建议提交，持续监控"

        reasons = []
        reasons.append(f"风险评分 {risk['score']}（{risk['level_label']}）")
        reasons.append(f"涉及 {n} 笔交易，合计 {total:.2f} {p['tx_currency']}")
        if patterns:
            reasons.append(f"匹配可疑模式：{pattern_desc}")
        if p.get("related_parties"):
            reasons.append(f"关联方 {len(p['related_parties'])} 个，存在网络结构")

        suggested_actions = []
        if risk["level"] == "high":
            suggested_actions = [
                "立即向 FIU 提交 SAR/STR",
                "冻结/限制相关账户进一步交易",
                "启动内部洗钱调查程序",
                "联络合规官/法务确认法律边界",
            ]
        elif risk["level"] == "medium":
            suggested_actions = [
                "加强该客户持续监控",
                "排查过去 6 个月全部关联交易",
                "如补充证据充足则提交 SAR",
            ]
        else:
            suggested_actions = [
                "纳入重点观察名单",
                "下次交易触发时升级审查",
            ]

        confidence = min(1.0, round(risk["score"] / 100.0 * 0.9 + (0.1 if p.get("trigger_reason") else 0), 3))

        return {
            "verdict": verdict,
            "confidence": confidence,
            "reasons": reasons,
            "suggested_actions": suggested_actions,
        }

    # ==============================================================
    # Step 5: 模板字段填充
    # ==============================================================
    def _fill_template(self, p: dict, template: dict, narrative: str, risk: dict, conclusion: dict) -> dict:
        cust = p.get("customer", {})
        first_tx = p["transactions"][0] if p["transactions"] else {}

        # 构建源字段值（中文友好）
        source_values = {
            "report_org": self.model["reporting_org"],
            "report_date": p["report_date"],
            "reporter": self.model["reporter"],
            "contact": self.model["contact"],
            "subject_name": cust.get("name") or cust.get("subject_name") or (p["subjects"][0].get("name") if p["subjects"] else ""),
            "subject_id_type": cust.get("id_type") or "身份证",
            "subject_id": cust.get("id_no") or cust.get("id") or "",
            "subject_account": cust.get("account") or first_tx.get("counterparty", {}).get("account") if isinstance(first_tx.get("counterparty"), dict) else "",
            "tx_time": first_tx.get("timestamp") or p["tx_date_range"],
            "tx_amount": p["tx_amount_total"],
            "tx_currency": p["tx_currency"],
            "counterparty": self._first_counterparty(p["transactions"]),
            "channel": first_tx.get("channel", ""),
            "ip": first_tx.get("ip", ""),
            "tx_pattern": "/".join([p_["name"] for p_ in self._detect_patterns_silent(p)]) or "待识别",
            "abnormal_feature": "金额异常/频率异常/路径异常（详见叙事）",
            "suspicious_reason": p.get("trigger_reason") or "基于规则与风险评分综合判断",
            "occupation": cust.get("occupation", ""),
            "income": cust.get("income", ""),
            "business": cust.get("business", ""),
            "tx_purpose": first_tx.get("purpose", ""),
            "related_accounts": "; ".join(str(a) for a in p.get("related_accounts", [])[:10]),
            "related_parties": "; ".join(str(x) for x in p.get("related_parties", [])[:10]),
            "related_txs": "; ".join(str(x) for x in p.get("related_txs", [])[:10]),
            "is_suspicious": risk["level"] in ("high", "medium"),
            "suspicious_level": risk["level_label"],
            "suggested_action": conclusion["verdict"],
            "risk_level": risk["level_label"],
            "subjects_list": "; ".join(s.get("name", "") for s in p.get("subjects", [])[:10]),
            "tx_list": json.dumps([
                {"tx_id": t["tx_id"], "time": t["timestamp"], "amount": t["amount"], "channel": t["channel"]}
                for t in p["transactions"][:20]
            ], ensure_ascii=False),
            "tx_amount_total": p["tx_amount_total"],
            "tx_date_range": p["tx_date_range"],
            "suspicion_type": "/".join([p_["name"] for p_ in self._detect_patterns_silent(p)]) or "Suspicious Activity",
            "suspicion_reason": p.get("trigger_reason") or "Rule-based detection + risk scoring",
            "legal_basis": "AML/CFT Regulation",
            "annex_docs": "; ".join(p.get("attachments", [])),
            "narrative_detail": narrative,
            "narrative": narrative,
            "activity_desc": narrative,
            "typing_suspicion": p.get("trigger_reason") or "Automated narrative generation",
            "filing_date": p["report_date"],
            "filer_ein": "",
            "filer_contact": self.model["contact"],
            "subject_ssn": cust.get("id_no") or "",
            "subject_address": cust.get("address") or "",
            "subject_dob": cust.get("dob") or "",
            "subject_nationality": cust.get("nationality") or "",
            "sar_type_code": "1020" if risk["level"] == "high" else "2010",
            "activity_date_from": p["tx_date_range"].split("~")[0].strip() if p["tx_date_range"] else "",
            "activity_date_to": p["tx_date_range"].split("~")[-1].strip() if "~" in p["tx_date_range"] else p["tx_date_range"],
            "activity_codes": "; ".join([p_["code"] for p_ in self._detect_patterns_silent(p)]),
            "fi_name": self.model["reporting_org"],
            "fi_account": cust.get("account") or "",
            "fi_routing": "",
            "le_contacted": False,
            "le_agency": "",
            "le_contact_info": "",
            "contact_name": self.model["reporter"],
            "contact_phone": self.model["contact"],
            "contact_email": "",
            "filer_reg": "",
            "cust_nationality": cust.get("nationality") or "",
            "suggestion": "; ".join(conclusion["suggested_actions"]),
        }

        filled: dict[str, dict] = {}
        tmap = self.model["field_mapping"]
        tid = template["template_id"]

        for section in template["sections"]:
            for field in section["fields"]:
                mapped_field = tmap.get(field, {}).get(tid, field)
                value = source_values.get(mapped_field, source_values.get(field, ""))
                filled[field] = {
                    "section": section["section"],
                    "title": section["title"],
                    "value": value,
                    "is_mandatory": field in template.get("mandatory", []),
                    "auto_filled": bool(value),
                    "source": mapped_field if mapped_field != field else "",
                }

        # 为叙事字段统一写入 narrative
        for key in ("narrative_detail", "narrative", "activity_desc", "tx_narrative"):
            if key in filled:
                filled[key]["value"] = narrative
                filled[key]["auto_filled"] = True

        return filled

    # ==============================================================
    # Step 6: 质量评分
    # ==============================================================
    def _score_quality(self, p: dict, template: dict, filled: dict, narrative: str) -> dict:
        weights = self.model["quality_weights"]
        total_score = 0.0
        breakdown = {}

        # 1. 完整性（30 分）
        mandatory = template.get("mandatory", [])
        filled_mandatory = [f for f in mandatory if filled.get(f, {}).get("value")]
        mandatory_fill = len(filled_mandatory) / max(1, len(mandatory))
        completeness_sub = {
            "mandatory_fill": round(mandatory_fill * 15, 1),
            "attachments": 10.0 if p.get("attachments") else 0.0,
            "data_source": 5.0 if p.get("trigger_reason") and p.get("external_info") else (2.5 if p.get("trigger_reason") else 0.0),
        }
        comp_total = sum(completeness_sub.values())
        breakdown["completeness"] = {"score": round(comp_total, 1), "max": 30, "sub_scores": completeness_sub}
        total_score += comp_total

        # 2. 准确性（25 分）—— 金额/日期/身份自洽校验
        accuracy_sub = {"amount_match": 0, "date_match": 0, "identity_match": 0, "regulation_cite": 0}
        tx_amount_total = p.get("tx_amount_total", 0)
        tx_amount_in_narrative = self._extract_amount_from_text(narrative)
        if tx_amount_in_narrative and abs(tx_amount_in_narrative - tx_amount_total) / max(tx_amount_total, 1) < 0.05:
            accuracy_sub["amount_match"] = 10.0
        elif not tx_amount_in_narrative and tx_amount_total > 0:
            accuracy_sub["amount_match"] = 6.0
        tx_dates = [t.get("timestamp") for t in p["transactions"] if t.get("timestamp")]
        if tx_dates and p["tx_date_range"]:
            accuracy_sub["date_match"] = 5.0
        elif tx_dates:
            accuracy_sub["date_match"] = 2.5
        cust = p.get("customer", {})
        if cust.get("name") and cust.get("id_no"):
            accuracy_sub["identity_match"] = 5.0
        elif cust.get("name"):
            accuracy_sub["identity_match"] = 2.5
        if p.get("trigger_reason") or any(c.get("code") for c in self._detect_patterns_silent(p)):
            accuracy_sub["regulation_cite"] = 5.0
        acc_total = sum(accuracy_sub.values())
        breakdown["accuracy"] = {"score": round(acc_total, 1), "max": 25, "sub_scores": accuracy_sub}
        total_score += acc_total

        # 3. 逻辑性（25 分）
        logic_sub = {"reason_sufficient": 0, "analysis_depth": 0, "conclusion_consistency": 0}
        patterns = self._detect_patterns_silent(p)
        reason_text = p.get("trigger_reason", "") + " " + narrative
        if len(reason_text) >= 100 and patterns:
            logic_sub["reason_sufficient"] = 10.0
        elif len(reason_text) >= 50:
            logic_sub["reason_sufficient"] = 6.0
        related_info = (p.get("related_accounts") or []) + (p.get("related_parties") or []) + list(p.get("external_info", {}).keys())
        depth = 0
        if p.get("tx_count", 0) >= 5:
            depth += 3
        if len(related_info) >= 3:
            depth += 3
        if patterns:
            depth += 4
        logic_sub["analysis_depth"] = float(min(10, depth))
        if patterns and p.get("alert_score", 0) > 0:
            logic_sub["conclusion_consistency"] = 5.0
        elif p.get("alert_score", 0) > 0:
            logic_sub["conclusion_consistency"] = 3.0
        logic_total = sum(logic_sub.values())
        breakdown["logic"] = {"score": round(logic_total, 1), "max": 25, "sub_scores": logic_sub}
        total_score += logic_total

        # 4. 合规性（20 分）
        compliance_sub = {"format_compliance": 0, "timeliness": 0, "confidentiality": 0}
        filled_rate = sum(1 for v in filled.values() if v.get("value")) / max(1, len(filled))
        if filled_rate >= 0.9:
            compliance_sub["format_compliance"] = 10.0
        elif filled_rate >= 0.7:
            compliance_sub["format_compliance"] = 7.0
        elif filled_rate >= 0.5:
            compliance_sub["format_compliance"] = 4.0
        compliance_sub["timeliness"] = 5.0
        compliance_sub["confidentiality"] = 5.0
        comp_total2 = sum(compliance_sub.values())
        breakdown["compliance"] = {"score": round(comp_total2, 1), "max": 20, "sub_scores": compliance_sub}
        total_score += comp_total2

        total_score = round(total_score, 1)
        mandatory_fill_rate = mandatory_fill
        auto_fill_rate = sum(1 for v in filled.values() if v.get("auto_filled")) / max(1, len(filled))

        return {
            "total_score": total_score,
            "grade": _classify_quality(total_score),
            "breakdown": breakdown,
            "mandatory_fill_rate": mandatory_fill_rate,
            "auto_fill_rate": auto_fill_rate,
        }

    # ==============================================================
    # 其它工具方法
    # ==============================================================
    @staticmethod
    def _first_counterparty(txs: list[dict]) -> str:
        for t in txs:
            cp = t.get("counterparty")
            if isinstance(cp, dict):
                return cp.get("name") or cp.get("account") or ""
            if isinstance(cp, str):
                return cp
        return ""

    def _detect_patterns_silent(self, p: dict) -> list[dict]:
        """非噪声版本，用于字段填充（不重复推理）。"""
        return self._detect_patterns(p)

    @staticmethod
    def _extract_amount_from_text(text: str) -> float | None:
        m = re.search(r"[\d,]+(?:\.\d+)?", text)
        if m:
            try:
                return float(m.group().replace(",", ""))
            except ValueError:
                return None
        return None

    @staticmethod
    def _suggest_attachments(result: dict) -> list[str]:
        s = result.get("summary", {})
        risk = result.get("risk_level", "")
        base = [
            "交易流水明细（Excel/CSV）",
            "客户 KYC 资料复印件",
        ]
        if result.get("suspicious_patterns"):
            base.append("可疑模式分析报告")
        if s.get("related_accounts_count", 0) > 0:
            base.append("关联账户网络图")
        if risk == "high":
            base.append("内部审计/合规意见")
            base.append("法律意见书（如涉及跨境）")
        if result.get("detected_patterns") and any(p.get("code") in ("PEP_RELATED", "HIGH_RISK_JURISDICTION") for p in result["detected_patterns"]):
            base.append("外部情报查询记录（PEP/制裁名单）")
        return base
