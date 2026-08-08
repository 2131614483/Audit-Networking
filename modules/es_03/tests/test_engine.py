"""[ES-03] engine 单测：卫星遥感环境监测（遥感指数 / 土地利用分类 / 变化检测 / 绿色漂洗）。

CVEngine 为纯 stdlib 实现（无 PortableDB 依赖）：
  * 遥感指数：NDVI / EVI / NDWI / NDMI / NBR / NIRV
  * 土地利用分类：基于 NDVI/NDWI/NBR/NDMI 阈值
  * 变化检测：多时相指数 delta → 毁林 / 退化 / 火灾 / 水质变化
  * 绿色漂洗验证：声明 vs 遥感指标一致性
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.es_03.engine import CVEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> dict:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_engine(**overrides) -> CVEngine:
    eng = CVEngine(config=overrides)
    eng.setup()
    return eng


def _slice(date, nir, red, green=0.2, blue=0.05, swir1=0.2, swir2=0.15, cloud_cover=0) -> dict:
    return {
        "date": date,
        "cloud_cover": cloud_cover,
        "source": "Sentinel-2",
        "bands": {"nir": nir, "red": red, "green": green, "blue": blue,
                  "swir1": swir1, "swir2": swir2},
    }


def _roi(**fields) -> dict:
    base = {
        "roi_id": "R1",
        "roi_name": "测试ROI",
        "area_ha": 100.0,
        "industry": "制造业",
        "claimed_actions": [],
        "time_slices": [],
    }
    base.update(fields)
    return base


# ----------------------------------------------------------------------
# 遥感指数计算
# ----------------------------------------------------------------------
def test_ndvi_computed_correctly():
    """NDVI = (nir - red) / (nir + red)。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.60, red=0.10)])])
    indices = result["roi_reports"][0]["timeline"][0]["indices"]
    # (0.60-0.10)/(0.60+0.10) = 0.5/0.7
    assert indices["NDVI"] == round(0.5 / 0.7, 4)


def test_ndwi_water_index():
    """NDWI = (green - nir) / (green + nir)。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.30, red=0.20, green=0.60)])])
    indices = result["roi_reports"][0]["timeline"][0]["indices"]
    # (0.60-0.30)/(0.60+0.30) = 0.3/0.9
    assert indices["NDWI"] == round(0.3 / 0.9, 4)


def test_all_six_indices_computed():
    """每个时间片计算 6 个遥感指数。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.50, red=0.20)])])
    indices = result["roi_reports"][0]["timeline"][0]["indices"]
    assert set(indices.keys()) == {"NDVI", "EVI", "NDWI", "NDMI", "NBR", "NIRV"}


def test_indices_rounded_to_four_decimals():
    """indices 保留 4 位小数。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.60, red=0.10)])])
    indices = result["roi_reports"][0]["timeline"][0]["indices"]
    for v in indices.values():
        # round(x, 4) 的小数位不会超过 4
        assert round(v, 4) == v


# ----------------------------------------------------------------------
# 土地利用分类
# ----------------------------------------------------------------------
def test_land_use_dense_forest():
    """高 NDVI (>0.65) 且 NDMI 充足 → 密林。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.60, red=0.10)])])
    assert result["roi_reports"][0]["timeline"][0]["land_use"] == "密林"


def test_land_use_water():
    """NDWI > 0.15 → 水体。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.30, red=0.20, green=0.60)])])
    assert result["roi_reports"][0]["timeline"][0]["land_use"] == "水体"


def test_land_use_fire_scar():
    """低 NBR (<0.05) + 低 NDVI (<0.3) → 火灾迹地。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.20, red=0.40, swir2=0.50)])])
    # NBR = (0.20-0.50)/0.70 = -0.4286 < 0.05, NDVI = -0.3333 < 0.3
    assert result["roi_reports"][0]["timeline"][0]["land_use"] == "火灾迹地"


# ----------------------------------------------------------------------
# 变化检测
# ----------------------------------------------------------------------
def test_change_detection_ndvi_drop_deforestation():
    """NDVI 显著下降 (<=-0.15) → deforestation，severity 高。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[
        _slice("2023-01-01", nir=0.60, red=0.10),  # NDVI=0.7143
        _slice("2024-01-01", nir=0.20, red=0.40),  # NDVI=-0.3333
    ])])
    changes = result["roi_reports"][0]["changes"]
    ndvi_changes = [c for c in changes if c["index"] == "NDVI"]
    assert len(ndvi_changes) == 1
    assert ndvi_changes[0]["category"] == "deforestation"
    assert ndvi_changes[0]["severity"] == "高"
    assert ndvi_changes[0]["delta"] < 0


def test_no_changes_with_single_slice():
    """单时间片无法检测变化 → changes 为空。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.50, red=0.20)])])
    assert result["roi_reports"][0]["changes"] == []


def test_land_use_change_recorded():
    """土地利用类型变化被记录为 LandUse 变化项。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[
        _slice("2023-01-01", nir=0.60, red=0.10),                 # 密林
        _slice("2024-01-01", nir=0.20, red=0.40, swir2=0.50),     # 火灾迹地
    ])])
    changes = result["roi_reports"][0]["changes"]
    lu_changes = [c for c in changes if c["index"] == "LandUse"]
    assert len(lu_changes) == 1
    assert lu_changes[0]["previous"] == "密林"
    assert lu_changes[0]["current"] == "火灾迹地"
    assert lu_changes[0]["severity"] == "高"


def test_change_includes_from_to_dates():
    """变化记录含 from_date / to_date。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[
        _slice("2023-01-01", nir=0.60, red=0.10),
        _slice("2024-01-01", nir=0.20, red=0.40),
    ])])
    for c in result["roi_reports"][0]["changes"]:
        assert c["from_date"] == "2023-01-01"
        assert c["to_date"] == "2024-01-01"


# ----------------------------------------------------------------------
# 绿色漂洗验证
# ----------------------------------------------------------------------
def test_greenwashing_supported_when_ndvi_rises():
    """声明种树且 NDVI 上升 → supported（声明与遥感数据一致）。"""
    eng = _make_engine()
    result = eng.execute([_roi(claimed_actions=["种树"], time_slices=[
        _slice("2023-01-01", nir=0.40, red=0.30),  # NDVI=0.1429
        _slice("2024-01-01", nir=0.60, red=0.10),  # NDVI=0.7143
    ])])
    gw = result["roi_reports"][0]["greenwashing_check"]
    assert gw["signal"] == "supported"
    assert gw["verdict"] == "声明与遥感数据一致"
    assert gw["score"] == 1.0


def test_greenwashing_contradiction_when_ndvi_drops():
    """声明种树但 NDVI 下降 → contradiction（绿色漂洗嫌疑高）。"""
    eng = _make_engine()
    result = eng.execute([_roi(claimed_actions=["种树"], time_slices=[
        _slice("2023-01-01", nir=0.60, red=0.10),  # NDVI=0.7143
        _slice("2024-01-01", nir=0.20, red=0.40),  # NDVI=-0.3333
    ])])
    gw = result["roi_reports"][0]["greenwashing_check"]
    assert gw["signal"] == "contradiction"
    assert gw["verdict"] == "绿色漂洗嫌疑高"
    assert gw["score"] == 0.0


def test_greenwashing_no_claims_returns_insufficient():
    """无 claimed_actions → insufficient_data。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[_slice("2024-01-01", nir=0.50, red=0.20)])])
    gw = result["roi_reports"][0]["greenwashing_check"]
    assert gw["signal"] == "insufficient_data"
    assert gw["verdict"] == "数据不足"


# ----------------------------------------------------------------------
# 告警 / 汇总
# ----------------------------------------------------------------------
def test_alerts_collect_high_severity_only():
    """高 severity 的变化/异常被收集到 alerts。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[
        _slice("2023-01-01", nir=0.60, red=0.10),
        _slice("2024-01-01", nir=0.20, red=0.40, swir2=0.50),
    ])])
    alerts = result["alerts"]
    assert len(alerts) >= 1
    for a in alerts:
        assert a["severity"] == "高"


def test_summary_structure_and_roi_count():
    """summary 含 roi_count / total_high_severity / greenwashing_suspects。"""
    eng = _make_engine()
    result = eng.execute(_sample()["rois"])
    s = result["summary"]
    assert s["roi_count"] == 4
    assert "total_high_severity" in s
    assert "greenwashing_suspects" in s


def test_empty_input_returns_empty_reports():
    """空 ROI 列表返回空结果。"""
    eng = _make_engine()
    result = eng.execute([])
    assert result["roi_reports"] == []
    assert result["alerts"] == []
    assert result["summary"]["roi_count"] == 0


def test_roi_metadata_preserved():
    """ROI 的 roi_id / roi_name / area_ha / industry 透传到结果。"""
    eng = _make_engine()
    result = eng.execute([_roi(
        roi_id="X1", roi_name="矿区", area_ha=500.0, industry="矿业",
        time_slices=[_slice("2024-01-01", nir=0.50, red=0.20)],
    )])
    r = result["roi_reports"][0]
    assert r["roi_id"] == "X1"
    assert r["roi_name"] == "矿区"
    assert r["area_ha"] == 500.0
    assert r["industry"] == "矿业"


def test_timeline_carries_land_use_and_indices():
    """timeline 每项含 date / land_use / indices。"""
    eng = _make_engine()
    result = eng.execute([_roi(time_slices=[
        _slice("2024-01-01", nir=0.60, red=0.10),
    ])])
    t = result["roi_reports"][0]["timeline"][0]
    assert t["date"] == "2024-01-01"
    assert "land_use" in t
    assert "indices" in t
    assert "NDVI" in t["indices"]


# ----------------------------------------------------------------------
# 模型加载
# ----------------------------------------------------------------------
def test_setup_loads_formulas_thresholds_classifier():
    """setup() 后加载遥感指数公式库 / 变化阈值 / 分类器。"""
    eng = _make_engine()
    assert "NDVI" in eng.index_formulas
    assert "NBR" in eng.index_formulas
    assert "NDVI" in eng.thresholds
    assert eng.land_use_classifier is not None


def test_roi_size_default_from_config():
    """config.roi_size_ha 透传到 roi_size_default。"""
    eng = _make_engine(roi_size_ha=250.0)
    assert eng.roi_size_default == 250.0
