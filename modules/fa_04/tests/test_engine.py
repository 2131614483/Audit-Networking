"""[FA-04] engine 单测：状态机推进 / 回函比对 / 催函预警 / 仪表板。

unittest 风格（不依赖 pytest）。每个用例构造独立 engine，时间戳相对 now 计算
以保证状态机判定确定性。
"""
from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timedelta

from modules.fa_04.engine import (
    BlockchainEngine,
    STATE_FLOW,
    STATUS_META,
    TEMPLATE_BANK,
    TEMPLATE_TRADE,
    TEMPLATE_LAWYER,
)


def _make_engine(**overrides) -> BlockchainEngine:
    config = {"threshold": {"confidence": 0.9}}
    config.update(overrides)
    eng = BlockchainEngine(config=config)
    eng.setup()
    return eng


def _hours_ago(hours: float) -> str:
    return (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")


def _days_ago_iso(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：状态机 / 模板库 / 催函规则加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_model_has_state_flow(self):
        """状态机含 draft / sent / replied / closed 等核心状态。"""
        sf = self.engine.model["state_flow"]
        for key in ("draft", "sent", "delivered", "replied", "reconciled",
                    "closed", "timeout", "difference"):
            self.assertIn(key, sf)

    def test_model_has_three_templates(self):
        """模板库含银行 / 往来 / 律师三类函证模板。"""
        tpls = self.engine.model["templates"]
        self.assertEqual(len(tpls), 3)
        ids = {t["template_id"] for t in tpls}
        self.assertIn("TPL-BANK-001", ids)
        self.assertIn("TPL-TRADE-001", ids)
        self.assertIn("TPL-LAW-001", ids)

    def test_model_has_escalation_rules(self):
        """催函规则为 48h/72h/120h 阶梯。"""
        rules = self.engine.model["escalation_rules"]
        self.assertEqual(len(rules), 3)
        hours = [r["after_hours"] for r in rules]
        self.assertEqual(hours, [48, 72, 120])

    def test_model_has_diff_assign_mapping(self):
        """差异分派映射含 amount / account 分派对象。"""
        assign = self.engine.model["diff_assign"]
        self.assertIn("amount", assign)
        self.assertIn("account", assign)
        self.assertEqual(assign["amount"], "审计师A")
        self.assertEqual(assign["account"], "审计师B")

    def test_state_flow_closed_is_terminal(self):
        """closed / cancelled 为终态（无可流转状态）。"""
        self.assertEqual(STATE_FLOW["closed"], [])
        self.assertEqual(STATE_FLOW["cancelled"], [])


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：函证记录标准化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_preprocess_requires_dict(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess(["not", "a", "dict"])

    def test_preprocess_normalizes_confirmations(self):
        """函证字段标准化：confirmation_id 默认生成、bank_or_counterparty 合并。"""
        prepared = self.engine._preprocess({"confirmations": [
            {"bank_name": "工行", "account_number": "123", "status": "sent"},
            {"counterparty": "客户丙", "type": "trade"},
        ]})
        confs = prepared["confirmations"]
        self.assertEqual(len(confs), 2)
        self.assertEqual(confs[0]["confirmation_id"], "CF-0001")
        self.assertEqual(confs[0]["bank_or_counterparty"], "工行")
        self.assertEqual(confs[0]["status"], "sent")
        self.assertEqual(confs[1]["confirmation_id"], "CF-0002")
        self.assertEqual(confs[1]["bank_or_counterparty"], "客户丙")
        self.assertIn("now", prepared)

    def test_preprocess_computes_audit_values_hash(self):
        """audit_values_hash 为 16 位十六进制。"""
        prepared = self.engine._preprocess({"confirmations": [
            {"audit_values": {"balance": 100}},
        ]})
        h = prepared["confirmations"][0]["audit_values_hash"]
        self.assertEqual(len(h), 16)
        expected = hashlib.sha256(
            json.dumps({"balance": 100}, sort_keys=True, default=str,
                       ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        self.assertEqual(h, expected)

    def test_preprocess_template_matching(self):
        """type → 模板匹配：bank/trade/lawyer。"""
        prepared = self.engine._preprocess({"confirmations": [
            {"type": "bank"}, {"type": "trade"}, {"type": "lawyer"}, {"type": "unknown"},
        ]})
        tpls = [c["template"]["template_id"] for c in prepared["confirmations"]]
        self.assertEqual(tpls, ["TPL-BANK-001", "TPL-TRADE-001", "TPL-LAW-001", "TPL-BANK-001"])

    def test_preprocess_skips_non_dict_entries(self):
        """非 dict 条目被跳过。"""
        prepared = self.engine._preprocess({"confirmations": [
            {"bank_name": "工行"}, "invalid", None, {"counterparty": "X"},
        ]})
        self.assertEqual(len(prepared["confirmations"]), 2)


class TestEngineStateMachine(unittest.TestCase):
    """_infer 状态机推进。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_sent_to_delivered_within_48h(self):
        """sent 20h → delivered（未超 48h）。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "sent", "sent_at": _hours_ago(20)},
        ]})
        self.assertEqual(result["confirmations"][0]["status"], "delivered")
        self.assertEqual(len(result["transitions"]), 1)
        self.assertEqual(result["transitions"][0]["to"], "delivered")

    def test_sent_to_timeout_after_48h(self):
        """sent 50h → timeout（超 48h）。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "sent", "sent_at": _hours_ago(50)},
        ]})
        self.assertEqual(result["confirmations"][0]["status"], "timeout")
        self.assertEqual(result["transitions"][0]["to"], "timeout")
        self.assertEqual(result["transitions"][0]["reason"], "超过48小时未回函")

    def test_delivered_to_timeout_past_deadline(self):
        """delivered 且 deadline 已过 → timeout（无 sent_at 不触发催函）。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "delivered",
             "deadline": (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")},
        ]})
        self.assertEqual(result["confirmations"][0]["status"], "timeout")
        self.assertEqual(len(result["escalations"]), 0)

    def test_replied_to_reconciled_no_diff(self):
        """replied 且审计值与银行值一致 → reconciled。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "replied",
             "audit_values": {"balance": 1000}, "bank_values": {"balance": 1000}},
        ]})
        self.assertEqual(result["confirmations"][0]["status"], "reconciled")
        self.assertEqual(result["confirmations"][0]["diff_records"], [])
        self.assertEqual(len(result["reconciliations"]), 0)

    def test_draft_stays_draft(self):
        """draft 状态保持不变。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "draft"},
        ]})
        self.assertEqual(result["confirmations"][0]["status"], "draft")
        self.assertEqual(len(result["transitions"]), 0)

    def test_closed_stays_closed(self):
        """closed 终态保持不变。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "closed"},
        ]})
        self.assertEqual(result["confirmations"][0]["status"], "closed")


class TestEngineReconcile(unittest.TestCase):
    """_reconcile：回函逐字段差异识别。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_reconcile_no_difference(self):
        """审计值与银行值一致 → 无差异。"""
        diffs = self.engine._reconcile({
            "audit_values": {"balance": 1000, "account_name": "A"},
            "bank_values": {"balance": 1000, "account_name": "A"},
        })
        self.assertEqual(diffs, [])

    def test_reconcile_balance_difference(self):
        """balance 数值差异 → diff_type=amount。"""
        diffs = self.engine._reconcile({
            "audit_values": {"balance": 1000},
            "bank_values": {"balance": 900},
        })
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["diff_type"], "amount")
        self.assertEqual(diffs[0]["field"], "balance")
        self.assertEqual(diffs[0]["audit_value"], 1000)
        self.assertEqual(diffs[0]["bank_value"], 900)

    def test_reconcile_account_name_difference(self):
        """account_name 非数值差异 → diff_type=account。"""
        diffs = self.engine._reconcile({
            "audit_values": {"account_name": "客户A"},
            "bank_values": {"account_name": "客户B"},
        })
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["diff_type"], "account")
        self.assertIsNone(diffs[0]["diff_value"])
        self.assertIsNone(diffs[0]["diff_pct"])

    def test_reconcile_diff_value_and_pct(self):
        """差异值与差异百分比正确计算。"""
        diffs = self.engine._reconcile({
            "audit_values": {"balance": 1500000},
            "bank_values": {"balance": 1480000},
        })
        d = diffs[0]
        self.assertEqual(d["diff_value"], -20000.0)
        self.assertAlmostEqual(d["diff_pct"], -1.33, places=2)

    def test_reconcile_assigns_to_correct_auditor(self):
        """差异分派：amount→审计师A，account→审计师B。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "CA", "status": "replied",
             "audit_values": {"balance": 100}, "bank_values": {"balance": 90}},
            {"confirmation_id": "CB", "status": "replied",
             "audit_values": {"account_name": "X"}, "bank_values": {"account_name": "Y"}},
        ]})
        rec = {r["confirmation_id"]: r for r in result["reconciliations"]}
        self.assertEqual(rec["CA"]["assignee"], "审计师A")
        self.assertEqual(rec["CB"]["assignee"], "审计师B")


class TestEngineEscalation(unittest.TestCase):
    """催函预警逻辑。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_escalation_triggered_after_48h(self):
        """sent 50h → 超时 + 催函（level 1, email）。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "sent", "sent_at": _hours_ago(50),
             "bank_name": "工行"},
        ]})
        self.assertEqual(len(result["escalations"]), 1)
        esc = result["escalations"][0]
        self.assertEqual(esc["confirmation_id"], "C1")
        self.assertEqual(esc["level"], 1)
        self.assertEqual(esc["channel"], "email")
        self.assertGreater(esc["hours_elapsed"], 48)

    def test_no_escalation_within_48h(self):
        """sent 20h → delivered，无催函。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "sent", "sent_at": _hours_ago(20)},
        ]})
        self.assertEqual(len(result["escalations"]), 0)

    def test_escalation_no_sent_at(self):
        """无 sent_at → 不触发催函。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "delivered"},
        ]})
        self.assertEqual(len(result["escalations"]), 0)

    def test_check_escalation_direct_returns_level1(self):
        """_check_escalation：hours>=48 返回 level 1。"""
        now = datetime.now()
        c = {"sent_at": _hours_ago(80)}
        esc = self.engine._check_escalation(c, now)
        self.assertIsNotNone(esc)
        self.assertEqual(esc["level"], 1)

    def test_check_escalation_returns_none_when_no_sent_at(self):
        """_check_escalation：无 sent_at 返回 None。"""
        self.assertIsNone(self.engine._check_escalation({}, datetime.now()))


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：仪表板统计。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_dashboard_total_and_status_counts(self):
        """dashboard.total 与 status_counts 一致。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "replied",
             "audit_values": {"balance": 1}, "bank_values": {"balance": 1}},
            {"confirmation_id": "C2", "status": "draft"},
        ]})
        dash = result["dashboard"]
        self.assertEqual(dash["total"], 2)
        self.assertIn("已核对", dash["status_counts"])

    def test_dashboard_diff_count(self):
        """diff_count 等于 difference 状态函证数。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "replied",
             "audit_values": {"balance": 100}, "bank_values": {"balance": 90}},
            {"confirmation_id": "C2", "status": "replied",
             "audit_values": {"balance": 100}, "bank_values": {"balance": 100}},
        ]})
        self.assertEqual(result["dashboard"]["diff_count"], 1)

    def test_dashboard_replied_count_includes_reconciled_and_diff(self):
        """replied_count = 已核对 + 有差异。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "replied",
             "audit_values": {"balance": 100}, "bank_values": {"balance": 100}},
            {"confirmation_id": "C2", "status": "replied",
             "audit_values": {"balance": 100}, "bank_values": {"balance": 90}},
        ]})
        self.assertEqual(result["dashboard"]["replied_count"], 2)

    def test_dashboard_timeout_count(self):
        """timeout_count 等于超时函证数。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "sent", "sent_at": _hours_ago(50)},
            {"confirmation_id": "C2", "status": "draft"},
        ]})
        self.assertEqual(result["dashboard"]["timeout_count"], 1)


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_confirmations(self):
        """空函证列表 → total=0。"""
        result = self.engine.execute({"confirmations": []})
        self.assertEqual(result["dashboard"]["total"], 0)
        self.assertEqual(result["dashboard"]["replied_count"], 0)

    def test_invalid_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute(["not", "dict"])

    def test_missing_confirmations_key(self):
        """缺少 confirmations 键 → 空列表处理。"""
        result = self.engine.execute({"foo": "bar"})
        self.assertEqual(result["dashboard"]["total"], 0)

    def test_execute_full_flow_returns_dashboard(self):
        """完整 execute 返回含 dashboard / confirmations / transitions。"""
        result = self.engine.execute({"confirmations": [
            {"confirmation_id": "C1", "status": "sent", "sent_at": _hours_ago(50),
             "bank_name": "工行"},
        ]})
        self.assertIn("dashboard", result)
        self.assertIn("confirmations", result)
        self.assertIn("transitions", result)
        self.assertIn("escalations", result)
        self.assertIn("reconciliations", result)

    def test_audit_values_hash_stable(self):
        """相同 audit_values 产生相同 hash。"""
        p1 = self.engine._preprocess({"confirmations": [
            {"audit_values": {"balance": 1, "name": "A"}}]})
        p2 = self.engine._preprocess({"confirmations": [
            {"audit_values": {"name": "A", "balance": 1}}]})
        self.assertEqual(p1["confirmations"][0]["audit_values_hash"],
                         p2["confirmations"][0]["audit_values_hash"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
