"""[CO-01] pipeline 端到端单测：Pipeline.run() 全流程跑通（unittest 风格）。

覆盖：端到端跑通 / 阈值分级 / 业务规则 / PortableDB 持久化 / 订阅规则增量。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modules.co_01.pipeline import Pipeline
from modules.shared.portable_db import PortableDB

_FIXTURES = Path(__file__).parent / "fixtures"


def _make_pipeline(test: unittest.TestCase, tmp_dir: str,
                   threshold: float = 0.85) -> Pipeline:
    """构造隔离 db 的 pipeline；注册 engine.close 清理（Windows 文件锁）。"""
    pipe = Pipeline(config={
        "threshold": {"confidence": threshold},
        "db_path": str(Path(tmp_dir) / "co_01_pipeline.db"),
    })
    test.addCleanup(pipe.engine.close)
    return pipe


class TestPipelineEndToEnd(unittest.TestCase):
    """端到端跑通。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_pipeline_with_mock_input(self):
        """用 fixtures/mock_input.json 端到端跑通，输出结构含 report + summary。"""
        pipe = _make_pipeline(self, self._tmp.name)
        mock_input = json.loads((_FIXTURES / "mock_input.json").read_text(encoding="utf-8"))
        out = pipe.run(mock_input)

        self.assertEqual(out["status"], "ok")
        self.assertIn("report", out)
        report = out["report"]
        self.assertEqual(report["title"], "法规监控日报")
        self.assertIn("summary", report)
        self.assertIn("regulations", report)
        self.assertIn("high_impact_list", report)
        self.assertIn("push_recommendations", report)

        summary = report["summary"]
        self.assertEqual(summary["total"], len(mock_input["regulations"]))
        # 覆盖国家应包含 CN / EU / US / IFRS
        self.assertIn("CN", summary["covered_countries"])
        self.assertGreaterEqual(summary["push_count"], 1)
        # 各分类统计之和等于总数
        self.assertEqual(sum(summary["by_category"].values()), summary["total"])

    def test_pipeline_classifies_all_categories(self):
        """mock_input 覆盖多分类，输出 by_category 含多个分类键。"""
        pipe = _make_pipeline(self, self._tmp.name)
        mock_input = json.loads((_FIXTURES / "mock_input.json").read_text(encoding="utf-8"))
        out = pipe.run(mock_input)
        cats = set(out["report"]["summary"]["by_category"].keys())
        # 至少覆盖 4 个分类
        self.assertGreaterEqual(len(cats), 4)
        self.assertIn("data_security", cats)


class TestThresholdsTiers(unittest.TestCase):
    """阈值分级：push / watch / ignore。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_high_relevance_push_tier(self):
        """本国本行业法规相关性 ≥0.85 → tier=push。"""
        pipe = _make_pipeline(self, self._tmp.name)
        out = pipe.run({
            "enterprise": {
                "industries": ["finance", "technology"], "countries": ["CN"],
                "size": "large", "listed": True,
            },
            "regulations": [{
                "reg_id": "TH1", "title": "数据安全法",
                "body": "数据安全 个人信息 数据出境 网络安全 数据保护",
                "country": "CN", "language": "zh", "publish_date": "2021-06-10",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertEqual(reg["tier"], "push")
        self.assertTrue(reg["push"])

    def test_low_relevance_ignore_tier(self):
        """外国无关法规相关性 <0.5 → tier=ignore。"""
        pipe = _make_pipeline(self, self._tmp.name)
        out = pipe.run({
            "enterprise": {
                "industries": ["finance"], "countries": ["CN"],
                "size": "large", "listed": False,
            },
            "regulations": [{
                "reg_id": "TH2", "title": "zzz qqq xxx",
                "body": "no relevant keyword here at all",
                "country": "XX", "language": "en", "publish_date": "2020-01-01",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertEqual(reg["tier"], "ignore")
        self.assertEqual(reg["category"], "other")
        self.assertFalse(reg["push"])


class TestCustomRules(unittest.TestCase):
    """业务规则：数据安全升级 / 本国强制推送 / 上市证券强制推送。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_data_security_upgraded_to_high_impact(self):
        """数据安全类法规自动升级为高影响（即使外国法规）。"""
        pipe = _make_pipeline(self, self._tmp.name)
        out = pipe.run({
            "enterprise": {
                "industries": ["technology"], "countries": ["CN"],
                "size": "large", "listed": False,
            },
            "regulations": [{
                "reg_id": "CR1", "title": "GDPR",
                "body": "data protection personal data privacy data processing data security",
                "country": "EU", "language": "en", "publish_date": "2018-05-25",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertEqual(reg["category"], "data_security")
        self.assertEqual(reg["impact_level"], "high")
        self.assertIn(reg, out["report"]["high_impact_list"])

    def test_home_country_force_push(self):
        """企业所在国法规强制推送（push_reasons 含 home_country）。"""
        pipe = _make_pipeline(self, self._tmp.name)
        out = pipe.run({
            "enterprise": {
                "industries": ["finance"], "countries": ["CN"],
                "size": "large", "listed": False,
            },
            "regulations": [{
                "reg_id": "CR2", "title": "增值税法",
                "body": "增值税 税率 抵扣 纳税申报 税务稽查",
                "country": "CN", "language": "zh", "publish_date": "2024-12-25",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertIn("home_country", reg["push_reasons"])
        self.assertTrue(reg["push"])

    def test_listed_securities_force_push(self):
        """上市企业涉证监法规强制推送（push_reasons 含 listed_securities）。"""
        pipe = _make_pipeline(self, self._tmp.name)
        out = pipe.run({
            "enterprise": {
                "industries": ["finance"], "countries": ["CN"],
                "size": "large", "listed": True,
            },
            "regulations": [{
                "reg_id": "CR3", "title": "证券法",
                "body": "证券发行 上市公司收购 招股说明书 信息披露 交易所监管",
                "country": "CN", "language": "zh", "publish_date": "2019-12-28",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertIn("listed_securities", reg["push_reasons"])
        self.assertTrue(reg["push"])

    def test_non_listed_no_securities_push(self):
        """非上市企业不触发 listed_securities 强制推送。"""
        pipe = _make_pipeline(self, self._tmp.name)
        out = pipe.run({
            "enterprise": {
                "industries": ["manufacturing"], "countries": ["XX"],
                "size": "small", "listed": False,
            },
            "regulations": [{
                "reg_id": "CR4", "title": "证券法",
                "body": "证券 上市公司 招股说明书",
                "country": "CN", "language": "zh", "publish_date": "2019-12-28",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertNotIn("listed_securities", reg["push_reasons"])


class TestPortableDBPersistence(unittest.TestCase):
    """PortableDB 持久化：四表落盘 + 数据可读。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_persists_to_four_tables(self):
        """Pipeline 初始化后 PortableDB 含四张表，run 后法规/分类/影响评估落盘。"""
        tmp = self._tmp.name
        db_path = Path(tmp) / "co_01_pipeline.db"
        pipe = Pipeline(config={
            "threshold": {"confidence": 0.85}, "db_path": str(db_path),
        })
        self.addCleanup(pipe.engine.close)
        pipe.run({
            "enterprise": {"industries": ["finance"], "countries": ["CN"],
                           "size": "large", "listed": False},
            "regulations": [
                {"reg_id": "DB1", "title": "数据安全法", "body": "数据安全 个人信息",
                 "country": "CN", "language": "zh", "publish_date": "2021-06-10"},
                {"reg_id": "DB2", "title": "GDPR", "body": "data protection personal data",
                 "country": "EU", "language": "en", "publish_date": "2018-05-25"},
            ],
        })

        with PortableDB(db_path) as db:
            tables = set(db.tables())
            self.assertIn("regulations", tables)
            self.assertIn("regulation_categories", tables)
            self.assertIn("impact_assessments", tables)
            self.assertIn("subscription_rules", tables)
            # 法规元数据落盘
            regs = db.all("regulations")
            self.assertEqual(len(regs), 2)
            reg_ids = {r["reg_id"] for r in regs}
            self.assertEqual(reg_ids, {"DB1", "DB2"})
            # 分类结果落盘
            cats = db.all("regulation_categories")
            self.assertEqual(len(cats), 2)
            self.assertIsInstance(cats[0]["matched_keywords"], list)
            # 影响评估落盘
            impacts = db.all("impact_assessments")
            self.assertEqual(len(impacts), 2)
            self.assertIsInstance(impacts[0]["matched_rules"], list)
            # 订阅规则种子已导入
            self.assertGreaterEqual(db.count("subscription_rules"), 8)

    def test_subscription_rules_seed_imported(self):
        """Pipeline 初始化后 subscription_rules 表含 fixtures 种子数据。"""
        tmp = self._tmp.name
        db_path = Path(tmp) / "co_01_seed.db"
        pipe = Pipeline(config={
            "threshold": {"confidence": 0.85}, "db_path": str(db_path),
        })
        self.addCleanup(pipe.engine.close)
        self.assertGreaterEqual(pipe.engine.db.count("subscription_rules"), 8)


class TestPipelineIncrementalSubscription(unittest.TestCase):
    """Pipeline 内 engine 支持订阅规则增量维护。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_add_rule_then_new_rule_matches(self):
        """新增订阅规则后，下次 run 命中新规则。"""
        pipe = _make_pipeline(self, self._tmp.name)
        pipe.engine.add_subscription_rule(
            "SUB-KR", industry="technology", country="KR",
            categories=["data_security"], priority="high", desc="韩国订阅",
        )
        out = pipe.run({
            "enterprise": {
                "industries": ["technology"], "countries": ["CN"],
                "size": "large", "listed": False,
            },
            "regulations": [{
                "reg_id": "IS1", "title": "Korea PIPA",
                "body": "data security personal information privacy data protection",
                "country": "KR", "language": "en", "publish_date": "2020-01-01",
            }],
        })
        reg = out["report"]["regulations"][0]
        self.assertIn("SUB-KR", reg["matched_rules"])
        self.assertTrue(reg["push"])


if __name__ == "__main__":
    unittest.main()
