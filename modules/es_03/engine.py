"""[cv] ES-03 卫星遥感AI环境监测。

纯 stdlib 实现的卫星遥感环境监测引擎：
  - _load_model  : 加载内置遥感指数公式库（NDVI/NIRV/NBR/NDWI/LST/NDMI）+ 土地利用分类规则 + 变化检测阈值
  - _preprocess  : 输入多时相遥感数据（波段值/合成指标），按 ROI × 时间片组织
  - _infer       : 遥感指数计算 → 土地利用分类 → 变化检测 → 异常发现 → 绿色漂洗线索
  - _postprocess : 输出环境变化报告（指数趋势 + 土地转移矩阵 + 异常区域 + 绿色漂洗验证建议）
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime

from modules.shared.base_engine import AbstractEngine


def _safe_div(a, b, default=0.0):
    if b is None or abs(b) < 1e-9:
        return default
    return a / b


_INDEX_FORMULAS = {
    "NDVI": lambda b: _safe_div(b.get("nir", 0) - b.get("red", 0), b.get("nir", 0) + b.get("red", 0)),
    "EVI": lambda b: 2.5 * _safe_div(b.get("nir", 0) - b.get("red", 0),
                                      b.get("nir", 0) + 6 * b.get("red", 0) - 7.5 * b.get("blue", 0) + 1),
    "NDWI": lambda b: _safe_div(b.get("green", 0) - b.get("nir", 0), b.get("green", 0) + b.get("nir", 0)),
    "NDMI": lambda b: _safe_div(b.get("nir", 0) - b.get("swir1", 0), b.get("nir", 0) + b.get("swir1", 0)),
    "NBR": lambda b: _safe_div(b.get("nir", 0) - b.get("swir2", 0), b.get("nir", 0) + b.get("swir2", 0)),
    "NIRV": lambda b: (b.get("nir", 0) - b.get("red", 0)) * _safe_div(b.get("nir", 0) - b.get("red", 0), b.get("nir", 0) + b.get("red", 0)),
}


def _classify_land_use(ndvi: float, ndwi: float, nbr: float, ndmi: float) -> str:
    if ndwi > 0.15:
        return "水体"
    if nbr < 0.05 and ndvi < 0.3:
        return "火灾迹地"
    if ndvi < 0.15:
        return "裸地/建设用地"
    if ndvi < 0.35:
        return "农田/草地"
    if ndmi < 0.05:
        return "灌木林"
    if ndvi < 0.65:
        return "混交林"
    return "密林"


_CHANGE_THRESHOLDS = {
    "NDVI": {"deforestation": -0.15, "degradation": -0.08, "recovery": 0.08},
    "NDWI": {"pollution_drop": -0.10, "drought": -0.15},
    "NBR": {"fire": -0.20, "partial_burn": -0.10},
}


class CVEngine(AbstractEngine):
    """ES-03 卫星遥感环境监测引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.index_formulas = {}
        self.thresholds = {}
        self.land_use_classifier = None
        self.roi_size_default = 100.0

    def _load_model(self):
        self.index_formulas = dict(_INDEX_FORMULAS)
        self.thresholds = dict(_CHANGE_THRESHOLDS)
        self.land_use_classifier = _classify_land_use
        self.roi_size_default = self.config.get("roi_size_ha", 100.0)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        prepared = []
        for it in items:
            roi_id = it.get("roi_id", it.get("entity", "ROI"))
            roi_name = it.get("roi_name", roi_id)
            area_ha = it.get("area_ha", self.roi_size_default)
            time_slices = it.get("time_slices") or it.get("snapshots", [])
            if not time_slices and "bands" in it:
                time_slices = [{"date": it.get("date", ""), "bands": it["bands"]}]
            if not isinstance(time_slices, list):
                time_slices = [time_slices]
            parsed_slices = []
            for ts in time_slices:
                if isinstance(ts, dict):
                    parsed_slices.append({
                        "date": ts.get("date", ""),
                        "bands": ts.get("bands", {}),
                        "cloud_cover": ts.get("cloud_cover", 0),
                        "source": ts.get("source", "Sentinel-2"),
                    })
            prepared.append({
                "roi_id": roi_id,
                "roi_name": roi_name,
                "area_ha": area_ha,
                "industry": it.get("industry", "制造业"),
                "claimed_actions": it.get("claimed_actions", []),
                "slices": parsed_slices,
            })
        return prepared

    def _infer(self, prepared):
        results = []
        for roi in prepared:
            slices_enriched = []
            for sl in roi["slices"]:
                indices = self._compute_indices(sl["bands"])
                lu = self.land_use_classifier(
                    indices["NDVI"], indices["NDWI"], indices["NBR"], indices["NDMI"]
                )
                slices_enriched.append({**sl, "indices": indices, "land_use": lu})
            changes = self._detect_changes(slices_enriched)
            anomalies = self._find_anomalies(slices_enriched, roi["claimed_actions"])
            greenwashing_check = self._greenwashing_verification(
                slices_enriched, roi["claimed_actions"], changes
            )
            results.append({
                "roi_id": roi["roi_id"],
                "roi_name": roi["roi_name"],
                "area_ha": roi["area_ha"],
                "industry": roi["industry"],
                "timeline": [
                    {
                        "date": s["date"],
                        "cloud_cover": s["cloud_cover"],
                        "land_use": s["land_use"],
                        "indices": {k: round(v, 4) for k, v in s["indices"].items()},
                    }
                    for s in slices_enriched
                ],
                "changes": changes,
                "anomalies": anomalies,
                "greenwashing_check": greenwashing_check,
                "generated_at": datetime.now().isoformat(),
            })
        return results

    def _compute_indices(self, bands: dict) -> dict:
        out = {}
        for name, formula in self.index_formulas.items():
            out[name] = formula(bands)
        return out

    def _detect_changes(self, slices: list) -> list:
        if len(slices) < 2:
            return []
        changes = []
        for i in range(1, len(slices)):
            prev = slices[i - 1]
            curr = slices[i]
            for idx_name in ("NDVI", "NDWI", "NBR"):
                prev_val = prev["indices"].get(idx_name, 0)
                curr_val = curr["indices"].get(idx_name, 0)
                delta = curr_val - prev_val
                thr = self.thresholds.get(idx_name, {})
                label = None
                for key, th in thr.items():
                    if key.startswith("de") and delta <= th:
                        label = key
                        break
                    if key.startswith("re") and delta >= th:
                        label = key
                        break
                if abs(delta) > 0.02:
                    changes.append({
                        "from_date": prev["date"],
                        "to_date": curr["date"],
                        "index": idx_name,
                        "previous": round(prev_val, 4),
                        "current": round(curr_val, 4),
                        "delta": round(delta, 4),
                        "change_pct": round(_safe_div(delta, abs(prev_val)) * 100, 2),
                        "severity": self._severity(idx_name, delta, label),
                        "category": label or ("下降" if delta < 0 else "上升"),
                    })
            if prev["land_use"] != curr["land_use"]:
                changes.append({
                    "from_date": prev["date"],
                    "to_date": curr["date"],
                    "index": "LandUse",
                    "previous": prev["land_use"],
                    "current": curr["land_use"],
                    "delta": "→",
                    "severity": "高" if curr["land_use"] in ("裸地/建设用地", "火灾迹地") else "中",
                    "category": "土地利用变化",
                })
        return changes

    def _severity(self, idx_name: str, delta: float, label: str | None) -> str:
        if not label:
            if abs(delta) > 0.20:
                return "高"
            if abs(delta) > 0.10:
                return "中"
            return "低"
        if "fire" in label or "deforestation" in label or "pollution" in label:
            return "高"
        if "partial" in label or "degradation" in label or "drought" in label:
            return "中"
        return "低"

    def _find_anomalies(self, slices: list, claimed: list) -> list:
        anomalies = []
        if not slices:
            return anomalies
        ndvi_trend = [s["indices"].get("NDVI", 0) for s in slices]
        if len(ndvi_trend) >= 3:
            slope = self._linear_slope(list(range(len(ndvi_trend))), ndvi_trend)
            if slope < -0.02:
                anomalies.append({
                    "type": "趋势异常",
                    "indicator": "NDVI持续下降",
                    "value": round(slope, 4),
                    "description": "植被覆盖度呈持续下降趋势，可能暗示环境退化",
                    "severity": "中",
                })
        nbr_trend = [s["indices"].get("NBR", 1) for s in slices if s["indices"].get("NBR", 1) > 0.5]
        if not nbr_trend:
            pass
        for s in slices:
            if s["indices"].get("NBR", 1) < 0.3:
                anomalies.append({
                    "type": "极端事件",
                    "indicator": "低NBR值",
                    "value": round(s["indices"]["NBR"], 4),
                    "description": f"{s['date']}附近区域NBR异常偏低，疑似火灾或严重植被损失",
                    "severity": "高",
                })
                break
        ndwi_vals = [s["indices"].get("NDWI", 0) for s in slices]
        if ndwi_vals and min(ndwi_vals) < -0.1 and max(ndwi_vals) > 0.3:
            anomalies.append({
                "type": "水体波动",
                "indicator": "NDWI大幅波动",
                "value": f"min={round(min(ndwi_vals),3)}, max={round(max(ndwi_vals),3)}",
                "description": "水体覆盖度大幅波动，可能涉及取水或排污行为",
                "severity": "中",
            })
        return anomalies

    def _greenwashing_verification(self, slices: list, claimed: list, changes: list) -> dict:
        if not slices or not claimed:
            return {"score": 0.5, "signal": "insufficient_data", "verdict": "数据不足"}
        latest = slices[-1]["indices"]
        earliest = slices[0]["indices"]
        ndvi_change = latest.get("NDVI", 0) - earliest.get("NDVI", 0)
        nbr_change = latest.get("NBR", 1) - earliest.get("NBR", 1)
        water_change = latest.get("NDWI", 0) - earliest.get("NDWI", 0)
        contradiction = 0
        support = 0
        for claim in claimed:
            c_text = str(claim).lower()
            if any(kw in c_text for kw in ("种树", "绿化", "恢复植被", "生态恢复")):
                if ndvi_change > 0.05:
                    support += 1
                else:
                    contradiction += 1
            if any(kw in c_text for kw in ("减排", "节能", "低碳")):
                if ndvi_change >= 0:
                    support += 0.5
                else:
                    contradiction += 0.5
            if any(kw in c_text for kw in ("节水", "保护水资源", "湿地保护")):
                if water_change >= -0.05:
                    support += 1
                else:
                    contradiction += 1
        total = contradiction + support
        if total == 0:
            return {"score": 0.5, "signal": "no_claim_match", "verdict": "声明与遥感指标无直接对应"}
        consistency = support / total
        if consistency < 0.4:
            verdict = "绿色漂洗嫌疑高"
            signal = "contradiction"
        elif consistency < 0.7:
            verdict = "部分声明缺乏支撑"
            signal = "weak_support"
        else:
            verdict = "声明与遥感数据一致"
            signal = "supported"
        return {
            "score": round(consistency, 3),
            "signal": signal,
            "verdict": verdict,
            "ndvi_change": round(ndvi_change, 4),
            "nbr_change": round(nbr_change, 4),
            "water_change": round(water_change, 4),
            "support_claims": support,
            "contradiction_claims": contradiction,
        }

    @staticmethod
    def _linear_slope(xs: list, ys: list) -> float:
        n = len(xs)
        mx = statistics.mean(xs)
        my = statistics.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        return _safe_div(num, den)

    def _postprocess(self, result):
        alerts = []
        for roi in result:
            for c in roi["changes"]:
                if c["severity"] == "高":
                    alerts.append({"roi": roi["roi_name"], **c})
            for a in roi["anomalies"]:
                if a["severity"] == "高":
                    alerts.append({"roi": roi["roi_name"], **a})
            gw = roi.get("greenwashing_check", {})
            if gw.get("verdict", "").startswith("绿色漂洗") or gw.get("signal") == "contradiction":
                alerts.append({"roi": roi["roi_name"], "type": "绿色漂洗", "severity": "高", "detail": gw})
        return {
            "roi_reports": result,
            "alerts": alerts,
            "summary": {
                "roi_count": len(result),
                "total_high_severity": len(alerts),
                "greenwashing_suspects": sum(1 for r in result
                                              if r.get("greenwashing_check", {}).get("verdict", "").startswith("绿色漂洗")),
                "generated_at": datetime.now().isoformat(),
            },
        }
