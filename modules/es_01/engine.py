"""[cv] ES-01 ESG多源数据智能采集平台。

纯 stdlib 实现的多源数据智能采集引擎：
  - _load_model  : 加载内置数据解析器注册中心 + ESG指标标准库（GRI/SASB/ISSB）+ 单位映射表
  - _preprocess  : 输入多源原始数据（结构化/半结构化/非结构化/时序/栅格），分派到对应解析器
  - _infer       : 多模态数据解析 → 指标标准化 → 多源融合 → 质量评分
  - _postprocess : 输出标准化ESG指标 + 数据质量报告 + 采集日志
"""
from __future__ import annotations

import hashlib
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime

from modules.shared.base_engine import AbstractEngine


_UNIT_CONVERSIONS = {
    "tCO2": {"kg": 1000.0, "g": 1_000_000.0, "吨": 1.0, "千克": 0.001, "克": 0.000001},
    "kWh": {"MWh": 0.001, "Wh": 1000.0, "千瓦时": 1.0, "兆千瓦时": 0.001, "瓦时": 1000.0},
    "MJ": {"GJ": 0.001, "kJ": 1000.0, "兆焦": 1.0, "吉焦": 0.001, "千焦": 1000.0},
    "m3": {"立方米": 1.0, "升": 1000.0, "L": 1000.0},
    "ha": {"公顷": 1.0, "m2": 10000.0, "平方米": 10000.0},
}

_GRI_METRICS = {
    "GHG_Emissions": {"name": "温室气体排放", "unit": "tCO2", "dimension": "E", "subcategory": "气候"},
    "Energy_Consumption": {"name": "能源消耗", "unit": "MJ", "dimension": "E", "subcategory": "能源"},
    "Water_Intensity": {"name": "用水强度", "unit": "m3", "dimension": "E", "subcategory": "水"},
    "Waste_Generated": {"name": "废弃物产生", "unit": "tCO2", "dimension": "E", "subcategory": "废弃物"},
    "Employee_Turnover": {"name": "员工流失率", "unit": "%", "dimension": "S", "subcategory": "劳工"},
    "Diversity_Ratio": {"name": "多元化比例", "unit": "%", "dimension": "S", "subcategory": "多元化"},
    "Board_Independence": {"name": "董事会独立性", "unit": "%", "dimension": "G", "subcategory": "治理"},
    "Anti_Corruption": {"name": "反腐败", "unit": "分", "dimension": "G", "subcategory": "合规"},
}

_SOURCE_WEIGHTS = {
    "政府平台": 1.0, "IoT传感器": 1.0, "第三方评级": 0.95,
    "企业年报": 0.85, "企业ESG报告": 0.80, "新闻媒体": 0.55,
    "社交媒体": 0.40, "内部系统": 0.70, "行业数据": 0.75,
}


class CVEngine(AbstractEngine):
    """ES-01 多源数据智能采集引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.parsers = {}
        self.metric_schema = _GRI_METRICS
        self.unit_map = _UNIT_CONVERSIONS
        self.source_weights = _SOURCE_WEIGHTS

    def _load_model(self):
        self.parsers = {
            "structured": self._parse_structured,
            "semi_structured": self._parse_semi_structured,
            "text": self._parse_text,
            "time_series": self._parse_timeseries,
            "image_meta": self._parse_image_meta,
        }
        self.metric_schema = dict(_GRI_METRICS)
        self.unit_map = dict(_UNIT_CONVERSIONS)
        self.source_weights = dict(_SOURCE_WEIGHTS)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        now = datetime.now()
        parsed_inputs = []
        for it in items:
            dtype = it.get("data_type", "structured")
            source = it.get("source", "未知")
            metric_key = it.get("metric_key") or self._guess_metric(it.get("content", it))
            parsed_inputs.append({
                "source": source,
                "source_weight": self.source_weights.get(source, 0.6),
                "data_type": dtype,
                "content": it.get("content", it),
                "metric_key": metric_key,
                "timestamp": it.get("timestamp", now.isoformat()),
                "period": it.get("period", "年度"),
                "entity": it.get("entity", ""),
                "raw_unit": it.get("unit", ""),
            })
        return {"inputs": parsed_inputs, "schema": self.metric_schema}

    def _infer(self, prepared):
        records = []
        errors = []
        for inp in prepared["inputs"]:
            dtype = inp["data_type"]
            parser = self.parsers.get(dtype, self._parse_structured)
            try:
                vals = parser(inp["content"])
            except Exception as exc:
                errors.append({"source": inp["source"], "error": str(exc), "metric": inp["metric_key"]})
                vals = []
            metric_def = self.metric_schema.get(inp["metric_key"], {})
            target_unit = metric_def.get("unit", inp["raw_unit"])
            for val in vals:
                std_val = self._normalize_unit(val["value"], val.get("unit", inp["raw_unit"]), target_unit)
                records.append({
                    "metric_key": inp["metric_key"],
                    "metric_name": metric_def.get("name", inp["metric_key"]),
                    "dimension": metric_def.get("dimension", "E"),
                    "subcategory": metric_def.get("subcategory", ""),
                    "value": std_val,
                    "unit": target_unit,
                    "raw_value": val["value"],
                    "raw_unit": val.get("unit", inp["raw_unit"]),
                    "source": inp["source"],
                    "source_weight": inp["source_weight"],
                    "entity": inp["entity"],
                    "period": inp["period"],
                    "timestamp": inp["timestamp"],
                    "data_id": hashlib.md5(f"{inp['metric_key']}|{inp['source']}|{inp['timestamp']}|{std_val}".encode()).hexdigest()[:12],
                })
        merged = self._merge_by_metric(records)
        quality = self._quality_assessment(records, merged)
        return {
            "records": records,
            "merged_metrics": merged,
            "quality_report": quality,
            "errors": errors,
        }

    def _parse_structured(self, content):
        if isinstance(content, dict):
            out = []
            for k, v in content.items():
                if isinstance(v, (int, float)):
                    out.append({"key": k, "value": float(v), "unit": ""})
                elif isinstance(v, dict):
                    if "value" in v:
                        out.append({"key": k, "value": float(v["value"]), "unit": v.get("unit", "")})
            return out
        if isinstance(content, list):
            return [{"key": f"item_{i}", "value": float(item["value"]) if isinstance(item, dict) and "value" in item else float(item), "unit": item.get("unit", "") if isinstance(item, dict) else ""} for i, item in enumerate(content)]
        return [{"key": "value", "value": float(content), "unit": ""}]

    def _parse_semi_structured(self, content):
        if isinstance(content, str):
            nums = re.findall(r"([\d.]+)\s*(tCO2e?|吨|kg|千瓦时|MWh|GJ|m3|ha|%)", content, re.IGNORECASE)
            if nums:
                return [{"key": "extracted", "value": float(n[0]), "unit": n[1]} for n in nums]
            just_nums = re.findall(r"([\d.]+)", content)
            return [{"key": "extracted", "value": float(n), "unit": ""} for n in just_nums[:5]]
        return self._parse_structured(content)

    def _parse_text(self, content):
        if not isinstance(content, str):
            content = str(content)
        patterns = [
            r"([\d.,]+)\s*(?:吨|tCO2|千克|kg).{0,8}(?:排放|温室|CO2)",
            r"(?:能耗|能源消耗)[^0-9]{0,10}([\d.,]+)\s*(?:MJ|GJ|kWh|千瓦时)",
            r"(?:用水|取水量)[^0-9]{0,10}([\d.,]+)\s*(?:m3|立方米|吨)",
            r"(?:覆盖率|比例|占比)[^0-9]{0,10}([\d.,]+)\s*%",
        ]
        results = []
        for pat in patterns:
            matches = re.findall(pat, content, re.IGNORECASE)
            for m in matches:
                clean = m.replace(",", "")
                try:
                    results.append({"key": "text_extract", "value": float(clean), "unit": ""})
                except ValueError:
                    pass
        return results if results else self._parse_semi_structured(content)

    def _parse_timeseries(self, content):
        if isinstance(content, list):
            return [{"key": f"ts_{i}", "value": float(c.get("value", c.get("v", 0))) if isinstance(c, dict) else float(c),
                     "unit": c.get("unit", "") if isinstance(c, dict) else ""}
                    for i, c in enumerate(content)]
        return self._parse_structured(content)

    def _parse_image_meta(self, content):
        if isinstance(content, dict):
            if "ndvi" in content:
                return [{"key": "NDVI", "value": float(content["ndvi"]), "unit": ""}]
            if "area_ha" in content:
                return [{"key": "area", "value": float(content["area_ha"]), "unit": "ha"}]
            if "land_use" in content:
                lu = content["land_use"]
                if isinstance(lu, dict):
                    return [{"key": f"lu_{k}", "value": float(v), "unit": "ha"} for k, v in lu.items()]
        return []

    def _guess_metric(self, content) -> str:
        text = str(content).lower()
        mapping = [
            (["co2", "碳排放", "温室气体", "ghg"], "GHG_Emissions"),
            (["能耗", "能源", "energy", "电耗"], "Energy_Consumption"),
            (["用水", "water", "取水量"], "Water_Intensity"),
            (["废弃物", "waste", "固废"], "Waste_Generated"),
            (["流失", "turnover", "员工变动"], "Employee_Turnover"),
            (["多元化", "diversity", "性别比例"], "Diversity_Ratio"),
            (["董事会", "board", "独立董事"], "Board_Independence"),
            (["反腐败", "反舞弊", "corruption"], "Anti_Corruption"),
        ]
        for keywords, key in mapping:
            for kw in keywords:
                if kw in text:
                    return key
        return "GHG_Emissions"

    def _normalize_unit(self, value, from_unit: str, to_unit: str):
        if not value or from_unit == to_unit or not from_unit or not to_unit:
            return value
        for std_unit, conversions in self.unit_map.items():
            if to_unit in conversions or to_unit == std_unit:
                target_base = std_unit
            if from_unit in conversions or from_unit == std_unit:
                source_base = std_unit
                factor = conversions.get(from_unit, 1.0)
                base_val = value * factor
                if to_unit == std_unit:
                    return base_val
                if to_unit in conversions:
                    return base_val / conversions[to_unit]
                return base_val
        return value

    def _merge_by_metric(self, records):
        grouped = defaultdict(list)
        for r in records:
            grouped[r["metric_key"]].append(r)
        merged = []
        for mkey, items in grouped.items():
            weights = [i["source_weight"] for i in items]
            values = [i["value"] for i in items]
            if values:
                avg = sum(v * w for v, w in zip(values, weights)) / sum(weights)
                stdev = statistics.stdev(values) if len(values) > 1 else 0.0
                cv = stdev / abs(avg) if avg != 0 else 0.0
            else:
                avg, stdev, cv = 0, 0, 0
            merged.append({
                "metric_key": mkey,
                "metric_name": items[0]["metric_name"],
                "dimension": items[0]["dimension"],
                "subcategory": items[0]["subcategory"],
                "unit": items[0]["unit"],
                "consolidated_value": round(avg, 4),
                "source_count": len(items),
                "source_list": sorted(set(i["source"] for i in items)),
                "range": [round(min(values), 4), round(max(values), 4)] if values else [0, 0],
                "std_dev": round(stdev, 4),
                "cv": round(cv, 4),
                "confidence": round(self._source_confidence(items, cv), 3),
            })
        return merged

    def _source_confidence(self, items, cv) -> float:
        avg_w = statistics.mean([i["source_weight"] for i in items]) if items else 0.5
        diversity_penalty = 1.0 - cv * 0.5
        coverage_bonus = min(1.0, len(items) / 3.0) * 0.15
        return min(1.0, max(0.0, avg_w * diversity_penalty + coverage_bonus))

    def _quality_assessment(self, records, merged):
        if not records:
            return {"coverage": 0, "accuracy": 0, "completeness": 0, "overall": 0, "issues": ["无数据"]}
        source_count = len(set(r["source"] for r in records))
        metric_count = len(set(r["metric_key"] for r in records))
        schema_coverage = metric_count / max(1, len(self.metric_schema))
        accuracy = statistics.mean([m["confidence"] for m in merged]) if merged else 0.0
        completeness = min(1.0, metric_count / max(1, len(self.metric_schema)) * 1.5)
        issues = []
        for m in merged:
            if m["cv"] > 0.3:
                issues.append(f"{m['metric_name']}: 数据离散度高(CV={m['cv']:.2f})，建议人工复核")
            if m["confidence"] < 0.6:
                issues.append(f"{m['metric_name']}: 数据源可信度偏低，建议补充权威来源")
        return {
            "source_count": source_count,
            "metric_count": metric_count,
            "coverage": round(schema_coverage, 3),
            "accuracy": round(accuracy, 3),
            "completeness": round(completeness, 3),
            "overall": round(0.4 * schema_coverage + 0.35 * accuracy + 0.25 * completeness, 3),
            "issues": issues,
        }

    def _postprocess(self, result):
        dim_summary = defaultdict(lambda: {"count": 0, "metrics": []})
        for m in result["merged_metrics"]:
            dim = m["dimension"]
            dim_summary[dim]["count"] += 1
            dim_summary[dim]["metrics"].append(m["metric_key"])
        return {
            "data_catalog": result["merged_metrics"],
            "dimension_summary": dict(dim_summary),
            "quality_report": result["quality_report"],
            "collection_log": {
                "total_records": len(result["records"]),
                "errors": result["errors"],
                "generated_at": datetime.now().isoformat(),
            },
        }
