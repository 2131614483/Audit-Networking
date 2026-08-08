"""[FA-12] engine 单测：交易识别 / 文本抽取 / 差集构建 / 合规规则 / 完整性评分。

unittest 风格（不依赖 pytest），覆盖 _load_model / _preprocess / _infer /
_postprocess 及核心匹配辅助方法。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.fa_12.engine import KGEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def _make_engine() -> KGEngine:
    """构造 engine 并显式触发 _load_model（编译关联方识别正则）。"""
    eng = KGEngine("fa_12")
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：关联方识别正则编译。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_hints_compiled(self):
        """_load_model 后 _hints 含编译后的正则对象。"""
        self.assertTrue(self.engine._hints)
        import re
        for p in self.engine._hints:
            self.assertIsInstance(p, re.Pattern)

    def test_hints_count_matches_definitions(self):
        """_hints 数量与 RELATED_PARTY_HINTS 一致。"""
        self.assertEqual(
            len(self.engine._hints), len(KGEngine.RELATED_PARTY_HINTS)
        )

    def test_disclosure_rules_count(self):
        """DISCLOSURE_RULES 含 8 条规则。"""
        self.assertEqual(len(KGEngine.DISCLOSURE_RULES), 8)

    def test_disclosure_rules_required_fields(self):
        """5 个必填字段：identifier/relationship/transaction_type/transaction_amount/outstanding_balance。"""
        required = {r[0] for r in KGEngine.DISCLOSURE_RULES if r[2]}
        self.assertEqual(required, {
            "identifier", "relationship", "transaction_type",
            "transaction_amount", "outstanding_balance",
        })

    def test_setup_returns_engine(self):
        """setup 返回 self，支持链式调用。"""
        eng = KGEngine("fa_12")
        self.assertIs(eng.setup(), eng)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据清洗与归一化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_preprocess_english_keys(self):
        """英文键 transactions/disclosure_text/related_parties 正确解析。"""
        prepared = self.engine._preprocess({
            "transactions": [
                {"tx_id": "T1", "related_party": "甲公司", "tx_type": "采购",
                 "amount": 1000, "outstanding": 200},
            ],
            "disclosure_text": "披露内容",
            "related_parties": ["甲公司"],
        })
        self.assertEqual(len(prepared["transactions"]), 1)
        self.assertEqual(prepared["transactions"][0]["amount"], 1000.0)
        self.assertEqual(prepared["disclosure_text"], "披露内容")
        self.assertEqual(prepared["declared_parties"], ["甲公司"])

    def test_preprocess_chinese_keys(self):
        """中文键 交易/披露文本/关联方清单 兼容。"""
        prepared = self.engine._preprocess({
            "交易": [{"关联方": "乙公司", "交易类型": "销售", "交易金额": "500"}],
            "披露文本": "披露内容",
            "关联方清单": ["乙公司"],
        })
        self.assertEqual(prepared["transactions"][0]["related_party"], "乙公司")
        self.assertEqual(prepared["transactions"][0]["amount"], 500.0)
        self.assertEqual(prepared["transactions"][0]["tx_type"], "销售")

    def test_preprocess_tx_id_generated_when_missing(self):
        """缺 tx_id 时按 md5 生成 8 位标识。"""
        prepared = self.engine._preprocess({
            "transactions": [{"related_party": "丙公司"}],
        })
        tx_id = prepared["transactions"][0]["tx_id"]
        self.assertEqual(len(tx_id), 8)

    def test_preprocess_non_dict_input(self):
        """非 dict 输入包装为 {transactions: data}。"""
        prepared = self.engine._preprocess([{"tx_id": "T1"}])
        self.assertEqual(len(prepared["transactions"]), 1)

    def test_preprocess_scalar_parties_wrapped(self):
        """标量关联方清单包装为列表。"""
        prepared = self.engine._preprocess({
            "transactions": [],
            "related_parties": "单个公司",
        })
        self.assertEqual(prepared["declared_parties"], ["单个公司"])

    def test_preprocess_amount_string(self):
        """金额字符串转 float。"""
        prepared = self.engine._preprocess({
            "transactions": [{"amount": "1234.5"}],
        })
        self.assertEqual(prepared["transactions"][0]["amount"], 1234.5)


class TestEngineTxInDisclosure(unittest.TestCase):
    """_tx_in_disclosure：交易在披露文本中的识别。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_name_exact_match(self):
        """关联方名称在文本中 → True。"""
        tx = {"related_party": "母公司甲", "tx_type": "采购", "amount": 1000}
        self.assertTrue(
            self.engine._tx_in_disclosure(tx, "与母公司甲的采购", [])
        )

    def test_name_not_in_text_no_match(self):
        """关联方名称不在文本且无模糊匹配 → False。"""
        tx = {"related_party": "未知公司", "tx_type": "采购", "amount": 1000}
        self.assertFalse(
            self.engine._tx_in_disclosure(tx, "与母公司甲的采购", [])
        )

    def test_fuzzy_match_via_declared(self):
        """关联方与 declared 模糊匹配 >0.7 且 declared 在文本中 → True。"""
        # "母公司甲有限"(6) vs "母公司甲"(4)：ratio=2*4/(6+4)=0.8 > 0.7
        tx = {"related_party": "母公司甲有限", "tx_type": "采购", "amount": 0}
        self.assertTrue(
            self.engine._tx_in_disclosure(
                tx, "与母公司甲的交易", ["母公司甲"]
            )
        )

    def test_type_and_amount_match(self):
        """类型+金额同时在文本中 → True（无关联方名称时）。"""
        tx = {"related_party": "", "tx_type": "采购", "amount": 1000.0}
        self.assertTrue(
            self.engine._tx_in_disclosure(tx, "采购业务金额1000", [])
        )

    def test_no_match_when_amount_absent(self):
        """类型在文本但金额不在 → False。"""
        tx = {"related_party": "", "tx_type": "采购", "amount": 9999.0}
        self.assertFalse(
            self.engine._tx_in_disclosure(tx, "采购业务", [])
        )


class TestEngineMandatoryFields(unittest.TestCase):
    """_check_mandatory_fields / _tx_missing_fields。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_complete_disclosure_no_missing(self):
        """完整披露文本 → 无文档级缺失必填字段。"""
        disc = "与母公司甲的采购，交易金额1000元，期末应付账款余额200，关联自然人。"
        missing = self.engine._check_mandatory_fields(disc, [])
        self.assertEqual(missing, [])

    def test_missing_relationship_field(self):
        """缺失关联关系关键词 → 缺 relationship 字段。"""
        disc = "与某公司的采购，交易金额1000元，期末余额200。"
        missing = self.engine._check_mandatory_fields(disc, [])
        field_ids = {m["field_id"] for m in missing}
        self.assertIn("relationship", field_ids)

    def test_tx_missing_amount_field(self):
        """已匹配交易金额未在文本 → 缺交易金额字段。"""
        tx = {"related_party": "甲公司", "tx_type": "采购", "amount": 9999.0}
        disc = "甲公司采购业务"
        missing = self.engine._tx_missing_fields(tx, disc)
        self.assertIn("交易金额", missing)

    def test_tx_no_missing_when_complete(self):
        """交易各要素均在文本 → 无缺失字段。"""
        tx = {"related_party": "甲公司", "tx_type": "采购", "amount": 1000.0}
        disc = "甲公司采购交易金额1000"
        missing = self.engine._tx_missing_fields(tx, disc)
        self.assertEqual(missing, [])


class TestEngineSeverity(unittest.TestCase):
    """_severity：严重度分级。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_high_for_very_large_amount(self):
        """金额 > 5000万 → high。"""
        tx = {"amount": 60_000_000, "relationship": "联营"}
        self.assertEqual(self.engine._severity(tx), "high")

    def test_high_for_controlling_shareholder_large_amount(self):
        """控股股东 + 金额>500万 → high。"""
        tx = {"amount": 6_000_000, "relationship": "控股股东"}
        self.assertEqual(self.engine._severity(tx), "high")

    def test_medium_for_million_amount(self):
        """金额 > 100万 → medium。"""
        tx = {"amount": 3_000_000, "relationship": "联营"}
        self.assertEqual(self.engine._severity(tx), "medium")

    def test_low_for_small_amount(self):
        """金额 ≤ 100万 → low。"""
        tx = {"amount": 500_000, "relationship": "关联自然人"}
        self.assertEqual(self.engine._severity(tx), "low")


class TestEngineCompletenessAndReason(unittest.TestCase):
    """_completeness_score / _undisclose_reason / _suggest。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_completeness_all_ok(self):
        """全部合规 → 100。"""
        self.assertEqual(self.engine._completeness_score(5, 0, 0), 100.0)

    def test_completeness_all_undisclosed(self):
        """全部未披露 → 0。"""
        self.assertEqual(self.engine._completeness_score(0, 0, 5), 0.0)

    def test_completeness_mixed(self):
        """1 OK + 1 PARTIAL + 3 UNDISCLOSED → (1+0.6)/5*100=32。"""
        self.assertEqual(self.engine._completeness_score(1, 1, 3), 32.0)

    def test_completeness_empty(self):
        """无交易 → 100。"""
        self.assertEqual(self.engine._completeness_score(0, 0, 0), 100.0)

    def test_undisclose_reason_amount_and_relationship(self):
        """金额与关联关系均未披露。"""
        tx = {"related_party": "甲公司", "amount": 1000.0, "relationship": "母公司"}
        reason = self.engine._undisclose_reason(tx, "无关内容")
        self.assertIn("交易金额未披露", reason)
        self.assertIn("关联关系类型未披露", reason)

    def test_undisclose_reason_no_party(self):
        """未声明关联方名称。"""
        tx = {"related_party": "", "amount": 0.0, "relationship": ""}
        reason = self.engine._undisclose_reason(tx, "无关内容")
        self.assertIn("未声明关联方名称", reason)

    def test_suggest_controlling_shareholder(self):
        """控股股东建议立即补充披露。"""
        tx = {"related_party": "控股股东丁", "relationship": "控股股东",
              "tx_type": "资金占用"}
        s = self.engine._suggest(tx)
        self.assertIn("立即补充披露", s)

    def test_suggest_other_party(self):
        """非控股股东建议补充交易明细。"""
        tx = {"related_party": "关联方丙", "relationship": "联营",
              "tx_type": "担保"}
        s = self.engine._suggest(tx)
        self.assertIn("补充", s)


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：汇总与统计。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_fixture("sample_input.json")
        self.result = self.engine.execute(self.sample)

    def test_result_has_required_keys(self):
        """输出含 items / summary / high_risk_items / remediation_plan。"""
        for key in ("items", "summary", "high_risk_items", "remediation_plan"):
            self.assertIn(key, self.result)

    def test_summary_counts(self):
        """fully=1 / partial=1 / undisclosed=3。"""
        s = self.result["summary"]
        self.assertEqual(s["fully_disclosed"], 1)
        self.assertEqual(s["partially_disclosed"], 1)
        self.assertEqual(s["undisclosed"], 3)

    def test_completeness_score(self):
        """completeness_score = 32.0。"""
        self.assertEqual(self.result["summary"]["completeness_score"], 32.0)

    def test_undisclosed_amount(self):
        """undisclosed_amount = 3M+60M+0.5M = 63.5M。"""
        self.assertAlmostEqual(
            self.result["summary"]["undisclosed_amount"], 63_500_000.0, places=2
        )

    def test_high_risk_items_contains_d04(self):
        """high_risk_items 含 TX-D04（控股股东大额未披露）。"""
        tx_ids = {i["tx_id"] for i in self.result["high_risk_items"]}
        self.assertIn("TX-D04", tx_ids)

    def test_remediation_plan_has_p0(self):
        """remediation_plan 含 P0 优先级（TX-D04 高严重度）。"""
        priorities = {s["priority"] for s in self.result["remediation_plan"]}
        self.assertIn("P0", priorities)

    def test_items_status_distribution(self):
        """条目状态分布：3 UNDISCLOSED + 1 PARTIAL + 1 OK。"""
        statuses = [i["status"] for i in self.result["items"]]
        self.assertEqual(statuses.count("UNDISCLOSED"), 3)
        self.assertEqual(statuses.count("PARTIAL"), 1)
        self.assertEqual(statuses.count("OK"), 1)


class TestEngineFixtureConsistency(unittest.TestCase):
    """与 expected_output.json 一致性。"""

    def setUp(self):
        self.engine = _make_engine()
        self.sample = _load_fixture("sample_input.json")
        self.expected = _load_fixture("expected_output.json")

    def test_items_count_matches_expected(self):
        """engine 输出条目数与 expected 一致（5）。"""
        result = self.engine.execute(self.sample)
        self.assertEqual(len(result["items"]), len(self.expected["items"]))

    def test_tx_ids_match_expected(self):
        """条目 ID 顺序与 expected 一致。"""
        result = self.engine.execute(self.sample)
        got = [i["tx_id"] for i in result["items"]]
        want = [i["tx_id"] for i in self.expected["items"]]
        self.assertEqual(got, want)

    def test_status_match_expected(self):
        """每条目 status 与 expected 一致。"""
        result = self.engine.execute(self.sample)
        for got, want in zip(result["items"], self.expected["items"]):
            self.assertEqual(got["status"], want["status"])
            self.assertEqual(got["severity"], want["severity"])

    def test_completeness_matches_expected(self):
        """completeness_score 与 expected 一致。"""
        result = self.engine.execute(self.sample)
        self.assertEqual(
            result["summary"]["completeness_score"],
            self.expected["summary"]["completeness_score"],
        )


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_input(self):
        """空输入 → 0 交易，完整性 100。"""
        result = self.engine.execute({"transactions": []})
        self.assertEqual(result["summary"]["total_transactions"], 0)
        self.assertEqual(result["summary"]["completeness_score"], 100.0)
        self.assertEqual(result["items"], [])

    def test_all_disclosed(self):
        """全部披露完整 → completeness=100。"""
        result = self.engine.execute({
            "transactions": [
                {"tx_id": "T1", "related_party": "甲公司", "tx_type": "采购",
                 "amount": 1000.0},
            ],
            "disclosure_text": "甲公司采购交易金额1000",
        })
        self.assertEqual(result["summary"]["completeness_score"], 100.0)
        self.assertEqual(result["items"][0]["status"], "OK")

    def test_all_undisclosed(self):
        """全部未披露 → completeness=0。"""
        result = self.engine.execute({
            "transactions": [
                {"tx_id": "T1", "related_party": "未知公司", "tx_type": "担保",
                 "amount": 1000.0},
            ],
            "disclosure_text": "无关内容",
        })
        self.assertEqual(result["summary"]["completeness_score"], 0.0)
        self.assertEqual(result["items"][0]["status"], "UNDISCLOSED")

    def test_no_disclosure_text(self):
        """披露文本为空 → 全部未披露。"""
        result = self.engine.execute({
            "transactions": [
                {"tx_id": "T1", "related_party": "甲公司", "amount": 1000.0},
            ],
            "disclosure_text": "",
        })
        self.assertEqual(result["summary"]["undisclosed"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
