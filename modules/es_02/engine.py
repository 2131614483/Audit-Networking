"""[ES-02] AI 碳排放自动核算引擎 —— 排放因子法（纯 stdlib）。

覆盖方案文档中的碳排放自动核算：
  * Scope 1（直接排放）：固定燃烧 + 移动燃烧 + 逸散排放
  * Scope 2（间接排放-电力）：外购电力 + 外购热力
  * Scope 3（其他间接排放）：商务差旅 + 员工通勤 + 供应链
  * 核算公式：E = AD × EF × GWP
    - AD (Activity Data): 活动水平数据（消耗量）
    - EF (Emission Factor): 排放因子
    - GWP (Global Warming Potential): 全球变暖潜势（CO₂=1, CH₄=28, N₂O=265）

模型结构（self.model）：
  {
    "emission_factors": {activity_type: {gas: ef}},
    "gwp": {"CO2": 1, "CH4": 28, "N2O": 265},
    "scope_mapping": {activity_type: scope},
  }

排放因子来源：IPCC 国家温室气体清单指南（2006）+ 企业温室气体核算标准（GHG Protocol）。
"""
from __future__ import annotations

from typing import Any

from modules.shared.base_engine import AbstractEngine


class MLEngine(AbstractEngine):
    """碳排放自动核算引擎（排放因子法，纯 stdlib）。"""

    def _load_model(self) -> None:
        """加载排放因子库 + GWP 系数 + 范围映射。"""
        self.model = {
            # 排放因子：EF[活动类型][气体] = kg排放/单位活动量
            "emission_factors": {
                # Scope 1: 固定燃烧（天然气、柴油、煤炭）
                "natural_gas":     {"CO2": 2.162, "CH4": 0.001, "N2O": 0.0001},   # kg/m³
                "diesel":          {"CO2": 2.730, "CH4": 0.003, "N2O": 0.0006},   # kg/L
                "coal":            {"CO2": 1.900, "CH4": 0.001, "N2O": 0.0015},   # kg/kg
                # Scope 1: 移动燃烧（汽油）
                "gasoline":        {"CO2": 2.350, "CH4": 0.002, "N2O": 0.0008},   # kg/L
                # Scope 1: 逸散（制冷剂 R410A）
                "refrigerant_r410a": {"CO2": 0, "CH4": 0, "N2O": 0, "HFC": 2088}, # GWP 直接计入
                # Scope 2: 外购电力
                "electricity":     {"CO2": 0.581, "CH4": 0, "N2O": 0},            # kg/kWh（华东电网平均）
                # Scope 2: 外购热力
                "steam":           {"CO2": 0.110, "CH4": 0, "N2O": 0},            # kg/MJ
                # Scope 3: 商务差旅（航空）
                "air_travel":      {"CO2": 0.255, "CH4": 0, "N2O": 0},            # kg/passenger-km
                # Scope 3: 员工通勤（公交）
                "commute_bus":     {"CO2": 0.045, "CH4": 0, "N2O": 0},            # kg/passenger-km
            },
            # GWP 系数（AR5, 100年）
            "gwp": {"CO2": 1, "CH4": 28, "N2O": 265, "HFC": 2088},
            # 活动类型 → 范围映射
            "scope_mapping": {
                "natural_gas": "Scope 1", "diesel": "Scope 1", "coal": "Scope 1",
                "gasoline": "Scope 1", "refrigerant_r410a": "Scope 1",
                "electricity": "Scope 2", "steam": "Scope 2",
                "air_travel": "Scope 3", "commute_bus": "Scope 3",
            },
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取活动数据列表（懒加载模型）。"""
        if self.model is None:
            self._load_model()
        if isinstance(input_data, dict) and "activities" in input_data:
            return input_data["activities"]
        return input_data if isinstance(input_data, list) else []

    def _infer(self, prepared: Any) -> Any:
        """排放因子法核算：E = AD × EF × GWP。"""
        ef = self.model["emission_factors"]
        gwp = self.model["gwp"]
        scope_map = self.model["scope_mapping"]

        results = []
        for act in prepared:
            act_type = act.get("type", "")
            amount = act.get("amount", 0)  # 活动量（对应单位）
            factors = ef.get(act_type)
            if not factors:
                results.append({
                    "activity_id": act.get("id", "?"),
                    "type": act_type,
                    "status": "unknown_type",
                    "emission_kg": 0,
                })
                continue

            scope = scope_map.get(act_type, "Unknown")
            # 计算各气体排放量 → 转 CO₂ 当量
            total_co2e = 0.0
            gas_breakdown = {}
            for gas, factor in factors.items():
                if factor == 0:
                    continue
                gas_emission = amount * factor  # kg
                co2e = gas_emission * gwp.get(gas, 1)
                gas_breakdown[gas] = round(co2e, 2)
                total_co2e += co2e

            results.append({
                "activity_id": act.get("id", "?"),
                "type": act_type,
                "scope": scope,
                "amount": amount,
                "unit": act.get("unit", ""),
                "emission_kg": round(total_co2e, 2),
                "emission_tons": round(total_co2e / 1000, 4),
                "gas_breakdown": gas_breakdown,
            })
        return results

    def _postprocess(self, result: Any) -> Any:
        """按 Scope 汇总 + 总排放量。"""
        scope_totals = {"Scope 1": 0, "Scope 2": 0, "Scope 3": 0, "Unknown": 0}
        for r in result:
            scope = r.get("scope", "Unknown")
            scope_totals[scope] = scope_totals.get(scope, 0) + r["emission_kg"]

        total_kg = sum(scope_totals.values())
        summary = {
            "total_emission_kg": round(total_kg, 2),
            "total_emission_tons": round(total_kg / 1000, 4),
            "scope_1_tons": round(scope_totals["Scope 1"] / 1000, 4),
            "scope_2_tons": round(scope_totals["Scope 2"] / 1000, 4),
            "scope_3_tons": round(scope_totals["Scope 3"] / 1000, 4),
            "activity_count": len(result),
        }
        return {"activities": result, "summary": summary}
