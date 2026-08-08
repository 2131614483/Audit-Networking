"""[ES-02] engine 单测：碳排放自动核算（排放因子法 E = AD × EF × GWP）。

MLEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * Scope 1（直接排放）：固定燃烧 / 移动燃烧 / 逸散
  * Scope 2（间接排放-电力）：外购电力 / 外购热力
  * Scope 3（其他间接排放）：商务差旅 / 员工通勤
  * 核算公式：E = AD × EF × GWP，按 Scope 汇总
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.es_02.engine import MLEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> MLEngine:
    eng = MLEngine(config=overrides)
    eng.setup()
    return eng


def _act(**fields) -> dict:
    """构造单个活动数据，补默认字段。"""
    base = {"id": "T1", "type": "natural_gas", "amount": 0, "unit": ""}
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 排放因子法核算公式
# ----------------------------------------------------------------------
def test_natural_gas_emission_formula():
    """天然气：E = AD × EF × GWP，CO2/CH4/N2O 三气体累加。

    amount=100 m³：
      CO2  = 100 × 2.162 × 1   = 216.2
      CH4  = 100 × 0.001 × 28  = 2.8
      N2O  = 100 × 0.0001 × 265 = 2.65
      total = 221.65 kg
    """
    eng = _make_engine()
    result = eng.execute({"activities": [_act(id="NG1", type="natural_gas", amount=100)]})
    a = result["activities"][0]
    assert a["emission_kg"] == 221.65
    assert a["emission_tons"] == round(221.65 / 1000, 4)
    assert a["gas_breakdown"]["CO2"] == 216.2
    assert a["gas_breakdown"]["CH4"] == 2.8
    assert a["gas_breakdown"]["N2O"] == 2.65


def test_electricity_only_co2():
    """外购电力排放因子仅含 CO2，gas_breakdown 只有 CO2 一项。"""
    eng = _make_engine()
    result = eng.execute({"activities": [_act(id="EL1", type="electricity", amount=1000)]})
    a = result["activities"][0]
    # 1000 × 0.581 × 1 = 581 kg
    assert a["emission_kg"] == 581.0
    assert list(a["gas_breakdown"].keys()) == ["CO2"]
    assert a["gas_breakdown"]["CO2"] == 581.0


def test_diesel_three_gases():
    """柴油含 CO2/CH4/N2O 三气体，均在 breakdown 中。"""
    eng = _make_engine()
    result = eng.execute({"activities": [_act(id="DS1", type="diesel", amount=100)]})
    a = result["activities"][0]
    # CO2=273, CH4=100*0.003*28=8.4, N2O=100*0.0006*265=15.9
    assert a["gas_breakdown"]["CO2"] == 273.0
    assert a["gas_breakdown"]["CH4"] == 8.4
    assert a["gas_breakdown"]["N2O"] == 15.9
    assert a["emission_kg"] == round(273.0 + 8.4 + 15.9, 2)


def test_gwp_applied_to_ch4_and_n2o():
    """GWP 系数：CH4=28, N2O=265 应用于 CO2 当量换算。"""
    eng = _make_engine()
    # 用一个 CH4 主导的场景验证 GWP
    result = eng.execute({"activities": [_act(id="G1", type="natural_gas", amount=10000)]})
    a = result["activities"][0]
    # CH4 = 10000 × 0.001 × 28 = 280
    assert a["gas_breakdown"]["CH4"] == 280.0
    # N2O = 10000 × 0.0001 × 265 = 265
    assert a["gas_breakdown"]["N2O"] == 265.0


# ----------------------------------------------------------------------
# Scope 分类
# ----------------------------------------------------------------------
def test_scope_classification():
    """各活动类型被分到正确的 Scope。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    by_id = {a["activity_id"]: a for a in result["activities"]}
    assert by_id["A001"]["scope"] == "Scope 1"  # natural_gas
    assert by_id["A003"]["scope"] == "Scope 1"  # diesel
    assert by_id["A005"]["scope"] == "Scope 1"  # coal
    assert by_id["A006"]["scope"] == "Scope 1"  # gasoline
    assert by_id["A002"]["scope"] == "Scope 2"  # electricity
    assert by_id["A007"]["scope"] == "Scope 2"  # steam
    assert by_id["A004"]["scope"] == "Scope 3"  # air_travel
    assert by_id["A008"]["scope"] == "Scope 3"  # commute_bus


def test_scope_field_in_each_activity():
    """每个已识别活动都带 scope 字段。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    for a in result["activities"]:
        assert "scope" in a
        assert a["scope"] in {"Scope 1", "Scope 2", "Scope 3"}


# ----------------------------------------------------------------------
# 汇总统计
# ----------------------------------------------------------------------
def test_summary_totals_and_counts():
    """summary 含总排放量 + 各 Scope 分项 + 活动数。"""
    eng = _make_engine()
    result = eng.execute(_sample())
    s = result["summary"]
    assert s["activity_count"] == 8
    assert s["total_emission_kg"] > 0
    # tons = kg / 1000
    assert s["total_emission_tons"] == round(s["total_emission_kg"] / 1000, 4)
    # 各 Scope 吨数之和 ≈ 总吨数
    scope_sum = s["scope_1_tons"] + s["scope_2_tons"] + s["scope_3_tons"]
    assert abs(scope_sum - s["total_emission_tons"]) < 1e-6


def test_summary_scope_isolation():
    """Scope 1/2/3 互不串扰：纯电力的输入只累加到 Scope 2。"""
    eng = _make_engine()
    result = eng.execute({"activities": [_act(id="EL", type="electricity", amount=1000)]})
    s = result["summary"]
    assert s["scope_1_tons"] == 0.0
    assert s["scope_2_tons"] == round(581.0 / 1000, 4)
    assert s["scope_3_tons"] == 0.0


# ----------------------------------------------------------------------
# 单位 / 字段保留
# ----------------------------------------------------------------------
def test_amount_and_unit_preserved():
    """活动数据的 amount / unit 透传到结果。"""
    eng = _make_engine()
    result = eng.execute({"activities": [
        _act(id="U1", type="natural_gas", amount=123.5, unit="m³")
    ]})
    a = result["activities"][0]
    assert a["amount"] == 123.5
    assert a["unit"] == "m³"
    assert a["activity_id"] == "U1"


def test_emission_tons_is_kg_divided_by_1000():
    """emission_tons = emission_kg / 1000。"""
    eng = _make_engine()
    result = eng.execute({"activities": [_act(id="T1", type="electricity", amount=500)]})
    a = result["activities"][0]
    assert a["emission_tons"] == round(a["emission_kg"] / 1000, 4)


# ----------------------------------------------------------------------
# 边界 / 异常输入
# ----------------------------------------------------------------------
def test_unknown_activity_type():
    """未知活动类型返回 status=unknown_type 且排放为 0。"""
    eng = _make_engine()
    result = eng.execute({"activities": [
        {"id": "X1", "type": "unknown_fuel", "amount": 999}
    ]})
    a = result["activities"][0]
    assert a["status"] == "unknown_type"
    assert a["emission_kg"] == 0
    assert a["type"] == "unknown_fuel"


def test_empty_activities():
    """空 activities 列表返回空结果 + 零汇总。"""
    eng = _make_engine()
    result = eng.execute({"activities": []})
    assert result["activities"] == []
    assert result["summary"]["activity_count"] == 0
    assert result["summary"]["total_emission_kg"] == 0


def test_non_dict_non_list_input_returns_empty():
    """非 dict/list 输入回退为空列表（不崩）。"""
    eng = _make_engine()
    result = eng.execute("invalid input")
    assert result["activities"] == []
    assert result["summary"]["activity_count"] == 0


def test_list_input_accepted():
    """直接传 list 输入（无 activities 包裹）也能处理。"""
    eng = _make_engine()
    result = eng.execute([_act(id="L1", type="electricity", amount=1000)])
    assert len(result["activities"]) == 1
    assert result["activities"][0]["emission_kg"] == 581.0


def test_missing_amount_defaults_zero():
    """缺 amount 字段默认 0，排放为 0。"""
    eng = _make_engine()
    result = eng.execute({"activities": [{"id": "M1", "type": "natural_gas"}]})
    a = result["activities"][0]
    assert a["amount"] == 0
    assert a["emission_kg"] == 0


def test_missing_id_defaults_unknown():
    """无 id 的活动默认 activity_id='?'。"""
    eng = _make_engine()
    result = eng.execute({"activities": [{"type": "electricity", "amount": 100}]})
    assert result["activities"][0]["activity_id"] == "?"


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_model_has_factors_gwp_and_scope_mapping():
    """engine 加载后 model 含排放因子库 / GWP / 范围映射。"""
    eng = _make_engine()
    assert "emission_factors" in eng.model
    assert "gwp" in eng.model
    assert "scope_mapping" in eng.model
    assert eng.model["gwp"]["CO2"] == 1
    assert eng.model["gwp"]["CH4"] == 28
    assert eng.model["gwp"]["N2O"] == 265
    assert "natural_gas" in eng.model["emission_factors"]


def test_lazy_load_on_execute():
    """不调 setup() 直接 execute 也能懒加载模型。"""
    eng = MLEngine()
    result = eng.execute({"activities": [_act(type="electricity", amount=100)]})
    assert eng.model is not None
    assert len(result["activities"]) == 1
