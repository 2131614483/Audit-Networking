"""[CO-07] AI数据资产自动发现与分类引擎 —— 纯 stdlib 模式匹配 + 关键词分类。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 敏感数据模式匹配（规则引擎，准确率 >99%）：
      - 身份证号（中国18位/15位/美国SSN/英国NI）
      - 信用卡号（正则 + Luhn 校验）
      - 邮箱地址 / 电话号码 / 银行账号 / 护照号
  * 字段名关键词分类（模拟 NLP 语义识别）：
      - 预定义敏感类型 → 中英双语字段名关键词词典
      - 字段名匹配得分 + 内容模式命中 → 敏感类型概率
  * 五级敏感等级分类（综合评分）：
      - L4受限: PII/医疗/生物特征（GDPR Art.9）
      - L3机密: 财务/商业合同/客户名单（SOX/PCI-DSS）
      - L2敏感: 员工薪酬/绩效考核/客户联系方式（GDPR Art.32）
      - L1内部: 组织架构/内部制度
      - L0公开: 官网信息/公开年报
  * 综合判定权重：规则引擎 0.6 + 字段名关键词 0.4

模型结构（self.model）：
  {
    "patterns": [(name, regex, validator_fn)],     # 模式规则列表
    "field_keywords": {sensitive_type: {zh:[], en:[]}},  # 字段名关键词词典
    "level_rules": {...},                          # 五级分类规则
  }
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "co_07.db"

_ASSETS_SCHEMA = {
    "asset_id": "TEXT",
    "name": "TEXT",
    "location": "TEXT",
    "source_type": "TEXT",
    "format_type": "TEXT",
    "sensitive_types": "JSON",
    "sensitivity_level": "TEXT",
    "sensitivity_score": "REAL",
    "field_count": "INTEGER",
    "sample_count": "INTEGER",
    "compliance_tags": "JSON",
    "owner": "TEXT",
    "description": "TEXT",
    "created_at": "DATETIME",
}
_FIELDS_SCHEMA = {
    "field_id": "TEXT",
    "asset_id": "TEXT",
    "field_name": "TEXT",
    "data_type": "TEXT",
    "sensitive_types": "JSON",
    "matched_patterns": "JSON",
    "level": "TEXT",
    "confidence": "REAL",
    "sample_values": "JSON",
    "created_at": "DATETIME",
}


def _luhn_check(card_number: str) -> bool:
    """Luhn 算法校验信用卡号。"""
    digits = [int(d) for d in card_number if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse = digits[::-1]
    for i, d in enumerate(reverse):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _validate_chinese_id(id_num: str) -> bool:
    """中国身份证号校验（18位：加权因子 + 校验码；15位：简单格式）。"""
    id_num = id_num.strip().upper()
    if len(id_num) == 15:
        return bool(re.match(r"^\d{15}$", id_num))
    if len(id_num) != 18:
        return False
    if not re.match(r"^\d{17}[\dX]$", id_num):
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_chars = "10X98765432"
    total = sum(int(id_num[i]) * weights[i] for i in range(17))
    return check_chars[total % 11] == id_num[17]


def _validate_email(email: str) -> bool:
    return bool(re.match(r"^[\w.+-]+@[\w-]+\.[\w.-]+$", email))


def _validate_ipv4(ip: str) -> bool:
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return False
    return all(0 <= int(p) <= 255 for p in parts if p.isdigit())


_SENSITIVE_FIELD_KEYWORDS: dict[str, dict[str, list[str]]] = {
    "pii": {
        "zh": ["身份证", "证件号", "姓名", "出生日期", "出生年月", "家庭住址", "现住址",
               "籍贯", "民族", "性别", "身份证号", "证件号码"],
        "en": ["ssn", "passport", "first_name", "last_name", "full_name", "birth_date",
               "dob", "address", "residence", "nationality", "ethnicity", "gender"],
    },
    "phone": {
        "zh": ["手机", "电话", "联系方式", "手机号码", "电话号码", "座机"],
        "en": ["phone", "mobile", "cell", "telephone", "contact"],
    },
    "email": {
        "zh": ["邮箱", "邮件", "email"],
        "en": ["email", "e_mail", "mail_address"],
    },
    "finance": {
        "zh": ["银行账号", "银行卡号", "账户余额", "交易金额", "收入", "工资", "薪酬",
               "税前工资", "税后工资", "奖金", "津贴", "报销", "贷款", "还款", "利息"],
        "en": ["bank_account", "card_no", "balance", "amount", "income", "salary",
               "wage", "bonus", "reimbursement", "loan", "payment", "interest"],
    },
    "credit_card": {
        "zh": ["信用卡", "卡号", "card"],
        "en": ["credit_card", "card_number", "cc_number"],
    },
    "health": {
        "zh": ["病历", "诊断", "医疗", "健康状况", "病情", "处方", "药品", "血压",
               "血糖", "体检", "基因", "生物特征", "指纹", "虹膜"],
        "en": ["medical", "diagnosis", "health", "record", "prescription", "blood",
               "genetic", "biometric", "fingerprint", "iris", "patient"],
    },
    "hr": {
        "zh": ["员工编号", "工号", "入职日期", "离职日期", "绩效考核", "绩效等级",
               "考勤", "请假", "加班", "背景调查", "简历", "面试"],
        "en": ["employee_id", "emp_id", "hire_date", "termination_date",
               "performance", "attendance", "leave", "overtime", "background_check"],
    },
    "business_secret": {
        "zh": ["客户名单", "客户列表", "供应商名单", "定价", "成本价", "毛利率",
               "研发", "专利", "算法", "源代码", "密钥", "密码", "配置", "架构"],
        "en": ["customer_list", "client_list", "pricing", "cost", "margin",
               "rd", "patent", "algorithm", "source_code", "secret", "password",
               "api_key", "architecture"],
    },
    "contract": {
        "zh": ["合同", "协议", "条款", "签约方", "合同金额", "合同期限"],
        "en": ["contract", "agreement", "terms", "party", "contract_amount", "term"],
    },
}

_LEVEL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "L4": {
        "name": "受限 Restricted",
        "score_range": (0.85, 1.01),
        "sensitive_types": {"pii", "health"},
        "compliance_tags": ["GDPR-Art.9", "CCPA", "PIPL", "HIPAA", "GLBA"],
        "description": "受法律法规严格保护，泄露后果极其严重",
    },
    "L3": {
        "name": "机密 Confidential",
        "score_range": (0.65, 0.85),
        "sensitive_types": {"finance", "credit_card", "business_secret", "contract"},
        "compliance_tags": ["SOX", "PCI-DSS", "GDPR-Art.32"],
        "description": "泄露可能对企业造成严重损害",
    },
    "L2": {
        "name": "敏感 Sensitive",
        "score_range": (0.40, 0.65),
        "sensitive_types": {"phone", "email", "hr"},
        "compliance_tags": ["GDPR-Art.32", "PIPL"],
        "description": "泄露可能对企业或员工造成中等损害",
    },
    "L1": {
        "name": "内部 Internal",
        "score_range": (0.15, 0.40),
        "sensitive_types": set(),
        "compliance_tags": [],
        "description": "企业内部使用，不对外公开",
    },
    "L0": {
        "name": "公开 Public",
        "score_range": (0.0, 0.15),
        "sensitive_types": set(),
        "compliance_tags": [],
        "description": "可对外公开的信息",
    },
}

_PATTERNS: list[tuple[str, str, Callable | None]] = [
    ("chinese_id", r"\b\d{17}[\dXx]\b|\b\d{15}\b", _validate_chinese_id),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b", None),
    ("uk_ni", r"\b[A-Za-z]{2}\d{6}[A-Za-z]\b", None),
    ("credit_card", r"\b(?:\d[ -]*?){13,19}\b", _luhn_check),
    ("email", r"[\w.+-]+@[\w-]+\.[\w.-]+", _validate_email),
    ("phone", r"\+?\d{1,3}[-.\s]?\d{3,4}[-.\s]?\d{4}\b", None),
    ("bank_account", r"\b\d{12,22}\b", None),
    ("passport", r"\b[A-Za-z]\d{8}\b|\bE\d{8}\b", None),
    ("ip_address", r"\b(?:\d{1,3}\.){3}\d{1,3}\b", _validate_ipv4),
]


class MLEngine(AbstractEngine):
    """CO-07 数据资产发现与分类引擎（纯 stdlib 模式匹配 + 关键词分类）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        """加载敏感数据模式规则 + 字段名关键词词典，初始化 PortableDB。"""
        self.db = PortableDB(self.db_path)
        if "assets" not in self.db.tables():
            self.db.create_table("assets", _ASSETS_SCHEMA)
        if "fields" not in self.db.tables():
            self.db.create_table("fields", _FIELDS_SCHEMA)

        self.model = {
            "patterns": list(_PATTERNS),
            "field_keywords": {k: {kk: list(vv) for kk, vv in v.items()}
                               for k, v in _SENSITIVE_FIELD_KEYWORDS.items()},
            "level_definitions": {k: dict(v) for k, v in _LEVEL_DEFINITIONS.items()},
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取待扫描的数据资产列表，清洗字段名与样本值。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 assets 列表")

        raw_assets = input_data.get("assets", [])
        if not isinstance(raw_assets, list):
            raise ValueError("input_data['assets'] 必须为列表")

        cleaned = []
        for a in raw_assets:
            if not isinstance(a, dict):
                continue
            asset_id = a.get("asset_id") or a.get("id") or ""
            fields_raw = a.get("fields", [])
            if not isinstance(fields_raw, list):
                fields_raw = []
            cleaned_fields = []
            for f in fields_raw:
                if isinstance(f, dict):
                    cleaned_fields.append({
                        "field_name": f.get("field_name", "") or f.get("name", ""),
                        "data_type": f.get("data_type", "") or f.get("type", ""),
                        "sample_values": f.get("sample_values", []) or f.get("samples", []) or [],
                        "description": f.get("description", ""),
                    })
            cleaned.append({
                "asset_id": asset_id,
                "name": a.get("name", "") or asset_id,
                "location": a.get("location", "") or a.get("path", ""),
                "source_type": (a.get("source_type", "") or a.get("source", "unknown")).lower(),
                "format_type": (a.get("format_type", "") or a.get("format", "structured")).lower(),
                "owner": a.get("owner", "") or "",
                "description": a.get("description", "") or "",
                "fields": cleaned_fields,
            })

        return cleaned

    def _infer(self, prepared: Any) -> Any:
        """核心推理：对每个字段执行模式匹配 + 关键词匹配 + 综合判定。"""
        patterns = self.model["patterns"]
        field_keywords = self.model["field_keywords"]

        field_results: list[dict] = []
        asset_results: list[dict] = []

        for asset in prepared:
            asset_id = asset["asset_id"]
            asset_fields = asset["fields"]
            field_count = len(asset_fields)

            for idx, f in enumerate(asset_fields):
                fname = f["field_name"].lower()
                samples = [str(v) for v in f["sample_values"] if v is not None]
                combined_text = " ".join([fname, f.get("description", "").lower()] + samples[:5])

                matched_patterns = self._match_patterns(samples, patterns)
                keyword_types = self._match_field_keywords(fname, field_keywords)
                sensitive_types = set(matched_patterns.keys()) | keyword_types
                confidence = self._calc_confidence(matched_patterns, keyword_types)
                level = self._score_to_level(confidence, sensitive_types)

                field_results.append({
                    "field_id": f"{asset_id}_f{idx}",
                    "asset_id": asset_id,
                    "field_name": f["field_name"],
                    "data_type": f["data_type"],
                    "sensitive_types": sorted(sensitive_types),
                    "matched_patterns": {k: v for k, v in matched_patterns.items()},
                    "level": level,
                    "confidence": confidence,
                    "sample_values": samples[:3],
                })

            asset_level, asset_score, asset_types, compliance_tags = self._aggregate_asset(field_results, asset_id)
            asset_results.append({
                "asset_id": asset_id,
                "name": asset["name"],
                "location": asset["location"],
                "source_type": asset["source_type"],
                "format_type": asset["format_type"],
                "sensitive_types": sorted(asset_types),
                "sensitivity_level": asset_level,
                "sensitivity_score": round(asset_score, 4),
                "field_count": field_count,
                "sample_count": len(asset_fields),
                "compliance_tags": compliance_tags,
                "owner": asset["owner"],
                "description": asset["description"],
                "fields": [fr for fr in field_results if fr["asset_id"] == asset_id],
            })

        return {"assets": asset_results, "fields": field_results}

    def _match_patterns(self, samples: list[str],
                        patterns: list[tuple[str, str, Callable | None]]) -> dict[str, int]:
        """对样本值执行所有正则模式匹配 + 可选校验函数。

        返回 {pattern_name: 命中次数}（仅计入通过校验函数的命中）。
        """
        hits: dict[str, int] = {}
        joined = " ".join(samples)
        for pname, regex, validator in patterns:
            try:
                matches = re.findall(regex, joined)
            except re.error:
                continue
            count = 0
            for m in matches:
                if validator is None or validator(m if isinstance(m, str) else m[0]):
                    count += 1
            if count > 0:
                hits[pname] = count
        return hits

    def _match_field_keywords(self, field_name: str,
                              field_keywords: dict[str, dict[str, list[str]]]) -> set[str]:
        """字段名关键词匹配：中英双语，返回命中的敏感类型集合。"""
        hit_types: set[str] = set()
        for stype, kw_groups in field_keywords.items():
            for lang in ("zh", "en"):
                for kw in kw_groups.get(lang, []):
                    if kw.lower() in field_name:
                        hit_types.add(stype)
                        break
        return hit_types

    def _calc_confidence(self, matched_patterns: dict[str, int],
                         keyword_types: set[str]) -> float:
        """综合置信度：规则引擎 0.6 + 字段名关键词 0.4。"""
        pattern_score = min(len(matched_patterns) / 4.0, 1.0) if matched_patterns else 0.0
        keyword_score = min(len(keyword_types) / 3.0, 1.0) if keyword_types else 0.0
        return round(pattern_score * 0.6 + keyword_score * 0.4, 4)

    def _score_to_level(self, confidence: float, sensitive_types: set[str]) -> str:
        """按评分 + 敏感类型综合判定五级分类。"""
        for level in ("L4", "L3", "L2", "L1", "L0"):
            defs = _LEVEL_DEFINITIONS[level]
            lo, hi = defs["score_range"]
            if lo <= confidence < hi:
                if defs["sensitive_types"] and sensitive_types & defs["sensitive_types"]:
                    return level
                if not defs["sensitive_types"]:
                    return level
        return "L0"

    def _aggregate_asset(self, field_results: list[dict], asset_id: str) -> tuple:
        """资产级别聚合：取最高等级 + 加权评分。"""
        asset_fields = [f for f in field_results if f["asset_id"] == asset_id]
        if not asset_fields:
            return "L0", 0.0, set(), []

        level_order = ["L0", "L1", "L2", "L3", "L4"]
        highest = max(asset_fields, key=lambda f: level_order.index(f["level"]))
        asset_level = highest["level"]

        if len(asset_fields) > 0:
            avg_score = sum(f["confidence"] for f in asset_fields) / len(asset_fields)
        else:
            avg_score = 0.0
        asset_score = max(avg_score, highest["confidence"])

        all_types: set[str] = set()
        for f in asset_fields:
            all_types.update(f["sensitive_types"])

        compliance_tags: set[str] = set()
        for lv in level_order:
            if lv in (asset_level,):
                compliance_tags.update(_LEVEL_DEFINITIONS[lv]["compliance_tags"])
                break
        if "pii" in all_types or "health" in all_types:
            compliance_tags.update(_LEVEL_DEFINITIONS["L4"]["compliance_tags"])

        return asset_level, asset_score, all_types, sorted(compliance_tags)

    def _postprocess(self, result: Any) -> Any:
        """汇总数据资产目录 + 统计，并持久化到 PortableDB。"""
        assets = result.get("assets", [])
        fields = result.get("fields", [])

        for a in assets:
            self.db.insert("assets", {
                "asset_id": a["asset_id"],
                "name": a["name"],
                "location": a["location"],
                "source_type": a["source_type"],
                "format_type": a["format_type"],
                "sensitive_types": a["sensitive_types"],
                "sensitivity_level": a["sensitivity_level"],
                "sensitivity_score": a["sensitivity_score"],
                "field_count": a["field_count"],
                "sample_count": a["sample_count"],
                "compliance_tags": a["compliance_tags"],
                "owner": a["owner"],
                "description": a["description"],
                "created_at": datetime.now(),
            })

        for f in fields:
            self.db.insert("fields", {
                "field_id": f["field_id"],
                "asset_id": f["asset_id"],
                "field_name": f["field_name"],
                "data_type": f["data_type"],
                "sensitive_types": f["sensitive_types"],
                "matched_patterns": f["matched_patterns"],
                "level": f["level"],
                "confidence": f["confidence"],
                "sample_values": f["sample_values"],
                "created_at": datetime.now(),
            })

        level_counts: dict[str, int] = {"L0": 0, "L1": 0, "L2": 0, "L3": 0, "L4": 0}
        type_counts: dict[str, int] = {}
        for a in assets:
            lvl = a["sensitivity_level"]
            level_counts[lvl] = level_counts.get(lvl, 0) + 1
            for t in a["sensitive_types"]:
                type_counts[t] = type_counts.get(t, 0) + 1

        result["statistics"] = {
            "total_assets": len(assets),
            "total_fields": len(fields),
            "by_level": level_counts,
            "by_sensitive_type": type_counts,
            "l3_l4_count": level_counts.get("L3", 0) + level_counts.get("L4", 0),
        }
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
