"""[CO-06] 执行管道 —— 采集 → 处理 → 输出三阶段。

编排顺序：
  collect(解析告警/交易/客户数据) → engine.execute(预处理→推理→后处理)
  → apply_thresholds(SAR 优先级分级) → apply_custom_rules(业务规则)
  → output(format_output 格式化 SAR 报告)
"""
from __future__ import annotations

from typing import Any

from .engine import KGEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = KGEngine(config)
        # 显式触发模型加载：初始化多监管模板 / 字段映射 / 质量评分框架
        self.engine.setup()

    def run(self, input_data: Any) -> Any:
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> dict:
        """数据采集：解析告警、交易、客户数据，归一化为 engine 输入结构。

        接受多种输入形态：
          - {"alert": {...}, "template_id": ..., "report_date": ...}（标准）
          - {alert 字段直接平铺}（裸告警）
          - {"transactions": [...], "customer": {...}}（拆分输入）
        统一返回 {"alert": {...}, "template_id": ..., "report_date": ...}。
        """
        if isinstance(input_data, str):
            import json
            try:
                input_data = json.loads(input_data)
            except (json.JSONDecodeError, ValueError):
                return {"alert": {"raw_text": input_data}}
        if not isinstance(input_data, dict):
            return {"alert": {"data": input_data}}

        # 已是标准结构（含 alert 键）→ 直接返回
        if "alert" in input_data:
            return input_data

        # 裸告警：含 transactions / customer / alert_id 等告警字段 → 包装为 alert
        alert_keys = {
            "alert_id", "risk_score", "trigger_reason", "patterns",
            "transactions", "customer", "subjects", "related_accounts",
            "related_parties", "attachments", "external_info",
        }
        if alert_keys & set(input_data.keys()):
            alert = dict(input_data)
            # 顶层 template_id / report_date 不应进入 alert
            template_id = alert.pop("template_id", None)
            report_date = alert.pop("report_date", None)
            out: dict = {"alert": alert}
            if template_id is not None:
                out["template_id"] = template_id
            if report_date is not None:
                out["report_date"] = report_date
            return out

        # 拆分输入：{"transactions": [...], "customer": {...}} → 组装告警
        alert = {}
        if "transactions" in input_data:
            alert["transactions"] = input_data["transactions"]
        if "customer" in input_data:
            alert["customer"] = input_data["customer"]
        if "subjects" in input_data:
            alert["subjects"] = input_data["subjects"]
        if "related_accounts" in input_data:
            alert["related_accounts"] = input_data["related_accounts"]
        if "related_parties" in input_data:
            alert["related_parties"] = input_data["related_parties"]
        if "risk_score" in input_data:
            alert["risk_score"] = input_data["risk_score"]
        if "trigger_reason" in input_data:
            alert["trigger_reason"] = input_data["trigger_reason"]
        if "alert_id" in input_data:
            alert["alert_id"] = input_data["alert_id"]

        out = {"alert": alert}
        if "template_id" in input_data:
            out["template_id"] = input_data["template_id"]
        if "report_date" in input_data:
            out["report_date"] = input_data["report_date"]
        return out

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为对外 SAR 报告结构。"""
        return format_output(result)
