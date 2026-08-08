"""[CB-02] engine 单测：敏感数据识别 / 脱敏策略 / 合规路由 / 数据分级。

MLEngine 为纯 stdlib 实现（正则 + Luhn + 校验位），不依赖外部模型。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.cb_02.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> MLEngine:
    eng = MLEngine(config=overrides)
    eng.setup()
    return eng


# ----------------------------------------------------------------------
# 敏感数据识别
# ----------------------------------------------------------------------
def test_id_card_detected_and_masked():
    """18位身份证被识别并脱敏（前4后4保留，中间 *）。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "身份证号", "value": "11010519491231002X"}],
    })
    f = result["fields"][0]
    assert f["detections"][0]["type"] == "id_card"
    assert f["detections"][0]["valid"] is True  # 校验位合法
    assert f["sensitive_level"] == 4
    # _mask_id_card：前4 + * + 后4
    assert f["masked_value"] == "1101**********002X"
    assert f["action"] == "mask"


def test_mobile_phone_detected_and_masked():
    """手机号识别后保留前3后4。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "手机号", "value": "13812345678"}],
    })
    f = result["fields"][0]
    assert f["detections"][0]["type"] == "mobile"
    assert f["masked_value"] == "138****5678"
    assert f["sensitive_level"] == 3


def test_email_detected_and_masked():
    """邮箱脱敏保留首字符 + 域名。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "邮箱", "value": "zhangsan@example.com"}],
    })
    f = result["fields"][0]
    assert f["detections"][0]["type"] == "email"
    assert f["masked_value"] == "z***@example.com"


def test_bank_card_luhn_validated():
    """银行卡号通过 Luhn 校验才被识别（4111... 是合法测试号）。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "银行卡号", "value": "4111111111111111"}],
    })
    f = result["fields"][0]
    assert f["detections"][0]["type"] == "bank_card"
    assert f["sensitive_level"] == 4
    assert f["masked_value"].startswith("4111")
    assert f["masked_value"].endswith("1111")


def test_invalid_bank_card_not_detected():
    """不满足 Luhn 校验的数字串不被识别为银行卡。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "备注", "value": "1234567890123456"}],  # 16位但 Luhn 不通过
    })
    f = result["fields"][0]
    # 没有银行卡命中（findings 为空）
    types = {d["type"] for d in f["detections"]}
    assert "bank_card" not in types


# ----------------------------------------------------------------------
# 合规路由
# ----------------------------------------------------------------------
def test_routing_cn_to_eu_mask_then_allow():
    """CN→EU 触发 mask_then_allow，敏感字段被脱敏。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "身份证号", "value": "11010519491231002X"}],
    })
    route = result["routing_decision"]
    assert route["action"] == "mask_then_allow"
    assert route["min_mask_level"] == 3


def test_routing_cn_to_cn_allow_no_mask():
    """CN→CN 本地传输 allow，即使身份证也不脱敏。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "CN",
        "fields": [{"name": "身份证号", "value": "11010519491231002X"}],
    })
    f = result["fields"][0]
    assert result["routing_decision"]["action"] == "allow"
    assert f["action"] == "none"
    assert f["masked_value"] == "11010519491231002X"  # 原值未变


def test_routing_cn_to_global_encrypt_then_allow():
    """CN→GLOBAL 跨境加密传输，极敏感字段被 tokenize。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "GLOBAL",
        "fields": [{"name": "身份证号", "value": "11010519491231002X"}],
    })
    f = result["fields"][0]
    assert result["routing_decision"]["action"] == "encrypt_then_allow"
    assert f["action"] == "tokenize"
    assert f["masked_value"].startswith("TK-")


def test_unknown_route_denied():
    """未知法域路由默认 deny。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "XX",
        "target_jurisdiction": "YY",
        "fields": [{"name": "x", "value": "1"}],
    })
    assert result["routing_decision"]["action"] == "deny"


# ----------------------------------------------------------------------
# 字段名级别推断 / 数据分级
# ----------------------------------------------------------------------
def test_field_name_infers_level():
    """字段名含关键词时推断出敏感级别（即使值本身不含敏感数据）。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "用户密码", "value": "plaintext123"}],
    })
    f = result["fields"][0]
    # "密码" 是 L4 关键词
    assert f["sensitive_level"] == 4
    assert f["sensitive_level_name"] == "极敏感"


def test_ip_address_level_2_not_masked_for_eu():
    """IP level=2 < CN→EU 的 min_mask_level=3，不被脱敏。

    字段名避开 L3 关键词（"地址"/"address"），确保级别仅由 IP 检测决定为 2。
    """
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [{"name": "节点", "value": "192.168.1.1"}],
    })
    f = result["fields"][0]
    assert f["detections"][0]["type"] == "ip_address"
    assert f["sensitive_level"] == 2
    # 2 < 3，走 "不脱敏" 分支
    assert f["action"] == "none"
    assert f["masked_value"] == "192.168.1.1"


# ----------------------------------------------------------------------
# 空输入 / 边界
# ----------------------------------------------------------------------
def test_empty_fields():
    """空字段列表返回空结果，summary.total_fields=0。"""
    eng = _make_engine()
    result = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
        "fields": [],
    })
    assert result["fields"] == []
    assert result["summary"]["total_fields"] == 0


def test_non_dict_input_wrapped_as_data():
    """非 dict 输入被包装为 {"data": input}，默认法域 LOCAL。"""
    eng = _make_engine()
    result = eng.execute(["some text", "another"])
    # 列表被转为 fields
    assert len(result["fields"]) == 2
    # LOCAL 路由不在 rules，回退 deny
    assert result["routing_decision"]["action"] == "deny"


def test_data_dict_format_accepted():
    """data 字典格式自动转为 fields（key 作为 name）。"""
    eng = _make_engine()
    result = eng.execute({
        "data": {"手机": "13812345678"},
        "source_jurisdiction": "CN",
        "target_jurisdiction": "EU",
    })
    assert len(result["fields"]) == 1
    assert result["fields"][0]["field_name"] == "手机"


# ----------------------------------------------------------------------
# 汇总统计 / 输出标记
# ----------------------------------------------------------------------
def test_summary_statistics_with_sample():
    """sample_input 端到端：summary 含分级分布、动作分布、法域名。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["module"] == "CB-02"
    assert s["family"] == "ml_nlp"
    assert s["total_fields"] == 6
    assert s["total_detections"] >= 5  # 至少识别出 5 类敏感数据
    assert s["routing_decision"] == "mask_then_allow"
    assert s["source_jurisdiction_name"] == "中国"
    assert s["target_jurisdiction_name"] == "欧盟"
    # by_level 的 key 是中文级别名
    assert "极敏感" in s["by_level"]
    assert s["by_action"]["mask"] >= 1


def test_reproducible_tokenization():
    """相同输入 + 相同 salt → 相同 token（tokenize 一致性）。"""
    eng = _make_engine()
    r1 = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "GLOBAL",
        "fields": [{"name": "身份证号", "value": "11010519491231002X"}],
    })
    r2 = eng.execute({
        "source_jurisdiction": "CN",
        "target_jurisdiction": "GLOBAL",
        "fields": [{"name": "身份证号", "value": "11010519491231002X"}],
    })
    assert r1["fields"][0]["masked_value"] == r2["fields"][0]["masked_value"]
