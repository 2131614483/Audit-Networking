"""[IP-01] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(接入 IPO 项目) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(加速分级) → apply_custom_rules(业务规则)
  → output(持久化 PortableDB + format_output)

PortableDB 持久化四张表：ipo_tasks / checkpoints / findings / acceleration_logs。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .engine import LLMEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = LLMEngine(config)
        # 显式触发模型加载：初始化 PortableDB + 加载流程模板与规则库
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        # collect → engine.execute → apply_thresholds → apply_custom_rules → output
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集：透传 IPO 项目输入；流程模板与规则库已在 engine._load_model 加载。"""
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：持久化到 PortableDB（审计追溯）+ 格式化对外结构。"""
        self._persist(result)
        return format_output(result)

    def _persist(self, result: Any) -> None:
        """把本次执行的任务/核查点/发现/加速日志写回 PortableDB 四张运行时表。"""
        db = self.engine.db
        if db is None:
            return
        now = datetime.now()
        project_id = (result.get("project", {}) or {}).get("project_id", "IPO-UNKNOWN")

        # 1. ipo_tasks：实例化的审计任务
        for t in result.get("tasks", []):
            db.insert("ipo_tasks", {
                "task_id": t.get("task_id"),
                "category": t.get("category"),
                "task_name": t.get("task_name"),
                "description": t.get("description"),
                "status": t.get("status"),
                "rpa_automatable": 1 if t.get("rpa_automatable") else 0,
                "ml_assisted": 1 if t.get("ml_assisted") else 0,
                "rpa_replacement_rate": t.get("rpa_replacement_rate", 0.0),
                "ml_assist_rate": t.get("ml_assist_rate", 0.0),
                "acceleration_ratio": t.get("acceleration_ratio", 0.0),
                "estimated_hours": t.get("estimated_hours", 0.0),
                "after_hours": t.get("after_hours", 0.0),
                "is_bottleneck": 1 if t.get("is_bottleneck") else 0,
                "payload": {
                    "project_id": project_id,
                    "acceleration_tier": t.get("acceleration_tier"),
                    "manual_review_reason": t.get("manual_review_reason"),
                },
                "created_at": now,
            })

        # 2. checkpoints：核查点执行记录
        for cp in result.get("checkpoints", []):
            db.insert("checkpoints", {
                "checkpoint_id": cp.get("checkpoint_id"),
                "category": cp.get("category"),
                "rule_id": cp.get("rule_id"),
                "rule_name": cp.get("rule_name"),
                "target_task_id": cp.get("target_task_id"),
                "status": cp.get("status"),
                "payload": {"project_id": project_id, "rule": cp.get("payload", {}).get("rule")},
                "created_at": now,
            })

        # 3. findings：核查发现
        for f in result.get("findings", []):
            db.insert("findings", {
                "finding_id": f.get("finding_id"),
                "category": f.get("category"),
                "severity": f.get("severity"),
                "source": f.get("source"),
                "description": f.get("description"),
                "related_task_id": f.get("related_task_id"),
                "need_manual_review": 1 if f.get("need_manual_review") else 0,
                "payload": {
                    "project_id": project_id,
                    "rule_applied": f.get("rule_applied"),
                    "key_check": f.get("key_check", False),
                    "escalated": f.get("escalated", False),
                    "detail": f.get("payload", {}),
                },
                "created_at": now,
            })

        # 4. acceleration_logs：加速日志（按技术栈阶段 + 每任务加速）
        accel = result.get("acceleration", {}) or {}
        # 4.1 各技术栈阶段汇总日志
        rpa = result.get("rpa_results", {}) or {}
        ml = result.get("ml_results", {}) or {}
        llm = result.get("llm_results", {}) or {}
        kg = result.get("kg_results", {}) or {}
        phase_meta = [
            ("rpa", "RPA任务自动化", rpa.get("automated_count", 0)),
            ("ml", "ML财务核查", ml.get("anomaly_count", 0)),
            ("llm", "LLM文档处理", llm.get("doc_count", 0)),
            ("kg", "KG知识图谱穿透",
             len(kg.get("equity_penetration", [])) + len(kg.get("related_transactions", []))),
        ]
        for phase, action, count in phase_meta:
            db.insert("acceleration_logs", {
                "phase": phase,
                "task_id": None,
                "action": action,
                "before_hours": 0.0,
                "after_hours": 0.0,
                "saved_hours": 0.0,
                "payload": {"project_id": project_id, "count": count},
                "created_at": now,
            })
        # 4.2 每任务加速日志
        for ta in accel.get("task_accelerations", []):
            db.insert("acceleration_logs", {
                "phase": "acceleration",
                "task_id": ta.get("task_id"),
                "action": ta.get("task_name"),
                "before_hours": ta.get("before_hours", 0.0),
                "after_hours": ta.get("after_hours", 0.0),
                "saved_hours": ta.get("saved_hours", 0.0),
                "payload": {
                    "project_id": project_id,
                    "category": ta.get("category"),
                    "acceleration_ratio": ta.get("acceleration_ratio"),
                    "is_bottleneck": ta.get("is_bottleneck"),
                },
                "created_at": now,
            })
