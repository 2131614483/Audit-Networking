"""[CM-02] 智能预警分级与自动处理引擎 —— 多规则评分 + 分级路由。

纯 stdlib 实现，覆盖方案文档中的预警分级与自动处置：
  * 规则匹配：金额阈值 / 频次阈值 / 非工作时段 / 重复告警
  * 严重度评分：多规则加权 → 0-100 分
  * 分级路由：P0(>=80, 立即处置) / P1(60-79, 专项审查) / P2(40-59, 监控) / P3(<40, 归档)
  * 自动处置：P3 自动关闭，P2 纳入监控，P1/P0 触发人工/自动流程

模型结构（self.model）：
  {
    "rules": [...],     # 规则列表（条件 + 分值 + 描述）
    "levels": [...],    # 分级阈值 + 路由动作
  }
"""
from __future__ import annotations

from typing import Any

from modules.shared.base_engine import AbstractEngine


class RPAEngine(AbstractEngine):
    """预警分级与自动处置引擎（规则驱动，纯 stdlib）。"""

    def _load_model(self) -> None:
        """加载分级规则 + 路由策略。"""
        self.model = {
            "rules": [
                {"id": "R001", "name": "大额交易", "field": "amount",
                 "op": ">", "value": 1_000_000, "score": 30},
                {"id": "R002", "name": "超大额交易", "field": "amount",
                 "op": ">", "value": 5_000_000, "score": 50},
                {"id": "R003", "name": "高频告警", "field": "frequency",
                 "op": ">", "value": 10, "score": 25},
                {"id": "R004", "name": "非工作时段", "field": "after_hours",
                 "op": "==", "value": True, "score": 15},
                {"id": "R005", "name": "重复告警", "field": "repeat_count",
                 "op": ">", "value": 3, "score": 20},
                {"id": "R006", "name": "高风险类别", "field": "category",
                 "op": "in", "value": ["fraud", "aml", "sanction"], "score": 35},
            ],
            "levels": [
                ("P0", 80, "立即处置", "auto_block"),
                ("P1", 60, "专项审查", "escalate"),
                ("P2", 40, "纳入监控", "monitor"),
                ("P3", 0,  "自动归档", "auto_close"),
            ],
        }

    def _preprocess(self, input_data: Any) -> Any:
        """提取告警列表（懒加载模型）。"""
        if self.model is None:
            self._load_model()
        if isinstance(input_data, dict) and "alerts" in input_data:
            return input_data["alerts"]
        return input_data if isinstance(input_data, list) else []

    def _infer(self, prepared: Any) -> Any:
        """多规则匹配 → 严重度评分。"""
        rules = self.model["rules"]
        results = []
        for alert in prepared:
            score = 0
            matched = []
            for rule in rules:
                field_val = alert.get(rule["field"])
                if field_val is None:
                    continue
                hit = False
                op, target = rule["op"], rule["value"]
                if op == ">" and isinstance(field_val, (int, float)):
                    hit = field_val > target
                elif op == "==" :
                    hit = field_val == target
                elif op == "in" and isinstance(field_val, (str, list)):
                    hit = field_val in target if isinstance(field_val, str) else any(v in target for v in field_val)
                if hit:
                    score += rule["score"]
                    matched.append({"rule_id": rule["id"], "name": rule["name"], "score": rule["score"]})
            results.append({
                "alert_id": alert.get("alert_id", "?"),
                "source": alert.get("source", "unknown"),
                "category": alert.get("category", "unknown"),
                "severity_score": min(score, 100),
                "matched_rules": matched,
                "raw_data": {k: v for k, v in alert.items() if k not in ("alert_id", "source")},
            })
        results.sort(key=lambda x: x["severity_score"], reverse=True)
        return results

    def _postprocess(self, result: Any) -> Any:
        """分级路由 + 处置动作。"""
        levels = self.model["levels"]
        for r in result:
            s = r["severity_score"]
            for level, threshold, action_desc, action in levels:
                if s >= threshold:
                    r["priority"] = level
                    r["action_desc"] = action_desc
                    r["action"] = action
                    break
        summary = {
            "total": len(result),
            "P0": sum(1 for r in result if r["priority"] == "P0"),
            "P1": sum(1 for r in result if r["priority"] == "P1"),
            "P2": sum(1 for r in result if r["priority"] == "P2"),
            "P3": sum(1 for r in result if r["priority"] == "P3"),
            "auto_closed": sum(1 for r in result if r["action"] == "auto_close"),
        }
        return {"alerts": result, "summary": summary}
