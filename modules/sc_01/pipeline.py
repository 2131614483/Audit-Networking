"""[SC-01] 执行管道 —— 采集 → 评分 → 阈值 → 规则 → 持久化 → 输出。

编排顺序：
  collect(接入数据) → engine.execute(预处理→五维推理→后处理)
  → apply_thresholds(分级 + 复核标记) → apply_custom_rules(一票否决/自动升级)
  → output(PortableDB 持久化 + format_output 格式化)

PortableDB 持久化（中心化公用辐射，模块根 data/sc_01.db）：
  - suppliers           供应商主表（按 supplier_id upsert）
  - risk_assessments    评分结果（每次执行追加，含五维子分/风险点/建议）
  - risk_events         风险事件明细（每个风险点一条记录）
  - scoring_weights     评分权重配置（engine._load_model 已初始化）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import MLEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = MLEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 合并 fixtures + 权重/关键词
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；权重与关键词已在 engine._load_model 合并。"""
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把评分结果落盘到 PortableDB（suppliers / risk_assessments / risk_events）。"""
        db = self.engine.db
        if db is None:
            return
        now = datetime.now()
        for s in result.get("suppliers", []):
            raw = s.get("_raw") or {}
            biz = raw.get("business", {}) or {}

            # 1) suppliers 主表：按 supplier_id upsert（重复执行不堆叠）
            db.upsert("suppliers", {
                "supplier_id": s.get("supplier_id"),
                "name": s.get("name"),
                "uscc": s.get("uscc"),
                "registered_capital": biz.get("registered_capital"),
                "establishment_years": biz.get("establishment_years"),
                "business_status": biz.get("business_status"),
                "change_count": biz.get("change_count"),
                "source": s.get("source"),
                "payload": raw,
                "ingested_at": now,
            }, pk="supplier_id")

            # 2) risk_assessments 评分结果表（每次执行追加，留存历史轨迹）
            db.insert("risk_assessments", {
                "supplier_id": s.get("supplier_id"),
                "name": s.get("name"),
                "total_score": float(s.get("total_score", 0.0)),
                "level": s.get("level"),
                "sub_scores": s.get("sub_scores", {}),
                "risk_points": s.get("risk_points", []),
                "recommendations": s.get("recommendations", []),
                "assessed_at": now,
            })

            # 3) risk_events 风险事件明细表（每个风险点一条记录）
            for rp in s.get("risk_points", []):
                db.insert("risk_events", {
                    "supplier_id": s.get("supplier_id"),
                    "name": s.get("name"),
                    "dimension": rp.get("dimension"),
                    "event_type": "risk_point",
                    "severity": s.get("level"),
                    "description": rp.get("point"),
                    "created_at": now,
                })
