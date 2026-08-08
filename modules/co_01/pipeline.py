"""[CO-01] 执行管道 —— 采集 → 处理 → 阈值 → 业务规则 → 输出。

编排顺序：
  collect(接入法规数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(相关性分级 push/watch/ignore)
  → apply_custom_rules(影响升级 + 强制推送)
  → output(持久化 PortableDB + format_output 法规监控日报)

PortableDB 持久化：将法规元数据、分类结果、影响评估写回
regulations / regulation_categories / impact_assessments 三表，供审计追溯。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = KGEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 建表 + 导入订阅规则种子
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入；订阅规则已在 engine._load_model 中合并。"""
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把法规元数据 / 分类结果 / 影响评估写回 PortableDB 三表。"""
        db = self.engine.db
        if db is None:
            return
        now = datetime.now()
        for r in result.get("regulations", []):
            reg_id = r.get("reg_id") or ""
            # 法规元数据表
            db.insert("regulations", {
                "reg_id": reg_id,
                "title": r.get("title"),
                "title_en": r.get("title_en"),
                "body": r.get("body"),
                "agency": r.get("agency"),
                "country": r.get("country"),
                "country_name": r.get("country_name"),
                "language": r.get("language"),
                "publish_date": r.get("publish_date"),
                "effective_date": r.get("effective_date"),
                "url": r.get("url"),
                "applicable_size": r.get("applicable_size"),
                "source": r.get("source"),
                "created_at": now,
            })
            # 分类结果表
            db.insert("regulation_categories", {
                "reg_id": reg_id,
                "category": r.get("category"),
                "confidence": float(r.get("category_confidence", 0.0)),
                "matched_keywords": r.get("matched_keywords", []),
                "created_at": now,
            })
            # 影响评估表
            db.insert("impact_assessments", {
                "reg_id": reg_id,
                "impact_level": r.get("impact_level"),
                "relevance": float(r.get("relevance", 0.0)),
                "country_match": int(bool(r.get("country_match"))),
                "industry_match": float(r.get("industry_match", 0.0)),
                "scope_match": int(bool(r.get("scope_match"))),
                "applicable_industries": r.get("applicable_industries", []),
                "applicable_scope": r.get("applicable_scope"),
                "push": int(bool(r.get("push"))),
                "matched_rules": r.get("matched_rules", []),
                "reason": ",".join(r.get("push_reasons", [])),
                "created_at": now,
            })
