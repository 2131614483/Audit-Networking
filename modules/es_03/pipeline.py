"""[ES-03] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(归一化卫星遥感数据：ROI 列表 / 坐标 / 时序波段)
  → engine.execute(预处理→推理→后处理)
  → apply_thresholds(环境影响分级) → apply_custom_rules(违规标记/升级)
  → output(format_output 对外报告)
"""
from __future__ import annotations

from typing import Any

from .engine import CVEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = CVEngine(config)
        # 显式触发模型加载（遥感指数公式库 + 分类器 + 变化阈值）
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：归一化输入为 ROI 列表，解析坐标与时序波段数据。"""
        items = _normalize_items(input_data)
        normalized = []
        for it in items:
            if not isinstance(it, dict):
                continue
            item = dict(it)
            # 解析坐标（支持 dict / "lng,lat" 字符串）
            coords = it.get("coordinates") or it.get("coords") or it.get("location")
            item["coordinates"] = _parse_coordinates(coords)
            # 兼容 snapshots → time_slices 别名
            if "time_slices" not in item and "snapshots" in item:
                item["time_slices"] = item["snapshots"]
            normalized.append(item)
        return normalized

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外环境监测报告。"""
        return format_output(result)


def _normalize_items(input_data: Any) -> list:
    """把多种输入形态统一为 ROI item 列表。"""
    if isinstance(input_data, list):
        return input_data
    if isinstance(input_data, dict):
        for key in ("rois", "regions", "areas", "sites"):
            if key in input_data and isinstance(input_data[key], list):
                return input_data[key]
        # 单 ROI 包装（含 time_slices / bands）
        if any(k in input_data for k in ("time_slices", "snapshots", "bands", "roi_id")):
            return [input_data]
        return [input_data]
    return []


def _parse_coordinates(coords: Any) -> dict | None:
    """解析坐标：支持 dict / "lng,lat" / "lng，lat" 字符串。"""
    if coords is None:
        return None
    if isinstance(coords, dict):
        return coords
    if isinstance(coords, str):
        s = coords.strip().replace("，", ",")
        parts = s.split(",")
        if len(parts) == 2:
            try:
                return {"lng": float(parts[0]), "lat": float(parts[1])}
            except ValueError:
                return None
    return None
