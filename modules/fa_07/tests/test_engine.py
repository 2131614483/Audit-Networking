"""[FA-07] engine 单测：模板匹配 / 数据填入 / 结论生成 / 交叉引用 / 完成度。

unittest 风格（不依赖 pytest）。每个测试用独立临时 PortableDB 隔离，避免持久化污染。
模板与审计数据 fixtures 来自 modules/fa_07/tests/fixtures/。
Windows 下测试结束前显式 eng.close() 释放 db 文件句柄，避免 PermissionError。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from modules.fa_07.engine import KGEngine, _resolve_path, _eval_rule

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _bank_subject() -> dict:
    return {
        "subject_code": "1002", "subject_name": "银行存款",
        "category": "asset_current", "balance": 12000000,
        "detail": {"bank_name": "工商银行中关村支行",
                   "bank_account_no": "6222020100012345678", "account_count": 3},
    }


def _ar_subject() -> dict:
    return {
        "subject_code": "1122", "subject_name": "应收账款",
        "category": "asset_current", "balance": 8800000,
        "detail": {"aging": {"within_1y": 8200000, "one_to_2y": 400000,
                             "two_to_3y": 150000, "over_3y": 50000,
                             "within_1y_ratio": 0.9318},
                   "top_customer": "甲科技有限公司", "top_customer_amount": 3200000,
                   "customer_count": 42},
    }


class EngineUnitTest(unittest.TestCase):
    """engine 核心能力单测。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._engines: list[KGEngine] = []
        # addCleanup 为 LIFO：后注册先执行 → 先关连接再删目录，避免 PermissionError
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._close_engines)

    def _close_engines(self) -> None:
        for eng in self._engines:
            try:
                eng.close()
            except Exception:
                pass

    def _make_engine(self, threshold: float = 0.85, **overrides) -> KGEngine:
        """构造隔离 db 的 engine 并加载模型（fixtures 用项目默认）。"""
        config = {
            "threshold": {"confidence": threshold},
            "db_path": str(Path(self._tmp.name) / "fa_07_engine.db"),
            "fixtures_dir": str(_FIXTURES),
        }
        config.update(overrides)
        eng = KGEngine(config=config)
        eng.setup()
        self._engines.append(eng)
        return eng

    # ------------------------------------------------------------------
    # ① 模板匹配
    # ------------------------------------------------------------------
    def test_template_matching_bank_deposits(self) -> None:
        """银行存款科目匹配「函证」+「余额表」两个底稿模板。"""
        eng = self._make_engine()
        prepared = eng._preprocess({
            "entity": {"name": "测试公司"},
            "period": {"name": "2024年度", "end": "2024-12-31"},
            "subjects": [_bank_subject()],
        })
        matched = eng._match_templates(prepared["subjects"][0], eng.model["templates"])
        tids = {t["template_id"] for t in matched}
        self.assertIn("tmpl_bank_confirm", tids)
        self.assertIn("tmpl_bank_balance", tids)
        self.assertGreaterEqual(len(matched), 2)

    def test_template_matching_one_subject_multiple_templates(self) -> None:
        """应收账款科目匹配账龄/函证/余额表三个模板。"""
        eng = self._make_engine()
        prepared = eng._preprocess({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [_ar_subject()],
        })
        matched = eng._match_templates(prepared["subjects"][0], eng.model["templates"])
        tids = {t["template_id"] for t in matched}
        self.assertIn("tmpl_ar_aging", tids)
        self.assertIn("tmpl_ar_confirm", tids)
        self.assertIn("tmpl_ar_balance", tids)

    # ------------------------------------------------------------------
    # ② 数据填入
    # ------------------------------------------------------------------
    def test_data_filling_placeholders(self) -> None:
        """占位符从 context 点分路径正确取值并填入模板。"""
        eng = self._make_engine()
        result = eng.execute({
            "entity": {"name": "智源科技有限公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [_bank_subject()],
        })
        wp = next(w for w in result["workpapers"]
                  if w["template_id"] == "tmpl_bank_confirm")
        filled = wp["placeholders_filled"]
        self.assertEqual(filled["entity_name"], "智源科技有限公司")
        self.assertEqual(filled["bank_name"], "工商银行中关村支行")
        self.assertEqual(filled["bank_deposits_balance"], 12000000)
        self.assertIn("工商银行中关村支行", wp["filled_content"])
        self.assertIn("12000000", wp["filled_content"])

    def test_missing_placeholder_marked(self) -> None:
        """缺失字段以「【待补充】」兜底，并记入 placeholders_missing。"""
        eng = self._make_engine()
        subj = _bank_subject()
        subj["detail"]["bank_account_no"] = None  # 制造缺失
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [subj],
        })
        wp = next(w for w in result["workpapers"]
                  if w["template_id"] == "tmpl_bank_confirm")
        self.assertIn("bank_account_no", wp["placeholders_missing"])
        self.assertIn("【待补充】", wp["filled_content"])

    # ------------------------------------------------------------------
    # ③ 结论生成
    # ------------------------------------------------------------------
    def test_conclusion_aging_ok_and_warning(self) -> None:
        """应收账款账龄：1年内占比≥0.9 命中 ok，3年以上>0 命中 warning（取最严重）。"""
        eng = self._make_engine()
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [_ar_subject()],
        })
        wp = next(w for w in result["workpapers"]
                  if w["template_id"] == "tmpl_ar_aging")
        hit_paths = {r["metric_path"] for r in wp["conclusion_rules_hit"]}
        self.assertIn("subject.detail.aging.within_1y_ratio", hit_paths)
        self.assertIn("subject.detail.aging.over_3y", hit_paths)
        # 取最严重 → warning（因 over_3y>0）
        self.assertEqual(wp["conclusion_severity"], "warning")
        self.assertIn("可回收性良好", wp["conclusion"])
        self.assertIn("坏账准备", wp["conclusion"])

    def test_conclusion_no_rules_hit(self) -> None:
        """未命中任何规则时给出人工判断提示。"""
        eng = self._make_engine()
        # 应收账款余额表模板只有一条 balance>0 的 ok 规则，会命中；改用余额为 0 避免命中
        subj = _ar_subject()
        subj["balance"] = 0
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [subj],
        })
        wp = next(w for w in result["workpapers"]
                  if w["template_id"] == "tmpl_ar_balance")
        self.assertEqual(wp["conclusion"], "未命中结论规则，需人工判断。")

    # ------------------------------------------------------------------
    # ④ 交叉引用
    # ------------------------------------------------------------------
    def test_cross_reference_linked(self) -> None:
        """应收账款账龄底稿引用余额表/函证底稿，被引用模板已生成 → linked。"""
        eng = self._make_engine()
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [_ar_subject()],
        })
        wp = next(w for w in result["workpapers"]
                  if w["template_id"] == "tmpl_ar_aging")
        ref_statuses = {r["to_template_id"]: r["status"]
                        for r in wp["cross_references"]}
        self.assertEqual(ref_statuses.get("tmpl_ar_balance"), "linked")
        self.assertEqual(ref_statuses.get("tmpl_ar_confirm"), "linked")
        # 全局交叉引用列表非空
        self.assertGreater(len(result["cross_references"]), 0)

    def test_cross_reference_broken_when_target_missing(self) -> None:
        """被引用模板对应科目缺失未生成底稿 → broken。"""
        eng = self._make_engine()
        # 仅提供库存现金科目 → 其 cross_refs 指向 tmpl_bank_balance（银行存款未生成）
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [{
                "subject_code": "1001", "subject_name": "库存现金",
                "category": "asset_current", "balance": 50000,
                "detail": {"cash_counted": None},
            }],
        })
        cash_wp = next(w for w in result["workpapers"]
                       if w["template_id"] == "tmpl_cash_count")
        broken = [r for r in cash_wp["cross_references"] if r["status"] == "broken"]
        self.assertTrue(any(r["to_template_id"] == "tmpl_bank_balance" for r in broken))
        self.assertGreater(result["statistics"]["broken_refs"], 0)

    # ------------------------------------------------------------------
    # 完成度与统计
    # ------------------------------------------------------------------
    def test_completeness_warning_lowers(self) -> None:
        """warning 命中数越多完成度越低，且低于 0.85。"""
        eng = self._make_engine()
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [_ar_subject()],  # 账龄底稿 1 warning → 0.8
        })
        wp = next(w for w in result["workpapers"]
                  if w["template_id"] == "tmpl_ar_aging")
        self.assertLess(wp["completeness"], 0.85)
        # 余额表底稿 0 warning → 1.0
        bal = next(w for w in result["workpapers"]
                   if w["template_id"] == "tmpl_ar_balance")
        self.assertEqual(bal["completeness"], 1.0)

    def test_statistics_present(self) -> None:
        """execute 结果含 statistics 字段，关键字段齐全。"""
        eng = self._make_engine()
        result = eng.execute({
            "entity": {"name": "测试公司"},
            "period": {"end": "2024-12-31"},
            "subjects": [_bank_subject(), _ar_subject()],
        })
        stats = result["statistics"]
        self.assertGreater(stats["total_workpapers"], 0)
        self.assertGreater(stats["covered_subjects"], 0)
        self.assertGreater(stats["cross_references"], 0)
        self.assertEqual(stats["core_templates"], 16)
        self.assertEqual(stats["library_total_meta"], 200)

    # ------------------------------------------------------------------
    # 数据底座回退与异常
    # ------------------------------------------------------------------
    def test_audit_data_fallback(self) -> None:
        """subjects 为空时从 audit_data.jsonl 重建科目数据。"""
        eng = self._make_engine()
        result = eng.execute({"entity": {"name": "测试公司"}, "period": {}})
        # audit_data.jsonl 含 9 个 balance 记录，应生成若干底稿
        self.assertGreater(result["statistics"]["total_workpapers"], 0)

    def test_invalid_input_raises(self) -> None:
        """非 dict 输入抛 ValueError。"""
        eng = self._make_engine()
        with self.assertRaises(ValueError):
            eng.execute(["not", "a", "dict"])

    def test_empty_subjects_no_fallback_no_workpapers(self) -> None:
        """无 subjects 且无 audit_data fixtures_dir 时返回空底稿列表。"""
        eng = self._make_engine(
            db_path=str(Path(self._tmp.name) / "empty.db"),
            fixtures_dir=str(Path(self._tmp.name) / "no_such_dir"),
        )
        result = eng.execute({"entity": {"name": "x"}, "period": {}})
        self.assertEqual(result["workpapers"], [])
        self.assertEqual(result["statistics"]["total_workpapers"], 0)


class RuleHelpersUnitTest(unittest.TestCase):
    """_resolve_path / _eval_rule 纯函数单测。"""

    def test_resolve_path_nested(self) -> None:
        ctx = {"subject": {"detail": {"aging": {"ratio": 0.93}}}}
        self.assertAlmostEqual(_resolve_path(ctx, "subject.detail.aging.ratio"), 0.93)

    def test_resolve_path_missing(self) -> None:
        self.assertIsNone(_resolve_path({"a": {}}, "a.b.c"))

    def test_eval_rule_missing_present(self) -> None:
        self.assertTrue(_eval_rule(None, "missing", None))
        self.assertFalse(_eval_rule(1, "missing", None))
        self.assertTrue(_eval_rule(1, "present", None))
        self.assertFalse(_eval_rule(None, "present", None))

    def test_eval_rule_numeric(self) -> None:
        self.assertTrue(_eval_rule(0.93, ">=", 0.9))
        self.assertFalse(_eval_rule(None, ">", 0))  # None 不命中数值比较
        self.assertTrue(_eval_rule(50000, ">", 0))
        self.assertTrue(_eval_rule(0.25, ">", 0.2))


if __name__ == "__main__":
    unittest.main()
