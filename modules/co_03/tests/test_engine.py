"""[CO-03] engine 单测：法规变更映射 / 程序更新 / 版本管理 / 回滚 / 覆盖率。

unittest 风格（不依赖 pytest）。CO-03 引擎无 PortableDB，无需 tmp 目录隔离。
注意：_update_programs 会就地变更 self.model，故每个测试用独立 engine 实例。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from modules.co_03.engine import (
    LLMEngine,
    _bump_version,
    _domain_for_regulation,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(**overrides) -> LLMEngine:
    config = {"threshold": {"sim_critical": 0.5, "sim_high": 0.3, "sim_medium": 0.15}}
    config.update(overrides)
    eng = LLMEngine(config=config)
    eng.setup()
    return eng


# 反洗钱法规变更文本（命中 aml 域）
_AML_CHANGE = (
    "本次反洗钱法修订强化了客户尽职调查(KYC)要求，新增受益所有权识别义务，"
    "要求金融机构加强可疑交易监控与报告，并提高对高风险客户和PEP的审查标准。"
)

# 数据隐私法规变更文本（命中 data_privacy 域）
_DP_CHANGE = (
    "本次个人信息保护法修订强化了数据保护与隐私要求，新增数据跨境传输规则，"
    "完善个人信息主体权利响应机制。"
)


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：程序模板库 / 领域映射 / 关键词加载。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_model_loaded(self):
        """setup 后 self.model 含核心键。"""
        self.assertIsNotNone(self.engine.model)
        for key in ("programs", "domain_mapping", "domain_keywords",
                    "update_history", "step_templates"):
            self.assertIn(key, self.engine.model)

    def test_programs_count(self):
        """内置审计程序模板 12 个。"""
        self.assertEqual(len(self.engine.model["programs"]), 12)

    def test_domain_mapping(self):
        """领域映射含 7 个合规领域。"""
        dm = self.engine.model["domain_mapping"]
        for dom in ("data_privacy", "aml", "tax", "accounting",
                    "environmental", "labor", "antitrust"):
            self.assertIn(dom, dm)
        self.assertEqual(len(dm), 7)

    def test_update_history_empty_initially(self):
        """初始 update_history 为空。"""
        self.assertEqual(len(self.engine.model["update_history"]), 0)

    def test_program_has_required_fields(self):
        """每个程序含 prog_id / name / domain / version / steps。"""
        for p in self.engine.model["programs"]:
            self.assertIn("prog_id", p)
            self.assertIn("name", p)
            self.assertIn("domain", p)
            self.assertIn("version", p)
            self.assertIn("steps", p)
            self.assertGreater(len(p["steps"]), 0)


class TestDomainDetection(unittest.TestCase):
    """_domain_for_regulation：法规领域识别。"""

    def test_aml_domain_detected(self):
        """反洗钱文本 → aml 域。"""
        domains = _domain_for_regulation(_AML_CHANGE)
        self.assertIn("aml", domains)

    def test_data_privacy_domain_detected(self):
        """个人信息文本 → data_privacy 域。"""
        domains = _domain_for_regulation(_DP_CHANGE)
        self.assertIn("data_privacy", domains)

    def test_empty_text_no_domains(self):
        """空文本 → 无领域。"""
        self.assertEqual(_domain_for_regulation(""), [])

    def test_multi_domain_detected(self):
        """同时含数据隐私与税务关键词 → 多领域。"""
        text = "个人信息保护与企业所得税申报的税务合规要求"
        domains = _domain_for_regulation(text)
        self.assertIn("data_privacy", domains)
        self.assertIn("tax", domains)


class TestBumpVersion(unittest.TestCase):
    """_bump_version：语义化版本号升级。"""

    def test_major_bump(self):
        self.assertEqual(_bump_version("1.2.3", "major"), "2.0.0")

    def test_minor_bump(self):
        self.assertEqual(_bump_version("1.2.3", "minor"), "1.3.0")

    def test_patch_bump(self):
        self.assertEqual(_bump_version("1.2.3", "patch"), "1.2.4")

    def test_invalid_version_defaults(self):
        """非法版本号 → 从 1.0.0 起步。"""
        self.assertEqual(_bump_version("bad", "minor"), "1.1.0")


class TestAnalyzeChange(unittest.TestCase):
    """_analyze_change：法规变更影响分析。"""

    def setUp(self):
        self.engine = _make_engine()
        self.result = self.engine.execute({
            "action": "analyze_change",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
        })

    def test_affected_domains(self):
        """AML 变更 → affected_domains 含 aml。"""
        self.assertIn("aml", self.result["affected_domains"])

    def test_affected_programs_count(self):
        """受影响程序数 = aml 域程序数（2）。"""
        self.assertEqual(self.result["affected_program_count"], 2)
        self.assertEqual(len(self.result["affected_programs"]), 2)

    def test_affected_programs_fields(self):
        """受影响程序含必要字段。"""
        for p in self.result["affected_programs"]:
            self.assertIn("prog_id", p)
            self.assertIn("name", p)
            self.assertIn("current_version", p)
            self.assertIn("domain", p)
            self.assertIn("impact_similarity", p)
            self.assertIn("impact_level", p)
            self.assertIn("update_urgency", p)

    def test_impact_similarity_in_range(self):
        """影响相似度 ∈ [0, 1]。"""
        for p in self.result["affected_programs"]:
            self.assertGreaterEqual(p["impact_similarity"], 0.0)
            self.assertLessEqual(p["impact_similarity"], 1.0)

    def test_affected_programs_sorted_by_similarity(self):
        """受影响程序按相似度降序排列。"""
        sims = [p["impact_similarity"] for p in self.result["affected_programs"]]
        self.assertEqual(sims, sorted(sims, reverse=True))

    def test_analysis_summary_populated(self):
        """分析摘要非空。"""
        self.assertTrue(len(self.result["analysis_summary"]) > 0)

    def test_aml_programs_targeted(self):
        """受影响程序均为 aml 域。"""
        for p in self.result["affected_programs"]:
            self.assertEqual(p["domain"], "aml")


class TestUpdatePrograms(unittest.TestCase):
    """_update_programs：程序自动更新 + 版本管理。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_update_bumps_version_minor(self):
        """minor 更新 → 版本 1.0.0 → 1.1.0。"""
        result = self.engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
        })
        self.assertGreater(result["programs_updated"], 0)
        for p in result["updated_programs"]:
            self.assertEqual(p["old_version"], "1.0.0")
            self.assertEqual(p["new_version"], "1.1.0")

    def test_update_bumps_version_major(self):
        """major 更新 → 版本 1.0.0 → 2.0.0。"""
        result = self.engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "major",
        })
        for p in result["updated_programs"]:
            self.assertEqual(p["new_version"], "2.0.0")

    def test_update_adds_new_step(self):
        """更新后高/中影响程序新增步骤（updates_made 非空）。"""
        result = self.engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
        })
        # 至少一个程序产生了实际变更（高/中影响程序新增步骤）
        with_changes = [p for p in result["updated_programs"]
                        if p["change_count"] > 0]
        self.assertGreater(len(with_changes), 0)
        for p in with_changes:
            self.assertGreater(len(p["updates_made"]), 0)

    def test_update_records_change_log(self):
        """更新后程序 change_log 记录变更。"""
        self.engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
        })
        aml_prog = next(p for p in self.engine.model["programs"]
                        if p["prog_id"] == "PROG-AML-001")
        self.assertGreater(len(aml_prog["change_log"]), 0)
        entry = aml_prog["change_log"][0]
        self.assertEqual(entry["old_version"], "1.0.0")
        self.assertEqual(entry["new_version"], "1.1.0")
        self.assertEqual(entry["change_type"], "minor")
        self.assertIn("changes", entry)

    def test_update_appends_history(self):
        """更新后 update_history 追加一条记录。"""
        result = self.engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
        })
        self.assertEqual(len(self.engine.model["update_history"]), 1)
        hist = self.engine.model["update_history"][0]
        self.assertEqual(hist["batch_id"], result["batch_id"])
        self.assertIn("timestamp", hist)

    def test_affected_prog_ids_filter(self):
        """affected_prog_ids 限定 → 仅更新指定程序。"""
        result = self.engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
            "affected_prog_ids": ["PROG-AML-001"],
        })
        self.assertEqual(result["programs_updated"], 1)
        self.assertEqual(result["updated_programs"][0]["prog_id"], "PROG-AML-001")

    def test_no_update_for_unrelated_regulation(self):
        """无关法规变更 → 0 程序更新。"""
        result = self.engine.execute({
            "action": "update_programs",
            "regulation_change": "本法规关于太空探索的规范",
            "regulation_title": "无关法规",
            "change_type": "minor",
        })
        self.assertEqual(result["programs_updated"], 0)
        self.assertEqual(result["batch_id"], "")


class TestGetStatus(unittest.TestCase):
    """_get_status：程序库状态查询。"""

    def test_initial_status(self):
        """初始状态：12 程序 / 0 更新。"""
        engine = _make_engine()
        result = engine.execute({"action": "get_status"})
        self.assertEqual(result["total_programs"], 12)
        self.assertEqual(result["total_updates_applied"], 0)
        self.assertIsNone(result["last_update"])
        self.assertIn("by_domain", result)
        self.assertIn("version_distribution", result)

    def test_status_after_update(self):
        """更新后状态：total_updates_applied=1。"""
        engine = _make_engine()
        engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
        })
        status = engine.execute({"action": "get_status"})
        self.assertEqual(status["total_updates_applied"], 1)
        self.assertIsNotNone(status["last_update"])
        # 版本分布中应出现 1.1.0
        self.assertIn("1.1.0", status["version_distribution"])

    def test_by_domain_counts(self):
        """按领域统计：data_privacy=3 / aml=2。"""
        engine = _make_engine()
        status = engine.execute({"action": "get_status"})
        self.assertEqual(status["by_domain"]["data_privacy"], 3)
        self.assertEqual(status["by_domain"]["aml"], 2)


class TestRollback(unittest.TestCase):
    """_rollback：版本回滚。"""

    def test_rollback_success(self):
        """更新后回滚到旧版本 → 成功。"""
        engine = _make_engine()
        engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
            "affected_prog_ids": ["PROG-AML-001"],
        })
        result = engine.execute({
            "action": "rollback",
            "prog_id": "PROG-AML-001",
            "target_version": "1.0.0",
        })
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["rolled_back_to"], "1.0.0")
        self.assertEqual(result["remaining_updates"], 0)
        # 程序版本已回滚
        prog = next(p for p in engine.model["programs"]
                    if p["prog_id"] == "PROG-AML-001")
        self.assertEqual(prog["version"], "1.0.0")

    def test_rollback_program_not_found(self):
        """回滚不存在的程序 → error。"""
        engine = _make_engine()
        result = engine.execute({
            "action": "rollback",
            "prog_id": "PROG-NOT-EXIST",
            "target_version": "1.0.0",
        })
        self.assertIn("error", result)

    def test_rollback_no_history(self):
        """回滚无变更历史的程序 → error。"""
        engine = _make_engine()
        result = engine.execute({
            "action": "rollback",
            "prog_id": "PROG-AML-001",
            "target_version": "1.0.0",
        })
        self.assertIn("error", result)

    def test_rollback_target_version_not_found(self):
        """回滚到不存在的目标版本 → error。"""
        engine = _make_engine()
        engine.execute({
            "action": "update_programs",
            "regulation_change": _AML_CHANGE,
            "regulation_title": "反洗钱法修订案",
            "change_type": "minor",
            "affected_prog_ids": ["PROG-AML-001"],
        })
        result = engine.execute({
            "action": "rollback",
            "prog_id": "PROG-AML-001",
            "target_version": "9.9.9",
        })
        self.assertIn("error", result)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：输入标准化。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_string_input_normalized(self):
        """裸字符串 → action=analyze_change, regulation_change=字符串。"""
        prepared = self.engine._preprocess("某法规变更内容")
        self.assertEqual(prepared["action"], "analyze_change")
        self.assertEqual(prepared["regulation_change"], "某法规变更内容")
        self.assertEqual(prepared["change_type"], "minor")

    def test_defaults_filled(self):
        """缺失字段补默认值。"""
        prepared = self.engine._preprocess({})
        self.assertEqual(prepared["action"], "analyze_change")
        self.assertEqual(prepared["regulation_change"], "")
        self.assertEqual(prepared["affected_prog_ids"], [])
        self.assertEqual(prepared["change_type"], "minor")
        self.assertEqual(prepared["prog_id"], "")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.engine = _make_engine()

    def test_empty_change_text(self):
        """空变更文本 → affected_programs 为空。"""
        result = self.engine.execute({
            "action": "analyze_change",
            "regulation_change": "",
            "regulation_title": "",
        })
        # 空文本走早退分支：返回 note 提示，affected_programs 为空
        self.assertEqual(result.get("affected_program_count", 0), 0)
        self.assertEqual(result["affected_programs"], [])

    def test_unknown_action(self):
        """未知 action → error。"""
        result = self.engine.execute({"action": "unknown_action"})
        self.assertIn("error", result)

    def test_meta_added(self):
        """_postprocess 注入 meta（module=CO-03）。"""
        result = self.engine.execute({"action": "get_status"})
        self.assertEqual(result["meta"]["module"], "CO-03")


if __name__ == "__main__":
    unittest.main(verbosity=2)
