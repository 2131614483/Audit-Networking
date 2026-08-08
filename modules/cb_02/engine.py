"""[CB-02] 数据脱敏网关 + 合规路由核心引擎 —— 纯 stdlib 敏感识别 + 脱敏。

算法设计（中心化公用辐射：不引入任何第三方依赖）：

  * 正则敏感数据识别（模式匹配 + 边界校验）：
      - 身份证号（中国18位/15位，含校验位验证）
      - 手机号（中国11位）、固定电话
      - 邮箱地址
      - 银行卡号（Luhn算法校验）
      - 护照号、社保号、IP地址
      - 支持中英文姓名、地址关键词识别
  * 脱敏方法（6 种策略）：
      - mask   遮蔽：保留前 N 后 M，中间用 *（如 138****1234）
      - replace 替换：用占位符（如 张** 或 [REDACTED]）
      - generalize 泛化：降精度（如 35→30-40岁，北京→华北）
      - perturb 扰乱：数值加小噪声（金额 ±1%）
      - encrypt 加密：Fernet 对称加密（stdlib 用 base64+hashlib 模拟）
      - tokenize 令牌化：生成一致性 hash token
  * 数据分级（L1公开 ~ L4极敏感）：
      - 根据字段类型 + 上下文关键词自动分级
  * 合规路由：
      - 源法域 → 目标法域合规检查
      - 输出 allow / deny / mask_then_allow / encrypt_then_allow

模型结构（self.model）：
  {
    "patterns": {敏感类型: {"regex": ..., "strategy": ..., "level": ...}},
    "jurisdiction_rules": {(src, dst): {"action", "min_mask_level", ...}},
    "field_classifier": {字段关键词: (类型, 级别)},
  }
"""
from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime
from typing import Any

from modules.shared.base_engine import AbstractEngine


# ------------------------------------------------------------------
# 敏感数据识别模式（正则 + 边界）
# ------------------------------------------------------------------

_ID_CARD_18 = re.compile(r"(?<!\d)(\d{6})(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(\d{3})([\dXx])(?!\d)")
_ID_CARD_15 = re.compile(r"(?<!\d)(\d{6})(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(\d{3})(?!\d)")
_MOBILE_CN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_TEL_CN = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_BANK_CARD = re.compile(r"(?<!\d)(\d{15,19})(?!\d)")
_PASSPORT = re.compile(r"(?<![A-Za-z0-9])([GDEPfgdep]\d{8}|[A-Z]\d{7,8})(?![A-Za-z0-9])")
_IPV4 = re.compile(r"(?<!\d)((?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?!\d)")

_NAME_ZH = re.compile(r"[\u4e00-\u9fff]{2,4}(?:[\u4e00-\u9fff]{0,2}(?:·|·)[\u4e00-\u9fff]{2,4})?")
_ADDRESS_KEYWORDS = (
    "省", "市", "区", "县", "镇", "乡", "街道", "路", "街", "号", "栋", "单元", "室",
    "road", "street", "avenue", "blvd", "ave", "suite",
)


def _luhn_check(num_str: str) -> bool:
    """Luhn 算法校验银行卡号。"""
    if not num_str.isdigit():
        return False
    total = 0
    reverse = num_str[::-1]
    for i, c in enumerate(reverse):
        n = int(c)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _is_valid_id18(id18: str) -> bool:
    """中国身份证 18 位校验位验证。"""
    if len(id18) != 18:
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_map = "10X98765432"
    try:
        s = sum(int(id18[i]) * weights[i] for i in range(17))
        expected = check_map[s % 11]
        return id18[17].upper() == expected
    except (ValueError, IndexError):
        return False


# ------------------------------------------------------------------
# 脱敏策略实现
# ------------------------------------------------------------------

def _mask(value: str, keep_head: int = 2, keep_tail: int = 2, char: str = "*") -> str:
    s = str(value)
    if len(s) <= keep_head + keep_tail:
        return char * len(s)
    return s[:keep_head] + char * (len(s) - keep_head - keep_tail) + s[-keep_tail:]


def _mask_email(email: str) -> str:
    if "@" not in email:
        return "[EMAIL]"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"*@{domain}"
    return local[0] + "***" + "@" + domain


def _mask_id_card(id_str: str) -> str:
    s = str(id_str)
    if len(s) >= 8:
        return s[:4] + "*" * (len(s) - 8) + s[-4:]
    return "*" * len(s)


def _mask_bank_card(card: str) -> str:
    s = str(card)
    if len(s) >= 10:
        return s[:4] + " **** **** " + s[-4:]
    return "*" * len(s)


def _generalize_age(val: Any) -> str:
    try:
        age = int(float(str(val).strip()))
    except (ValueError, TypeError):
        return "[AGE_RANGE]"
    low = (age // 10) * 10
    return f"{low}-{low + 9}岁"


def _perturb_amount(val: Any, ratio: float = 0.01, rng: random.Random | None = None) -> float:
    rng = rng or random.Random(42)
    try:
        amt = float(str(val).replace(",", "").replace("，", "").strip())
    except (ValueError, TypeError):
        return 0.0
    delta = amt * ratio * (rng.random() * 2 - 1)
    return round(amt + delta, 2)


def _tokenize(value: str, salt: str = "cb02-salt") -> str:
    h = hashlib.sha256((salt + str(value)).encode("utf-8")).hexdigest()
    return f"TK-{h[:16].upper()}"


# ------------------------------------------------------------------
# 合规路由规则
# ------------------------------------------------------------------

_JURISDICTION_RULES: dict[tuple[str, str], dict[str, Any]] = {
    ("CN", "CN"): {"action": "allow", "min_mask_level": 0, "desc": "本地传输，按内部规则"},
    ("CN", "EU"): {"action": "mask_then_allow", "min_mask_level": 3, "desc": "GDPR充分性+数据出境评估"},
    ("CN", "US"): {"action": "mask_then_allow", "min_mask_level": 3, "desc": "CCPA合规检查"},
    ("CN", "SG"): {"action": "mask_then_allow", "min_mask_level": 2, "desc": "新加坡PDPA合规"},
    ("CN", "GLOBAL"): {"action": "encrypt_then_allow", "min_mask_level": 4, "desc": "跨境加密传输"},
    ("EU", "EU"): {"action": "allow", "min_mask_level": 0, "desc": "GDPR内部流动"},
    ("EU", "CN"): {"action": "mask_then_allow", "min_mask_level": 3, "desc": "标准合同条款(SCC)"},
    ("EU", "US"): {"action": "mask_then_allow", "min_mask_level": 3, "desc": "数据隐私框架(DPF)"},
    ("US", "US"): {"action": "allow", "min_mask_level": 0, "desc": "本地传输"},
    ("US", "CN"): {"action": "mask_then_allow", "min_mask_level": 3, "desc": "CCPA境外传输规则"},
    ("GLOBAL", "GLOBAL"): {"action": "encrypt_then_allow", "min_mask_level": 4, "desc": "全球加密传输"},
}


_JURISDICTION_NAMES = {
    "CN": "中国", "EU": "欧盟", "US": "美国",
    "SG": "新加坡", "HK": "香港", "JP": "日本",
    "GLOBAL": "全球/未知",
}


class MLEngine(AbstractEngine):
    """数据脱敏网关 + 合规路由引擎（纯 stdlib）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改：预处理 → 推理 → 后处理。
    """

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载敏感识别模式库 + 脱敏策略映射 + 合规路由规则。"""
        self.model = {
            "patterns": {
                "id_card":      {"regex": _ID_CARD_18, "regex2": _ID_CARD_15, "strategy": "mask_id", "level": 4},
                "mobile":       {"regex": _MOBILE_CN, "strategy": "mask_mobile", "level": 3},
                "telephone":    {"regex": _TEL_CN, "strategy": "mask_telephone", "level": 2},
                "email":        {"regex": _EMAIL, "strategy": "mask_email", "level": 3},
                "bank_card":    {"regex": _BANK_CARD, "strategy": "mask_bank", "level": 4},
                "passport":     {"regex": _PASSPORT, "strategy": "mask_passport", "level": 4},
                "ip_address":   {"regex": _IPV4, "strategy": "replace", "level": 2},
            },
            "level_names": {1: "公开", 2: "内部", 3: "敏感", 4: "极敏感"},
            "jurisdiction_rules": dict(_JURISDICTION_RULES),
            "jurisdiction_names": dict(_JURISDICTION_NAMES),
        }

    # ------------------------------------------------------------------
    # 预处理：提取字段/文本 + 确定传输场景
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """将输入标准化为统一格式。

        input_data 格式：
          {
            "data": {"field_name": value, ...} 或 [text, ...],
            "source_jurisdiction": "CN",
            "target_jurisdiction": "EU",
            "fields": [{"name": "姓名", "value": "张三"}, ...],
          }
        """
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            input_data = {"data": input_data}

        source = (input_data.get("source_jurisdiction") or input_data.get("source") or "LOCAL").upper()
        target = (input_data.get("target_jurisdiction") or input_data.get("target") or "LOCAL").upper()

        fields_raw = input_data.get("fields")
        if fields_raw is None:
            data = input_data.get("data", {})
            if isinstance(data, dict):
                fields_raw = [{"name": str(k), "value": v} for k, v in data.items()]
            elif isinstance(data, list):
                fields_raw = [{"name": f"text_{i}", "value": v} for i, v in enumerate(data)]
            else:
                fields_raw = [{"name": "text", "value": data}]

        fields = []
        for f in fields_raw:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name", f.get("field", ""))).strip()
            value = f.get("value")
            if value is None:
                value = f.get("content", "")
            fields.append({"name": name, "value": value})

        return {
            "source_jurisdiction": source,
            "target_jurisdiction": target,
            "fields": fields,
            "scenario": input_data.get("scenario", "cross_border"),
        }

    # ------------------------------------------------------------------
    # 推理：敏感识别 → 分级 → 脱敏 → 合规路由
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """对每个字段执行：敏感识别 → 分级 → 脱敏策略选择 → 脱敏执行。"""
        patterns = self.model["patterns"]
        src = prepared["source_jurisdiction"]
        dst = prepared["target_jurisdiction"]
        route_rule = self._resolve_route(src, dst)

        results = []
        total_findings = 0
        for field in prepared["fields"]:
            name = field["name"]
            value = field["value"]
            text = str(value) if value is not None else ""

            findings = self._detect_sensitive(text, patterns)
            field_level = max([f["level"] for f in findings], default=0)
            field_level = max(field_level, self._field_name_level(name))
            total_findings += len(findings)

            # 执行脱敏（仅当路由要求脱敏时）
            if route_rule["action"] == "allow" or field_level < route_rule.get("min_mask_level", 0):
                masked_value = text
                applied = "none"
            elif route_rule["action"] == "encrypt_then_allow":
                masked_value = _tokenize(text, salt=f"cb02-encrypt-{name}")
                applied = "tokenize"
            else:
                masked_value = self._apply_masking(text, findings)
                applied = "mask" if findings else "none"

            results.append({
                "field_name": name,
                "original_value": text,
                "masked_value": masked_value,
                "detections": findings,
                "sensitive_level": field_level,
                "sensitive_level_name": self.model["level_names"].get(field_level, "未知"),
                "action": applied,
            })

        return {
            "source_jurisdiction": src,
            "target_jurisdiction": dst,
            "routing_decision": route_rule,
            "fields": results,
            "total_detections": total_findings,
        }

    # ------------------------------------------------------------------
    # 后处理：汇总统计 + 合规报告
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """生成脱敏统计 + 合规路由报告。"""
        fields = result.get("fields", [])

        by_level: dict[int, int] = {}
        by_action: dict[str, int] = {}
        for f in fields:
            lvl = f.get("sensitive_level", 0)
            by_level[lvl] = by_level.get(lvl, 0) + 1
            act = f.get("action", "none")
            by_action[act] = by_action.get(act, 0) + 1

        route = result.get("routing_decision", {})
        src = result.get("source_jurisdiction", "")
        dst = result.get("target_jurisdiction", "")

        result["summary"] = {
            "module": "CB-02",
            "family": "ml_nlp",
            "routing_decision": route.get("action", "unknown"),
            "routing_desc": route.get("desc", ""),
            "source_jurisdiction_name": self.model["jurisdiction_names"].get(src, src),
            "target_jurisdiction_name": self.model["jurisdiction_names"].get(dst, dst),
            "total_fields": len(fields),
            "total_sensitive_fields": sum(1 for f in fields if f.get("sensitive_level", 0) >= 2),
            "total_detections": result.get("total_detections", 0),
            "by_level": {
                self.model["level_names"].get(k, str(k)): v
                for k, v in sorted(by_level.items())
            },
            "by_action": by_action,
            "generated_at": datetime.now().isoformat(),
        }
        return result

    # ------------------------------------------------------------------
    # 内部：敏感识别
    # ------------------------------------------------------------------
    def _detect_sensitive(self, text: str, patterns: dict) -> list[dict]:
        """对文本执行所有敏感模式匹配，返回检测结果列表。"""
        findings: list[dict] = []
        if not text:
            return findings

        # 身份证（18位优先）
        for m in _ID_CARD_18.finditer(text):
            id_val = m.group(0)
            valid = _is_valid_id18(id_val)
            findings.append({
                "type": "id_card", "value": id_val, "level": 4,
                "strategy": "mask_id", "valid": valid, "position": m.start(),
            })
        for m in _ID_CARD_15.finditer(text):
            findings.append({
                "type": "id_card_15", "value": m.group(0), "level": 4,
                "strategy": "mask_id", "valid": True, "position": m.start(),
            })

        # 手机号
        for m in _MOBILE_CN.finditer(text):
            findings.append({
                "type": "mobile", "value": m.group(0), "level": 3,
                "strategy": "mask_mobile", "position": m.start(),
            })

        # 邮箱
        for m in _EMAIL.finditer(text):
            findings.append({
                "type": "email", "value": m.group(0), "level": 3,
                "strategy": "mask_email", "position": m.start(),
            })

        # 银行卡号（Luhn 校验）
        for m in _BANK_CARD.finditer(text):
            card = m.group(0)
            if 13 <= len(card) <= 19 and _luhn_check(card):
                findings.append({
                    "type": "bank_card", "value": card, "level": 4,
                    "strategy": "mask_bank", "position": m.start(),
                })

        # 护照
        for m in _PASSPORT.finditer(text):
            findings.append({
                "type": "passport", "value": m.group(0), "level": 4,
                "strategy": "mask_passport", "position": m.start(),
            })

        # IP 地址
        for m in _IPV4.finditer(text):
            findings.append({
                "type": "ip_address", "value": m.group(0), "level": 2,
                "strategy": "replace", "position": m.start(),
            })

        # 固定电话
        for m in _TEL_CN.finditer(text):
            findings.append({
                "type": "telephone", "value": m.group(0), "level": 2,
                "strategy": "mask_telephone", "position": m.start(),
            })

        # 去重（按 position 优先保留 level 高的）
        findings.sort(key=lambda f: (f["position"], -f["level"]))
        deduped: list[dict] = []
        last_end = -1
        for f in findings:
            if f["position"] >= last_end:
                deduped.append(f)
                last_end = f["position"] + len(f["value"])
        return deduped

    def _field_name_level(self, name: str) -> int:
        """根据字段名关键词推测敏感级别。"""
        n = name.lower()
        lvl = 0
        l4_keywords = ("身份证", "护照", "银行卡", "账号", "密码", "密钥", "secret", "password", "key", "api_key")
        l3_keywords = ("手机", "电话", "邮箱", "email", "phone", "mobile", "地址", "address", "name", "姓名")
        l2_keywords = ("ip", "ip地址", "设备号", "device", "mac")
        for kw in l4_keywords:
            if kw in n:
                lvl = max(lvl, 4)
        for kw in l3_keywords:
            if kw in n:
                lvl = max(lvl, 3)
        for kw in l2_keywords:
            if kw in n:
                lvl = max(lvl, 2)
        return lvl

    # ------------------------------------------------------------------
    # 内部：脱敏执行
    # ------------------------------------------------------------------
    def _apply_masking(self, text: str, findings: list[dict]) -> str:
        """按发现顺序替换原始文本中的敏感值。"""
        if not findings:
            return text
        # 从后往前替换，避免位置偏移
        sorted_f = sorted(findings, key=lambda f: f["position"], reverse=True)
        result = text
        for f in sorted_f:
            start = f["position"]
            end = start + len(f["value"])
            masked = self._mask_value(f["value"], f["type"], f["strategy"])
            result = result[:start] + masked + result[end:]
        return result

    def _mask_value(self, value: str, stype: str, strategy: str) -> str:
        if stype in ("id_card", "id_card_15"):
            return _mask_id_card(value)
        if stype == "mobile":
            return _mask(value, 3, 4)
        if stype == "telephone":
            return _mask(value, 2, 2)
        if stype == "email":
            return _mask_email(value)
        if stype == "bank_card":
            return _mask_bank_card(value)
        if stype == "passport":
            return _mask(value, 1, 2)
        if stype == "ip_address":
            return "[IP]"
        if strategy == "replace":
            return f"[{stype.upper()}]"
        return _mask(value)

    # ------------------------------------------------------------------
    # 内部：合规路由解析
    # ------------------------------------------------------------------
    def _resolve_route(self, src: str, dst: str) -> dict:
        """解析路由规则，返回合规决策。"""
        src = src.upper()
        dst = dst.upper()
        rules = self.model["jurisdiction_rules"]
        if (src, dst) in rules:
            return rules[(src, dst)]
        if (src, "GLOBAL") in rules:
            return rules[(src, "GLOBAL")]
        if ("GLOBAL", dst) in rules:
            return rules[("GLOBAL", dst)]
        return {"action": "deny", "min_mask_level": 4, "desc": f"未知路由 {src}→{dst}，默认拒绝"}
