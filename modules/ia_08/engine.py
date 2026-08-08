"""[rpa] IA-08 整改效果自动验证。

纯 stdlib 实现的整改效果自动验证引擎：
  - _load_model  : 加载内置验证规则库（5大类整改类型 × 验证步骤 + 评分权重 + 通过阈值）
  - _preprocess  : 输入整改任务+采集证据，匹配适用的验证规则
  - _infer       : 规则引擎逐条判定（阈值/比较/趋势/权限）→ 综合效果评分 + 置信度评估
  - _postprocess : 输出验证报告（通过/有条件/不通过 + 分项得分 + 退化预警 + 重验周期）
"""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta

from modules.shared.base_engine import AbstractEngine


_REMEDIATION_TYPES = ("流程控制", "系统控制", "权限控制", "数据修复", "制度流程")


class RPAEngine(AbstractEngine):
    """IA-08 整改效果自动验证引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.rules: dict[str, list[dict]] = {}
        self.weights: dict[str, dict] = {}
        self.thresholds: dict[str, dict] = {}

    def _load_model(self):
        self.rules = {
            "流程控制": [
                {"id": "F1", "name": "审批节点完整性", "type": "threshold",
                 "target": "approval_pass_rate", "op": ">=", "value": 0.98, "weight": 0.30,
                 "description": "审批通过率≥98%"},
                {"id": "F2", "name": "SLA达标率", "type": "threshold",
                 "target": "sla_hit_rate", "op": ">=", "value": 0.95, "weight": 0.25,
                 "description": "SLA达成率≥95%"},
                {"id": "F3", "name": "绕过次数", "type": "threshold",
                 "target": "bypass_count", "op": "<=", "value": 0, "weight": 0.30,
                 "description": "绕过控制次数=0"},
                {"id": "F4", "name": "关键节点日志完整", "type": "threshold",
                 "target": "log_complete_rate", "op": ">=", "value": 0.99, "weight": 0.15,
                 "description": "日志完整率≥99%"},
            ],
            "系统控制": [
                {"id": "S1", "name": "配置合规", "type": "threshold",
                 "target": "config_match_rate", "op": ">=", "value": 0.95, "weight": 0.35},
                {"id": "S2", "name": "超限拦截率", "type": "threshold",
                 "target": "block_rate", "op": ">=", "value": 1.0, "weight": 0.25},
                {"id": "S3", "name": "拦截日志完整", "type": "threshold",
                 "target": "block_log_rate", "op": ">=", "value": 0.99, "weight": 0.20},
                {"id": "S4", "name": "绕过权限存在性", "type": "threshold",
                 "target": "bypass_permission", "op": "==", "value": 0, "weight": 0.20},
            ],
            "权限控制": [
                {"id": "P1", "name": "权限矩阵清理", "type": "threshold",
                 "target": "removed_count", "op": "==", "value": 0, "weight": 0.30},
                {"id": "P2", "name": "敏感操作拒绝", "type": "threshold",
                 "target": "denied_attempts", "op": "==", "value": 0, "weight": 0.30},
                {"id": "P3", "name": "权限变更日志", "type": "threshold",
                 "target": "change_log_complete", "op": ">=", "value": 0.99, "weight": 0.20},
                {"id": "P4", "name": "同类权限他人持有", "type": "threshold",
                 "target": "others_with_same", "op": "<=", "value": 1, "weight": 0.20},
            ],
            "数据修复": [
                {"id": "D1", "name": "待修复数据完整率", "type": "threshold",
                 "target": "fix_complete_rate", "op": ">=", "value": 1.0, "weight": 0.35},
                {"id": "D2", "name": "修复后合规", "type": "threshold",
                 "target": "data_valid_rate", "op": ">=", "value": 0.98, "weight": 0.30},
                {"id": "D3", "name": "修复审批记录", "type": "threshold",
                 "target": "approval_exists", "op": "==", "value": 1, "weight": 0.20},
                {"id": "D4", "name": "新错误增长率", "type": "trend",
                 "target": "new_error_rate", "op": "<=", "value": 0.01, "weight": 0.15},
            ],
            "制度流程": [
                {"id": "N1", "name": "制度发布", "type": "existence",
                 "target": "policy_published", "weight": 0.30},
                {"id": "N2", "name": "培训覆盖", "type": "threshold",
                 "target": "training_coverage", "op": ">=", "value": 0.90, "weight": 0.25},
                {"id": "N3", "name": "抽样执行率", "type": "threshold",
                 "target": "execution_rate", "op": ">=", "value": 0.95, "weight": 0.30},
                {"id": "N4", "name": "违规案例", "type": "threshold",
                 "target": "violation_count", "op": "==", "value": 0, "weight": 0.15},
            ],
        }
        self.weights = {
            rt: {r["id"]: r["weight"] for r in rules}
            for rt, rules in self.rules.items()
        }
        self.thresholds = {
            "pass": self.config.get("pass_threshold", 0.8),
            "conditional": self.config.get("conditional_pass_threshold", 0.6),
        }

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        now = datetime.now()
        parsed = []
        for it in items:
            rtype = it.get("remediation_type", "流程控制")
            if rtype not in self.rules:
                rtype = "流程控制"
            evidence = it.get("evidence", {})
            if isinstance(it.get("metrics"), dict):
                evidence.update(it["metrics"])
            history = it.get("history_sequence", [])
            parsed.append({
                "remediation_type": rtype,
                "task_id": it.get("task_id", ""),
                "metrics": evidence,
                "evidence_files": it.get("evidence_files", []),
                "history_sequence": history,
                "sample_size": it.get("sample_size", 50),
                "now": now.isoformat(),
                "validation_time": now.isoformat(),
            })
        return {"items": parsed, "rules": self.rules}

    def _infer(self, prepared):
        results = []
        for item in prepared["items"]:
            rtype = item["remediation_type"]
            rules = self.rules[rtype]
            metric = item["metrics"]
            rule_results = []
            total_w = 0.0
            weighted_pass = 0.0
            for rule in rules:
                passed, evidence = self._evaluate(rule, metric, item["history_sequence"])
                w = rule["weight"]
                rule_results.append({
                    "rule_id": rule["id"],
                    "rule_name": rule["name"],
                    "description": rule["description"],
                    "passed": passed,
                    "weight": w,
                    "evidence": evidence,
                })
                total_w += w
                weighted_pass += (1.0 if passed else 0.0) * w
            score = weighted_pass / max(1e-6, total_w)
            verdict = self._verdict(score)
            confidence = self._confidence(item, len(rules), score)
            degradation = self._degradation_signal(item["history_sequence"], score)
            revalidation_days = self._revalidation_period(rtype, verdict, degradation)
            results.append({
                "task_id": item["task_id"],
                "remediation_type": rtype,
                "score": round(score, 3),
                "verdict": verdict,
                "confidence": round(confidence, 3),
                "confidence_label": self._confidence_label(confidence),
                "rule_results": rule_results,
                "degradation_signal": degradation,
                "revalidation_period_days": revalidation_days,
                "evidence_coverage": self._evidence_coverage(item, rules),
                "generated_at": datetime.now().isoformat(),
            })
        return results

    def _evaluate(self, rule: dict, metric: dict, history: list) -> tuple[bool, dict]:
        target = rule["target"]
        op = rule.get("op", ">=")
        value = rule.get("value")
        rtype = rule["type"]
        current = metric.get(target)
        if current is None:
            return False, {"current": None, "expected": value, "op": op, "reason": "数据缺失"}
        if rtype == "existence":
            passed = bool(current)
        elif rtype == "threshold":
            passed = self._compare(current, op, value)
        elif rtype == "trend":
            hist_vals = [h.get(target) for h in history if h.get(target) is not None]
            if hist_vals:
                trend_avg = statistics.mean(hist_vals[-10:])
                passed = self._compare(trend_avg, op, value)
            else:
                passed = self._compare(current, op, value)
        else:
            passed = self._compare(current, op, value)
        return passed, {"current": current, "expected": value, "op": op, "rule_type": rtype}

    @staticmethod
    def _compare(a, op: str, b) -> bool:
        if a is None or b is None:
            return False
        if op == ">=":
            return a >= b
        if op == ">":
            return a > b
        if op == "<=":
            return a <= b
        if op == "<":
            return a < b
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        return False

    def _verdict(self, score: float) -> str:
        if score >= self.thresholds["pass"]:
            return "通过"
        if score >= self.thresholds["conditional"]:
            return "有条件通过"
        return "不通过"

    def _confidence(self, item: dict, n_rules: int, score: float) -> float:
        cov = self._evidence_coverage(item, self.rules[item["remediation_type"]])
        sample_factor = min(1.0, item.get("sample_size", 10) / 50.0)
        agreement = abs(score - 0.5) * 2.0
        return 0.4 * cov + 0.3 * sample_factor + 0.3 * agreement

    def _confidence_label(self, conf: float) -> str:
        if conf >= 0.8:
            return "高"
        if conf >= 0.6:
            return "中"
        return "低（需人工复核）"

    def _evidence_coverage(self, item: dict, rules: list) -> float:
        metric = item["metrics"]
        hit = sum(1 for r in rules if metric.get(r["target"]) is not None)
        return hit / max(1, len(rules))

    def _degradation_signal(self, history: list, current_score: float) -> dict:
        if not history or len(history) < 2:
            return {"detected": False, "trend": "stable", "drop_pct": 0.0, "level": "无"}
        scores = [h.get("score", 0.7) for h in history if h.get("score") is not None]
        scores.append(current_score)
        recent = scores[-5:]
        if len(recent) >= 2:
            drop = (recent[0] - recent[-1]) / max(0.001, recent[0])
        else:
            drop = 0.0
        if drop > 0.20:
            level = "红色"
        elif drop > 0.10:
            level = "橙色"
        elif drop > 0.05:
            level = "黄色"
        else:
            level = "无"
        trend = "down" if drop > 0.05 else "stable"
        if drop < -0.05:
            trend = "up"
        return {
            "detected": drop > 0.05,
            "trend": trend,
            "drop_pct": round(drop * 100, 2),
            "level": level,
            "history_length": len(history),
        }

    def _revalidation_period(self, rtype: str, verdict: str, degradation: dict) -> int:
        base = {"流程控制": 90, "系统控制": 60, "权限控制": 90, "数据修复": 60, "制度流程": 180}
        period = base.get(rtype, 90)
        if verdict == "不通过":
            period = 30
        elif verdict == "有条件通过":
            period = 45
        if degradation.get("level") == "红色":
            period = min(period, 14)
        elif degradation.get("level") == "橙色":
            period = min(period, 30)
        return period

    def _postprocess(self, result):
        overall = {
            "total": len(result),
            "pass": sum(1 for r in result if r["verdict"] == "通过"),
            "conditional": sum(1 for r in result if r["verdict"] == "有条件通过"),
            "fail": sum(1 for r in result if r["verdict"] == "不通过"),
            "avg_score": round(statistics.mean([r["score"] for r in result]), 3) if result else 0.0,
            "avg_confidence": round(statistics.mean([r["confidence"] for r in result]), 3) if result else 0.0,
        }
        degraded = [r for r in result if r["degradation_signal"]["detected"]]
        low_conf = [r for r in result if r["confidence"] < 0.6]
        return {
            "items": result,
            "overall": overall,
            "degradation_alerts": degraded,
            "needs_human_review": low_conf,
            "generated_at": datetime.now().isoformat(),
        }
