"""[FA-07] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(完成度分级) → apply_custom_rules(复核标记)
  → output(持久化 PortableDB + format_output)
"""
from __future__ import annotations

import uuid
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
        # 显式触发模型加载：初始化 PortableDB + 导入模板种子
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传输入（科目余额/凭证/合同已由 engine._preprocess 规范化）。"""
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把生成的底稿 / 交叉引用 / 生成日志写回 PortableDB。"""
        db = self.engine.db
        if db is None:
            return
        batch_id = uuid.uuid4().hex[:12]
        now = datetime.now()

        # 1. 持久化每份底稿 + 生成日志
        for wp in result.get("workpapers", []):
            db.insert("workpapers", {
                "workpaper_id": wp.get("workpaper_id"),
                "template_id": wp.get("template_id"),
                "subject_code": wp.get("subject_code"),
                "subject_name": wp.get("subject_name"),
                "filled_content": wp.get("filled_content"),
                "conclusion": wp.get("conclusion"),
                "conclusion_severity": wp.get("conclusion_severity"),
                "completeness": float(wp.get("completeness", 0.0)),
                "created_at": now,
                "payload": {
                    "template_name": wp.get("template_name"),
                    "audit_procedure": wp.get("audit_procedure"),
                    "placeholders_filled": wp.get("placeholders_filled"),
                    "placeholders_missing": wp.get("placeholders_missing"),
                    "conclusion_rules_hit": wp.get("conclusion_rules_hit"),
                    "tier": wp.get("tier"),
                    "needs_review": wp.get("needs_review"),
                    "review_reasons": wp.get("review_reasons"),
                    "warnings": wp.get("warnings"),
                    "cross_references": wp.get("cross_references"),
                },
            })
            db.insert("generation_logs", {
                "batch_id": batch_id,
                "template_id": wp.get("template_id"),
                "workpaper_id": wp.get("workpaper_id"),
                "action": "generate_workpaper",
                "created_at": now,
                "payload": {"tier": wp.get("tier"),
                            "completeness": wp.get("completeness")},
            })

        # 2. 持久化交叉引用
        for ref in result.get("cross_references", []):
            db.insert("cross_references", {
                "from_workpaper_id": ref.get("from_workpaper_id"),
                "to_workpaper_id": ref.get("to_workpaper_id"),
                "to_template_id": ref.get("to_template_id"),
                "to_template_name": ref.get("to_template_name"),
                "status": ref.get("status"),
                "created_at": now,
            })
            if ref.get("status") == "broken":
                db.insert("generation_logs", {
                    "batch_id": batch_id,
                    "template_id": ref.get("to_template_id"),
                    "workpaper_id": ref.get("from_workpaper_id"),
                    "action": "broken_cross_ref",
                    "created_at": now,
                    "payload": {"to_template_name": ref.get("to_template_name")},
                })

        # 3. 批次汇总日志
        stats = result.get("statistics", {})
        db.insert("generation_logs", {
            "batch_id": batch_id,
            "template_id": None,
            "workpaper_id": None,
            "action": "batch_summary",
            "created_at": now,
            "payload": stats,
        })
