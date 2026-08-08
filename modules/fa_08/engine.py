from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict, Counter
import re, math, hashlib
from difflib import SequenceMatcher

from modules.shared.base_engine import AbstractEngine


class MLEngine(AbstractEngine):
    """FA-08 底稿自动勾稽检查引擎。

    核心：跨表/跨底稿金额勾稽一致性 + 数字间逻辑勾稽。
    规则库：
      1) 科目借贷平衡校验；
      2) 报表间勾稽（资产=负债+权益、现金流期末=资产负债期末现金）；
      3) 底稿 ↔ 凭证 ↔ 报表三方金额一致性；
      4) 异常波动检测（同比/环比 > 阈值）。
    """

    CONSISTENCY_RULES = [
        ("trial_balance", "借贷平衡", lambda d: abs(d.get("debit", 0) - d.get("credit", 0)) < 0.01),
        ("balance_sheet", "资产=负债+权益", lambda d: abs(
            d.get("assets", 0) - d.get("liabilities", 0) - d.get("equity", 0)) < 0.01),
        ("cash_flow", "现金流量期末=资产负债现金", lambda d: abs(
            d.get("cf_ending_cash", 0) - d.get("bs_cash", 0)) < 0.01),
        ("retained_earnings", "期末未分配利润=期初+净利润-分配", lambda d: abs(
            d.get("ending_re", 0) - d.get("begin_re", 0) - d.get("net_profit", 0)
            + d.get("dividend", 0)) < 0.01),
        ("inventory", "存货=原材料+在产品+产成品", lambda d: abs(
            d.get("inventory_total", 0) - d.get("raw", 0) - d.get("wip", 0) - d.get("fg", 0)) < 0.01),
        ("depreciation", "累计折旧期末=期初+本期计提-本期处置", lambda d: abs(
            d.get("dep_ending", 0) - d.get("dep_begin", 0) - d.get("dep_add", 0)
            + d.get("dep_dispose", 0)) < 0.01),
        ("payroll", "应付职工薪酬期末=期初+计提-发放", lambda d: abs(
            d.get("pay_ending", 0) - d.get("pay_begin", 0) - d.get("pay_accrue", 0)
            + d.get("pay_paid", 0)) < 0.01),
    ]

    ANOMALY_THRESHOLD = 0.3

    def __init__(self, name: str = "fa_08") -> None:
        super().__init__(name)
        self._rules: List[Tuple[str, str, Any]] = []

    def _load_model(self) -> None:
        self._rules = list(self.CONSISTENCY_RULES)

    def _preprocess(self, input_data: Any) -> Dict[str, Any]:
        data = input_data or {}
        if not isinstance(data, dict):
            data = {"workpapers": data}
        out = {
            "workpapers": data.get("workpapers", data.get("底稿", [])),
            "statements": data.get("statements", data.get("报表", {})),
            "vouchers": data.get("vouchers", data.get("凭证", [])),
            "metrics": data.get("metrics", data.get("指标", {})),
        }
        return out

    def _infer(self, prepared: Any) -> Any:
        results = []
        wp = prepared.get("workpapers", [])
        st = prepared.get("statements", {})
        vs = prepared.get("vouchers", [])
        metrics = prepared.get("metrics", {})

        # 1) 跨报表勾稽
        for rule_id, desc, checker in self._rules:
            payload = st.get(rule_id, {})
            try:
                ok = checker(payload)
            except Exception:
                ok = False
            if not ok:
                diff = self._rule_diff(rule_id, payload)
                results.append({
                    "check_id": rule_id,
                    "type": "consistency",
                    "description": desc,
                    "severity": "high" if rule_id in ("balance_sheet", "cash_flow", "retained_earnings") else "medium",
                    "diff_amount": diff,
                    "status": "FAIL",
                    "suggestion": f"复核{desc}相关科目明细",
                })

        # 2) 底稿 ↔ 凭证 一致性
        wp_by_id = {str(w.get("id", w.get("workpaper_id", ""))): w for w in wp}
        for v in vs:
            v_id = str(v.get("workpaper_id", ""))
            if v_id in wp_by_id:
                wp_amt = float(wp_by_id[v_id].get("amount", 0) or 0)
                v_amt = float(v.get("amount", 0) or 0)
                if abs(wp_amt - v_amt) > 0.01:
                    results.append({
                        "check_id": f"voucher_{v_id}",
                        "type": "cross_doc",
                        "description": f"底稿与凭证金额不一致 ({v_id})",
                        "severity": "high",
                        "diff_amount": round(v_amt - wp_amt, 2),
                        "status": "FAIL",
                        "suggestion": "核对底稿金额与原始凭证",
                    })

        # 3) 异常波动
        for m in metrics:
            cur = float(m.get("current", 0) or 0)
            prev = float(m.get("previous", 0) or 0)
            name = m.get("name", m.get("metric", "指标"))
            if prev == 0 and cur != 0:
                results.append(self._anomaly_result(name, cur, prev, 1.0, "new_appear"))
            elif prev != 0:
                pct = (cur - prev) / abs(prev)
                if abs(pct) > self.ANOMALY_THRESHOLD:
                    results.append(self._anomaly_result(name, cur, prev, pct, "volatility"))

        # 通过项
        passes = len(self._rules) - sum(1 for r in results if r["type"] == "consistency")
        for rule_id, desc, _ in self._rules:
            if not any(r["check_id"] == rule_id for r in results):
                results.append({
                    "check_id": rule_id,
                    "type": "consistency",
                    "description": desc,
                    "severity": "low",
                    "diff_amount": 0.0,
                    "status": "PASS",
                    "suggestion": "",
                })

        return results

    def _postprocess(self, result: Any) -> Any:
        items = result or []
        if not isinstance(items, list):
            items = []
        fails = [i for i in items if i["status"] == "FAIL"]
        passes = [i for i in items if i["status"] == "PASS"]
        severities = Counter(f["severity"] for f in fails)
        return {
            "items": items,
            "summary": {
                "total_checks": len(items),
                "pass_count": len(passes),
                "fail_count": len(fails),
                "pass_rate": round(len(passes) / max(1, len(items)), 3),
                "severity_distribution": dict(severities),
                "total_diff_amount": round(sum(abs(f.get("diff_amount", 0)) for f in fails), 2),
            },
            "critical_issues": [f for f in fails if f["severity"] == "high"],
            "adjustment_suggestions": self._adjustment_suggestions(fails),
        }

    # ── 辅助 ────────────────────────────────────────────────────────────────
    def _rule_diff(self, rule_id: str, payload: Dict[str, Any]) -> float:
        diff_map = {
            "trial_balance": lambda p: abs(p.get("debit", 0) - p.get("credit", 0)),
            "balance_sheet": lambda p: abs(p.get("assets", 0) - p.get("liabilities", 0) - p.get("equity", 0)),
            "cash_flow": lambda p: abs(p.get("cf_ending_cash", 0) - p.get("bs_cash", 0)),
            "retained_earnings": lambda p: abs(p.get("ending_re", 0) - p.get("begin_re", 0) - p.get("net_profit", 0) + p.get("dividend", 0)),
            "inventory": lambda p: abs(p.get("inventory_total", 0) - p.get("raw", 0) - p.get("wip", 0) - p.get("fg", 0)),
            "depreciation": lambda p: abs(p.get("dep_ending", 0) - p.get("dep_begin", 0) - p.get("dep_add", 0) + p.get("dep_dispose", 0)),
            "payroll": lambda p: abs(p.get("pay_ending", 0) - p.get("pay_begin", 0) - p.get("pay_accrue", 0) + p.get("pay_paid", 0)),
        }
        return round(diff_map.get(rule_id, lambda p: 0)(payload), 2)

    def _anomaly_result(self, name, cur, prev, pct, kind) -> Dict[str, Any]:
        return {
            "check_id": f"anomaly_{hashlib.md5(name.encode()).hexdigest()[:8]}",
            "type": "anomaly",
            "description": f"异常波动: {name}",
            "severity": "medium" if kind == "volatility" else "high",
            "diff_amount": round(cur - prev, 2),
            "change_pct": round(pct, 3),
            "status": "FAIL",
            "suggestion": f"复核{name}同比{round(pct*100,1)}%波动原因",
        }

    def _adjustment_suggestions(self, fails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tips = []
        for f in fails:
            if f["type"] == "consistency":
                tips.append({
                    "issue": f["description"],
                    "action": f["suggestion"],
                    "expected_diff": f["diff_amount"],
                })
        return tips
