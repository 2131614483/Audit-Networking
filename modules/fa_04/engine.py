"""[FA-04] 智能函证管理平台 —— 全流程状态机 + 差异处理 + 催函预警。

算法设计（纯 stdlib：datetime / hashlib）：

  * _load_model:
      - 函证状态机（draft→sent→delivered→replied→reconciled→closed，含超时/退回/差异分支）
      - 模板库（银行函证/往来函证/律师函证）
      - 催函规则（48h/72h/120h 阶梯提醒）
  * _preprocess: 将 input 标准化为 confirmation 记录列表
  * _infer:
      ① 状态机推进（按规则流转）
      ② 催函触发判断
      ③ 回函比对（逐字段差异识别）
      ④ 差异分派（按类型 → 负责人类）
  * _postprocess: 函证仪表板数据（各状态计数 + 平均周期 + 异常清单）
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from modules.shared.base_engine import AbstractEngine


STATE_FLOW = {
    "draft": ["sent", "cancelled"],
    "sent": ["delivered", "timeout", "returned"],
    "delivered": ["replied", "timeout"],
    "timeout": ["sent"],
    "replied": ["reconciled", "difference"],
    "returned": ["sent", "cancelled"],
    "difference": ["resolved", "escalated"],
    "reconciled": ["closed"],
    "resolved": ["reconciled"],
    "escalated": ["closed"],
    "closed": [],
    "cancelled": [],
}

STATUS_META = {
    "draft": "草稿", "sent": "已发送", "delivered": "已送达",
    "replied": "已回函", "reconciled": "已核对", "closed": "已闭环",
    "timeout": "超时", "returned": "退回", "difference": "有差异",
    "resolved": "差异已解决", "escalated": "已升级", "cancelled": "已取消",
}

TEMPLATE_BANK = {
    "template_id": "TPL-BANK-001", "name": "银行存款函证",
    "fields": ["bank_name", "account_number", "account_name",
               "currency", "balance", "as_of_date", "interest_rate",
               "freeze_status", "pledge_info"],
}
TEMPLATE_TRADE = {
    "template_id": "TPL-TRADE-001", "name": "往来款项函证",
    "fields": ["counterparty", "account_type", "amount", "as_of_date"],
}
TEMPLATE_LAWYER = {
    "template_id": "TPL-LAW-001", "name": "律师询证函",
    "fields": ["law_firm", "matter", "status", "amount_involved"],
}


class BlockchainEngine(AbstractEngine):
    """智能函证管理平台引擎（纯 stdlib：状态机 + 模板引擎 + 差异比对）。"""

    def _load_model(self) -> None:
        self.model = {
            "state_flow": STATE_FLOW,
            "status_meta": STATUS_META,
            "templates": [TEMPLATE_BANK, TEMPLATE_TRADE, TEMPLATE_LAWYER],
            "escalation_rules": [
                {"after_hours": 48, "channel": "email", "level": 1},
                {"after_hours": 72, "channel": "sms", "level": 2},
                {"after_hours": 120, "channel": "phone", "level": 3},
            ],
            "diff_assign": {
                "amount": "审计师A", "account": "审计师B",
                "interest": "审计师C", "freeze": "高级审计师",
            },
        }

    def _preprocess(self, input_data: Any) -> Any:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 confirmations 列表")
        now = datetime.now()
        confs = input_data.get("confirmations", []) or []
        norm: list[dict] = []
        for i, c in enumerate(confs):
            if not isinstance(c, dict):
                continue
            created = c.get("created_at") or now.isoformat()
            norm.append({
                "confirmation_id": c.get("confirmation_id", f"CF-{i + 1:04d}"),
                "type": c.get("type", "bank"),
                "template": c.get("template", self._match_template(c.get("type", "bank"))),
                "status": c.get("status", "draft"),
                "bank_or_counterparty": c.get("bank_name") or c.get("counterparty", ""),
                "account_number": c.get("account_number", ""),
                "audit_values": c.get("audit_values", {}),
                "bank_values": c.get("bank_values", {}),
                "created_at": created,
                "sent_at": c.get("sent_at"),
                "replied_at": c.get("replied_at"),
                "deadline": c.get("deadline"),
                "channel": c.get("channel", "email"),
                "diff_records": c.get("diff_records", []),
                "audit_values_hash": self._hash_values(c.get("audit_values", {})),
            })
        return {"confirmations": norm, "now": now}

    def _match_template(self, ctype: str) -> dict:
        tpl_map = {"bank": TEMPLATE_BANK, "trade": TEMPLATE_TRADE, "lawyer": TEMPLATE_LAWYER}
        return tpl_map.get(ctype, TEMPLATE_BANK)

    def _hash_values(self, values: dict) -> str:
        blob = json.dumps(values, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def _infer(self, prepared: Any) -> Any:
        now = prepared["now"]
        confs = prepared["confirmations"]
        transitions: list[dict] = []
        reconciled: list[dict] = []
        escalations: list[dict] = []
        for c in confs:
            new_state = self._advance_state(c, now)
            if new_state != c["status"]:
                transitions.append({
                    "confirmation_id": c["confirmation_id"],
                    "from": c["status"], "to": new_state,
                    "reason": self._transition_reason(c, new_state),
                })
                c["status"] = new_state

            if c["status"] in ("replied",):
                diffs = self._reconcile(c)
                c["diff_records"] = diffs
                if diffs:
                    c["status"] = "difference"
                    for d in diffs:
                        assignee = self.model["diff_assign"].get(d["diff_type"], "待分配")
                        reconciled.append({
                            "confirmation_id": c["confirmation_id"],
                            "bank": c["bank_or_counterparty"],
                            "diff_type": d["diff_type"],
                            "detail": d["detail"],
                            "assignee": assignee,
                        })
                else:
                    c["status"] = "reconciled"

            if c["status"] in ("sent", "delivered", "timeout"):
                esc = self._check_escalation(c, now)
                if esc:
                    escalations.append({
                        "confirmation_id": c["confirmation_id"],
                        "bank": c["bank_or_counterparty"],
                        "level": esc["level"],
                        "channel": esc["channel"],
                        "hours_elapsed": esc["hours"],
                    })

        return {
            "confirmations": confs,
            "transitions": transitions,
            "reconciliations": reconciled,
            "escalations": escalations,
        }

    def _advance_state(self, c: dict, now: datetime) -> str:
        cur = c["status"]
        if cur == "sent":
            sent = self._parse_dt(c.get("sent_at"))
            if sent and (now - sent) > timedelta(hours=48):
                return "timeout"
            return "delivered"
        if cur == "delivered":
            deadline = self._parse_dt(c.get("deadline"))
            if deadline and now > deadline:
                return "timeout"
        return cur

    def _parse_dt(self, s: Any) -> datetime | None:
        if isinstance(s, datetime):
            return s
        if not isinstance(s, str):
            return None
        for f in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                return datetime.strptime(s, f)
            except ValueError:
                continue
        return None

    def _transition_reason(self, c: dict, new_state: str) -> str:
        reasons = {
            "delivered": "函证已送达",
            "timeout": "超过48小时未回函",
        }
        return reasons.get(new_state, "状态变更")

    def _reconcile(self, c: dict) -> list[dict]:
        audit = c.get("audit_values", {}) or {}
        bank = c.get("bank_values", {}) or {}
        diffs: list[dict] = []
        for key in set(list(audit.keys()) + list(bank.keys())):
            av = audit.get(key)
            bv = bank.get(key)
            if av is None and bv is None:
                continue
            if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
                if abs(av - bv) > 0.01:
                    pct = 0 if av == 0 else (bv - av) / abs(av) * 100
                    diffs.append({
                        "diff_type": "amount" if "balance" in key.lower() or "amount" in key.lower() else "other",
                        "field": key,
                        "audit_value": av,
                        "bank_value": bv,
                        "diff_value": round(bv - av, 2),
                        "diff_pct": round(pct, 2),
                        "detail": f"{key}: 审计方{av} vs 银行方{bv}，差异{bv - av:.2f}({pct:.2f}%)",
                    })
            elif av != bv:
                diffs.append({
                    "diff_type": "account" if any(k in key.lower() for k in ["account", "name", "account_number"]) else "other",
                    "field": key,
                    "audit_value": av,
                    "bank_value": bv,
                    "diff_value": None,
                    "diff_pct": None,
                    "detail": f"{key}: 审计方'{av}' vs 银行方'{bv}'",
                })
        return diffs

    def _check_escalation(self, c: dict, now: datetime) -> dict | None:
        sent = self._parse_dt(c.get("sent_at"))
        if not sent:
            return None
        hours = (now - sent).total_seconds() / 3600.0
        for rule in self.model["escalation_rules"]:
            if hours >= rule["after_hours"]:
                return {"level": rule["level"], "channel": rule["channel"], "hours": round(hours, 1)}
        return None

    def _postprocess(self, result: Any) -> Any:
        confs = result["confirmations"]
        total = len(confs)
        status_counts: dict[str, int] = {}
        for c in confs:
            status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
        reconciled = [c for c in confs if c["status"] == "reconciled"]
        with_diff = [c for c in confs if c["status"] == "difference"]
        result["dashboard"] = {
            "total": total,
            "status_counts": {self.model["status_meta"].get(k, k): v for k, v in status_counts.items()},
            "replied_count": status_counts.get("replied", 0) + len(reconciled) + len(with_diff),
            "diff_count": len(with_diff),
            "timeout_count": status_counts.get("timeout", 0),
            "escalations": len(result["escalations"]),
            "transition_count": len(result["transitions"]),
        }
        return result
