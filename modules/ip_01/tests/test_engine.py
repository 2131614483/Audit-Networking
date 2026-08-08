"""[IP-01] engine 单测 —— unittest 风格，纯 stdlib。

覆盖四栈融合引擎各层：
  * 模型加载 + PortableDB 四表初始化
  * 预处理（项目信息提取 + 任务模板实例化）
  * RPA 任务自动化（规则引擎模拟）
  * ML 财务核查（Benford + Z-Score + 趋势分析）
  * LLM 文档处理（TextRank 摘要 + 关键词 + 关键信息）
  * 知识图谱穿透（股权穿透 + 关联交易 + 资金流向）
  * 进度加速计算 + 瓶颈识别
  * execute() 模板方法端到端
"""
import json
import math
import tempfile
import unittest
from pathlib import Path

from modules.ip_01.engine import LLMEngine

_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "fixtures"


def _load_mock_input():
    with open(_FIXTURES_DIR / "mock_input.json", encoding="utf-8") as f:
        return json.load(f)


# ==================================================================
# 1. 模型加载与 PortableDB 初始化
# ==================================================================
class EngineModelLoadingTests(unittest.TestCase):
    """引擎模型加载 + PortableDB 四张运行时表。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test_engine.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
            "threshold": {"confidence": 0.85, "bottleneck": 0.5},
        })
        self.engine.setup()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_model_loaded(self):
        """模型加载后 self.model 含四要素。"""
        self.assertIsNotNone(self.engine.model)
        for key in ("audit_task_templates", "checkpoint_rules",
                     "benford_expected", "related_tx_threshold"):
            self.assertIn(key, self.engine.model)

    def test_portabledb_four_tables_created(self):
        """PortableDB 四张运行时表已创建。"""
        tables = self.engine.db.tables()
        for t in ("ipo_tasks", "checkpoints", "findings", "acceleration_logs"):
            self.assertIn(t, tables)

    def test_benford_expected_correct(self):
        """Benford 期望频率 = log10(1+1/d)。"""
        expected = self.engine.model["benford_expected"]
        for d in range(1, 10):
            self.assertAlmostEqual(expected[d], math.log10(1 + 1 / d), places=4)

    def test_audit_task_templates_four_categories(self):
        """审计任务模板覆盖四类：financial/legal/business/internal_control。"""
        templates = self.engine.model["audit_task_templates"]
        self.assertGreater(len(templates), 15)
        cats = {t["category"] for t in templates}
        self.assertEqual(cats, {"financial", "legal", "business", "internal_control"})

    def test_checkpoint_rules_loaded(self):
        """核查规则库加载，含 financial 类规则。"""
        rules = self.engine.model["checkpoint_rules"]
        self.assertGreater(len(rules), 0)
        fin_rules = [r for r in rules.values() if r.get("category") == "financial"]
        self.assertGreater(len(fin_rules), 0)

    def test_related_tx_threshold_configurable(self):
        """关联交易阈值可被 config 覆盖。"""
        self.assertEqual(self.engine.model["related_tx_threshold"], 5_000_000)


# ==================================================================
# 2. 预处理
# ==================================================================
class EnginePreprocessTests(unittest.TestCase):
    """预处理：项目信息提取 + 任务模板实例化。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        self.engine.setup()
        self.mock = _load_mock_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_returns_project_and_tasks(self):
        prepared = self.engine._preprocess(self.mock)
        self.assertIn("project", prepared)
        self.assertIn("tasks", prepared)
        self.assertEqual(prepared["project"]["project_id"], "IPO-2026-001")

    def test_preprocess_instantiates_all_templates(self):
        """任务数 = 模板数。"""
        prepared = self.engine._preprocess(self.mock)
        templates = self.engine.model["audit_task_templates"]
        self.assertEqual(len(prepared["tasks"]), len(templates))

    def test_preprocess_tasks_initial_pending(self):
        """实例化任务初始状态 pending、加速比例 0、非瓶颈。"""
        prepared = self.engine._preprocess(self.mock)
        for t in prepared["tasks"]:
            self.assertEqual(t["status"], "pending")
            self.assertEqual(t["acceleration_ratio"], 0.0)
            self.assertFalse(t["is_bottleneck"])

    def test_preprocess_extracts_project_fields(self):
        """预处理提取 enterprise/financial_data/documents 等字段。"""
        prepared = self.engine._preprocess(self.mock)
        project = prepared["project"]
        self.assertEqual(project["enterprise"]["name"], "智造未来科技股份有限公司")
        self.assertIn("2025", project["financial_data"])
        self.assertGreater(len(project["related_parties"]), 0)
        self.assertIn("equity_structure", project)

    def test_preprocess_invalid_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess("not a dict")

    def test_preprocess_lazy_load_model(self):
        """懒加载：未 setup() 时 _preprocess 自动加载模型。"""
        engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "lazy.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        prepared = engine._preprocess(self.mock)
        self.assertIsNotNone(engine.model)
        self.assertGreater(len(prepared["tasks"]), 0)
        engine.close()


# ==================================================================
# 3. RPA 任务自动化
# ==================================================================
class EngineRpaTests(unittest.TestCase):
    """RPA 任务自动化（规则引擎模拟）。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        self.engine.setup()
        self.mock = _load_mock_input()
        self.prepared = self.engine._preprocess(self.mock)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_rpa_automates_automatable_tasks(self):
        """rpa_automatable=True 的任务被自动完成。"""
        findings = []
        result = self.engine._rpa_automate(
            self.prepared["project"], self.prepared["tasks"], findings)
        self.assertGreaterEqual(result["automated_count"], 6)
        for action in result["actions"]:
            self.assertEqual(action["status"], "auto_done")

    def test_rpa_automated_tasks_status_changed(self):
        """被 RPA 自动化的任务状态变为 auto_done。"""
        findings = []
        self.engine._rpa_automate(
            self.prepared["project"], self.prepared["tasks"], findings)
        auto_tasks = [t for t in self.prepared["tasks"] if t["rpa_automatable"]]
        for t in auto_tasks:
            self.assertEqual(t["status"], "auto_done")

    def test_rpa_action_mapping(self):
        """RPA 动作按任务名映射到合法集合。"""
        valid_actions = {
            "data_collection", "format_conversion", "cross_check",
            "file_archiving", "generic_automation",
        }
        for t in self.prepared["tasks"]:
            action = self.engine._rpa_action_for(t)
            self.assertIn(action, valid_actions)

    def test_rpa_action_data_collection(self):
        """含"采集"的任务 → data_collection。"""
        action = self.engine._rpa_action_for({"task_name": "财务数据采集与归档"})
        self.assertEqual(action, "data_collection")

    def test_rpa_action_format_conversion(self):
        """含"格式"/"转换"的任务 → format_conversion。"""
        action = self.engine._rpa_action_for({"task_name": "财务数据格式转换与勾稽核对"})
        self.assertEqual(action, "format_conversion")

    def test_rpa_cross_check_no_finding_for_consistent_data(self):
        """mock_input 注册资本=实收资本=1亿，RPA 交叉核对不产 finding。"""
        findings = []
        self.engine._rpa_automate(
            self.prepared["project"], self.prepared["tasks"], findings)
        rpa_findings = [f for f in findings if f["source"] == "rpa"]
        # 注册资本与实收资本一致，无 RPA 交叉核对发现
        self.assertEqual(len(rpa_findings), 0)


# ==================================================================
# 4. ML 财务核查
# ==================================================================
class EngineMlTests(unittest.TestCase):
    """ML 财务核查：Benford + Z-Score 异常值 + 趋势分析。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
            "threshold": {"z_score": 2.5},
        })
        self.engine.setup()
        self.mock = _load_mock_input()
        self.prepared = self.engine._preprocess(self.mock)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_benford_analysis_returns_metrics(self):
        amounts = [2300000, 1800000, 4200000, 1500000, 3100000]
        result = self.engine._benford_analysis(amounts)
        for key in ("chi_square", "deviation", "observed", "expected"):
            self.assertIn(key, result)

    def test_benford_empty_amounts(self):
        """空金额列表 → 零值返回。"""
        result = self.engine._benford_analysis([])
        self.assertEqual(result["chi_square"], 0.0)
        self.assertEqual(result["deviation"], 0.0)

    def test_benford_observed_sum_equals_total(self):
        """观察频数之和 = 样本总数。"""
        amounts = [2300000, 1800000, 4200000, 1500000, 3100000, 9500000]
        result = self.engine._benford_analysis(amounts)
        total_obs = sum(result["observed"].values())
        self.assertEqual(total_obs, len(amounts))

    def test_zscore_detects_anomaly_tx(self):
        """TX-2025-004=850万（异常大额），Z-Score 应标记。"""
        financial_data = self.prepared["project"]["financial_data"]
        years = sorted(financial_data.keys())
        outliers = self.engine._zscore_outliers(financial_data, years)
        self.assertGreater(len(outliers), 0)
        tx_ids = [o["tx_id"] for o in outliers]
        self.assertIn("TX-2025-004", tx_ids)

    def test_zscore_few_transactions_returns_empty(self):
        """交易数 < 4 → 空列表。"""
        result = self.engine._zscore_outliers(
            {"2023": {"transactions": []}}, ["2023"])
        self.assertEqual(result, [])

    def test_trend_detects_revenue_anomaly(self):
        """2025 年收入同比 +61%（>50%），趋势分析应标记。"""
        financial_data = self.prepared["project"]["financial_data"]
        years = sorted(financial_data.keys())
        trends = self.engine._trend_analysis(financial_data, years)
        metrics = [t["metric"] for t in trends]
        self.assertTrue(any("revenue" in m for m in metrics))

    def test_trend_detects_revenue_profit_divergence(self):
        """2025 年收入增长但净利润下滑 → revenue_vs_net_profit 背离。"""
        financial_data = self.prepared["project"]["financial_data"]
        years = sorted(financial_data.keys())
        trends = self.engine._trend_analysis(financial_data, years)
        metrics = [t["metric"] for t in trends]
        self.assertIn("revenue_vs_net_profit", metrics)

    def test_ml_financial_check_produces_findings(self):
        """ML 核查产出发现（异常值 + 趋势 + Benford）。"""
        findings = []
        checkpoints = []
        tasks_by_id = {t["task_id"]: t for t in self.prepared["tasks"]}
        result = self.engine._ml_financial_check(
            self.prepared["project"], findings, checkpoints, tasks_by_id)
        self.assertGreater(result["anomaly_count"], 0)
        self.assertGreater(len(findings), 0)

    def test_ml_findings_source_is_ml(self):
        """ML 产出的发现 source=ml。"""
        findings = []
        checkpoints = []
        tasks_by_id = {t["task_id"]: t for t in self.prepared["tasks"]}
        self.engine._ml_financial_check(
            self.prepared["project"], findings, checkpoints, tasks_by_id)
        for f in findings:
            self.assertEqual(f["source"], "ml")

    def test_ml_checkpoints_evaluated(self):
        """财务类核查规则被评估并产出 checkpoint。"""
        findings = []
        checkpoints = []
        tasks_by_id = {t["task_id"]: t for t in self.prepared["tasks"]}
        self.engine._ml_financial_check(
            self.prepared["project"], findings, checkpoints, tasks_by_id)
        self.assertGreater(len(checkpoints), 0)
        for cp in checkpoints:
            self.assertEqual(cp["category"], "financial")
            self.assertIn(cp["status"], ("passed", "flagged"))


# ==================================================================
# 5. LLM 文档处理（TextRank）
# ==================================================================
class EngineLlmTextRankTests(unittest.TestCase):
    """LLM 文档处理：TextRank 摘要 + 关键词 + 关键信息。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        self.engine.setup()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_textrank_returns_summary_keywords_keyinfo(self):
        text = ("公司是国内领先的高端装备制造商。"
                "2025年营业收入6.2亿元。"
                "公司存在关联交易风险。"
                "实际控制人为张明。")
        summary, keywords, key_info = self.engine._textrank(
            text, num_sentences=2, num_keywords=5)
        self.assertIsInstance(summary, str)
        self.assertGreater(len(summary), 0)
        self.assertIsInstance(keywords, list)
        self.assertIsInstance(key_info, dict)

    def test_textrank_empty_text(self):
        """空文本 → 空返回。"""
        summary, keywords, key_info = self.engine._textrank("")
        self.assertEqual(summary, "")
        self.assertEqual(keywords, [])
        self.assertEqual(key_info, {})

    def test_textrank_key_info_extracts_amounts(self):
        """关键信息抽取金额（含"万元"/"元"/"亿"）。"""
        text = "2023年6月签订合同，金额5000万元，同比增长15.5%。"
        _, _, key_info = self.engine._textrank(text)
        self.assertTrue(any("5000" in a for a in key_info["amounts"]))

    def test_textrank_key_info_extracts_dates(self):
        """关键信息抽取日期。"""
        text = "2023年6月签订合同，2024年7月完成验收。"
        _, _, key_info = self.engine._textrank(text)
        self.assertTrue(len(key_info["dates"]) > 0)

    def test_textrank_key_info_extracts_ratios(self):
        """关键信息抽取百分比。"""
        text = "同比增长15.5%，利润率20%。"
        _, _, key_info = self.engine._textrank(text)
        self.assertTrue(any("15.5%" in r for r in key_info["ratios"]))

    def test_llm_document_process_produces_summaries(self):
        """LLM 文档处理产出摘要（招股说明书 + 法律文件）。"""
        mock = _load_mock_input()
        prepared = self.engine._preprocess(mock)
        findings = []
        tasks_by_id = {t["task_id"]: t for t in prepared["tasks"]}
        result = self.engine._llm_document_process(
            prepared["project"], findings, tasks_by_id)
        self.assertGreater(result["doc_count"], 0)
        self.assertEqual(result["doc_count"], len(result["summaries"]))

    def test_llm_risk_word_produces_finding(self):
        """法律文档含风险词（诉讼/担保/纠纷），LLM 产出文档类发现。"""
        mock = _load_mock_input()
        prepared = self.engine._preprocess(mock)
        findings = []
        tasks_by_id = {t["task_id"]: t for t in prepared["tasks"]}
        self.engine._llm_document_process(
            prepared["project"], findings, tasks_by_id)
        llm_findings = [f for f in findings if f["source"] == "llm"]
        self.assertGreater(len(llm_findings), 0)
        for f in llm_findings:
            self.assertEqual(f["category"], "document")
            self.assertTrue(f["need_manual_review"])


# ==================================================================
# 6. 知识图谱穿透
# ==================================================================
class EngineKgTests(unittest.TestCase):
    """知识图谱穿透：股权穿透 + 关联交易 + 资金流向。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        self.engine.setup()
        self.mock = _load_mock_input()
        self.prepared = self.engine._preprocess(self.mock)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_equity_penetration_finds_controller(self):
        """股权穿透：BFS 找到终极控制人张明（经 4 层持股）。"""
        equity = self.prepared["project"]["equity_structure"]
        results = self.engine._equity_penetration(equity)
        self.assertGreater(len(results), 0)
        controllers = [r["controller"] for r in results]
        self.assertIn("张明", controllers)

    def test_equity_penetration_path_complex(self):
        """张明经 4 层持股（E1←H1←H2←H3←P1），路径长度 > 3。"""
        equity = self.prepared["project"]["equity_structure"]
        results = self.engine._equity_penetration(equity)
        zhang = [r for r in results if r["controller"] == "张明"][0]
        self.assertGreater(len(zhang["path"]), 3)

    def test_equity_penetration_total_ratio(self):
        """累计持股比例 = 各层 ratio 乘积（0.55*0.80*0.70*0.90=0.2772）。"""
        equity = self.prepared["project"]["equity_structure"]
        results = self.engine._equity_penetration(equity)
        zhang = [r for r in results if r["controller"] == "张明"][0]
        self.assertAlmostEqual(zhang["total_ratio"], 0.2772, places=3)

    def test_related_transactions_lists_all(self):
        """关联交易：列出全部 3 笔关联方交易。"""
        related_parties = self.prepared["project"]["related_parties"]
        result = self.engine._related_transactions(related_parties, [])
        self.assertEqual(len(result), 3)

    def test_related_transactions_flags_high_amount(self):
        """820万 > 500万阈值 → flagged=True。"""
        related_parties = self.prepared["project"]["related_parties"]
        result = self.engine._related_transactions(related_parties, [])
        flagged = [r for r in result if r["flagged"]]
        self.assertGreater(len(flagged), 0)
        self.assertTrue(any(r["amount"] == 8_200_000 for r in flagged))

    def test_fund_flow_returns_paths(self):
        """资金流向：BFS 追踪多跳资金路径。"""
        equity = self.prepared["project"]["equity_structure"]
        related_parties = self.prepared["project"]["related_parties"]
        paths = self.engine._fund_flow(equity, related_parties)
        self.assertIsInstance(paths, list)
        self.assertGreater(len(paths), 0)

    def test_kg_penetration_produces_findings(self):
        """KG 穿透产出发现：关联交易超阈值 + 股权穿透链路过长。"""
        findings = []
        tasks_by_id = {t["task_id"]: t for t in self.prepared["tasks"]}
        self.engine._kg_penetration(
            self.prepared["project"], findings, tasks_by_id)
        kg_findings = [f for f in findings if f["source"] == "kg"]
        self.assertGreater(len(kg_findings), 0)

    def test_kg_high_severity_for_related_tx(self):
        """关联交易 820万 > 阈值 500万 → high severity。"""
        findings = []
        tasks_by_id = {t["task_id"]: t for t in self.prepared["tasks"]}
        self.engine._kg_penetration(
            self.prepared["project"], findings, tasks_by_id)
        high_kg = [f for f in findings
                   if f["source"] == "kg" and f["severity"] == "high"]
        self.assertGreater(len(high_kg), 0)

    def test_kg_finding_for_complex_equity(self):
        """股权穿透链路 > 3 层 → 产出 medium 发现。"""
        findings = []
        tasks_by_id = {t["task_id"]: t for t in self.prepared["tasks"]}
        self.engine._kg_penetration(
            self.prepared["project"], findings, tasks_by_id)
        equity_findings = [f for f in findings
                           if "股权穿透" in f.get("description", "")]
        self.assertGreater(len(equity_findings), 0)


# ==================================================================
# 7. 进度加速计算 + 瓶颈识别
# ==================================================================
class EngineAccelerationTests(unittest.TestCase):
    """进度加速计算 + 瓶颈识别。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
            "threshold": {"bottleneck": 0.5},
        })
        self.engine.setup()
        self.mock = _load_mock_input()
        self.prepared = self.engine._preprocess(self.mock)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_acceleration_ratio_formula(self):
        """加速比例 = rpa + ml*(1-rpa)，上限 0.95。"""
        tasks = self.prepared["tasks"]
        self.engine._compute_acceleration(tasks)
        for t in tasks:
            rpa = t["rpa_replacement_rate"]
            ml = t["ml_assist_rate"]
            expected = min(0.95, rpa + ml * (1 - rpa))
            self.assertAlmostEqual(t["acceleration_ratio"], round(expected, 4), places=3)

    def test_bottleneck_identification(self):
        """加速比例 < 0.5 → 瓶颈。"""
        tasks = self.prepared["tasks"]
        self.engine._compute_acceleration(tasks)
        for t in tasks:
            if t["acceleration_ratio"] < 0.5:
                self.assertTrue(t["is_bottleneck"])
            else:
                self.assertFalse(t["is_bottleneck"])

    def test_overall_acceleration_positive(self):
        """整体加速比例 > 0。"""
        tasks = self.prepared["tasks"]
        accel = self.engine._compute_acceleration(tasks)
        self.assertGreater(accel["overall_acceleration_ratio"], 0)

    def test_overall_acceleration_in_target_range(self):
        """业务目标：整体加速比例落在 40-70% 区间（目标 50-60%）。"""
        tasks = self.prepared["tasks"]
        accel = self.engine._compute_acceleration(tasks)
        overall = accel["overall_acceleration_ratio"]
        self.assertGreaterEqual(overall, 0.40)
        self.assertLessEqual(overall, 0.70)

    def test_cycle_reduction_pct(self):
        """周期缩短比例 = 整体加速比例 * 100。"""
        tasks = self.prepared["tasks"]
        accel = self.engine._compute_acceleration(tasks)
        self.assertAlmostEqual(
            accel["estimated_cycle_reduction_pct"],
            round(accel["overall_acceleration_ratio"] * 100, 2),
            places=1)

    def test_saved_hours_positive(self):
        """节省工时 > 0。"""
        tasks = self.prepared["tasks"]
        accel = self.engine._compute_acceleration(tasks)
        self.assertGreater(accel["total_saved_hours"], 0)

    def test_after_hours_less_than_before(self):
        """加速后工时 < 加速前工时。"""
        tasks = self.prepared["tasks"]
        accel = self.engine._compute_acceleration(tasks)
        self.assertLess(accel["total_after_hours"], accel["total_before_hours"])

    def test_bottleneck_tasks_sorted_asc(self):
        """瓶颈任务按加速比例升序排列（最待优化的在前）。"""
        tasks = self.prepared["tasks"]
        accel = self.engine._compute_acceleration(tasks)
        bottlenecks = accel["bottleneck_tasks"]
        for i in range(1, len(bottlenecks)):
            self.assertGreaterEqual(
                bottlenecks[i]["acceleration_ratio"],
                bottlenecks[i - 1]["acceleration_ratio"])


# ==================================================================
# 8. execute() 模板方法端到端
# ==================================================================
class EngineExecuteTests(unittest.TestCase):
    """execute() 模板方法端到端：预处理 → 推理 → 后处理。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "test.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        self.engine.setup()
        self.mock = _load_mock_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_execute_returns_result_with_report(self):
        """execute() 返回含 report/statistics/tasks/findings/acceleration。"""
        result = self.engine.execute(self.mock)
        for key in ("report", "statistics", "tasks", "findings",
                     "acceleration", "rpa_results", "ml_results",
                     "llm_results", "kg_results"):
            self.assertIn(key, result)

    def test_execute_report_findings_summary(self):
        """report.findings_summary.total > 0（mock_input 必然触发发现）。"""
        result = self.engine.execute(self.mock)
        report = result["report"]
        self.assertIn("findings_summary", report)
        self.assertGreater(report["findings_summary"]["total"], 0)
        # 按来源统计
        by_source = report["findings_summary"]["by_source"]
        self.assertIn("ml", by_source)

    def test_execute_report_acceleration_effect(self):
        """report.acceleration_effect 含周期缩短指标。"""
        result = self.engine.execute(self.mock)
        ae = result["report"]["acceleration_effect"]
        self.assertGreater(ae["overall_acceleration_ratio"], 0)
        self.assertGreater(ae["total_saved_hours"], 0)
        self.assertGreater(ae["estimated_cycle_reduction_pct"], 0)

    def test_execute_statistics_has_cycle_metrics(self):
        """statistics 含周期天数与缩短比例。"""
        result = self.engine.execute(self.mock)
        stats = result["statistics"]
        for key in ("total_tasks", "overall_acceleration_ratio",
                     "estimated_cycle_reduction_pct",
                     "cycle_before_days", "cycle_after_days"):
            self.assertIn(key, stats)
        self.assertGreater(stats["cycle_before_days"], stats["cycle_after_days"])

    def test_execute_report_bottleneck_analysis(self):
        """report.bottleneck_analysis 含瓶颈任务列表。"""
        result = self.engine.execute(self.mock)
        bn = result["report"]["bottleneck_analysis"]
        self.assertIn("bottleneck_count", bn)
        self.assertIn("bottleneck_tasks", bn)

    def test_execute_report_task_completion(self):
        """report.task_completion 含状态汇总。"""
        result = self.engine.execute(self.mock)
        tc = result["report"]["task_completion"]
        self.assertIn("status_count", tc)
        self.assertIn("category_status", tc)

    def test_execute_lazy_load_model(self):
        """懒加载：未 setup() 时 execute() 自动加载模型。"""
        engine = LLMEngine(config={
            "db_path": str(Path(self.tmpdir.name) / "lazy.db"),
            "fixtures_dir": str(_FIXTURES_DIR),
        })
        result = engine.execute(self.mock)
        self.assertIn("report", result)
        engine.close()


if __name__ == "__main__":
    unittest.main()
