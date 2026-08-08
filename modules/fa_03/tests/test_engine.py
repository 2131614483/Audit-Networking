"""[FA-03] engine 单测 —— 三区分层提升 / 血缘 / 质量评分 / 数据流转。

使用 unittest.TestCase，pytest 与 unittest 均可发现并运行。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# sys.path 引导：保证两种运行器下均可导入 modules 包
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.fa_03.engine import MLEngine  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mock_input.json"


def _load_input():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.input_data = _load_input()
        # 临时 db 文件，保证测试隔离
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.eng = MLEngine(config={
            "db_path": self.db_path,
            "threshold": {"confidence": 0.85},
        })

    def tearDown(self):
        self.eng.close()
        for ext in ("", "-wal", "-shm"):
            p = self.db_path + ext
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # ---------- _load_model ----------
    def test_load_model_creates_three_zones_and_meta_tables(self):
        self.eng.setup()
        tables = self.eng.db.tables()
        for t in ("ods_raw", "dwd_standardized", "ads_ready",
                  "lineage", "quality_metrics"):
            self.assertIn(t, tables)
        self.assertIsNotNone(self.eng.model)
        self.assertIn("account_master", self.eng.model)

    def test_load_model_idempotent(self):
        self.eng.setup()
        db_ref = self.eng.db
        self.eng._load_model()  # 再次调用应幂等
        self.assertIs(db_ref, self.eng.db)

    # ---------- _preprocess ----------
    def test_preprocess_writes_ods_with_sources(self):
        prepared = self.eng._preprocess(self.input_data)
        self.assertEqual(prepared["ingested"], 57)
        self.assertEqual(self.eng.db.count("ods_raw"), 57)
        self.assertEqual(
            set(prepared["sources"]),
            {"ERP-SAP", "用友NC", "工商银行"},
        )
        # 原始 schema 被记录
        row = self.eng.db.query("ods_raw", limit=1)[0]
        self.assertIsInstance(row["raw_schema"], list)
        self.assertIsInstance(row["raw_data"], dict)

    # ---------- execute（三区分层提升） ----------
    def test_execute_three_zone_promotion_and_dedup(self):
        out = self.eng.execute(self.input_data)
        # ODS 57 条原始
        self.assertEqual(out["zones"]["ods"]["count"], 57)
        # DWD 去重后 54 条（3 条真重复被合并）
        self.assertEqual(out["zones"]["dwd"]["count"], 54)
        self.assertEqual(out["dedup_removed"], 3)
        # ADS 聚合后行数 <= DWD 且非空
        self.assertGreater(out["zones"]["ads"]["count"], 0)
        self.assertLessEqual(out["zones"]["ads"]["count"], 54)
        self.assertEqual(out["zones"]["ads"]["theme"],
                         "account_monthly_summary")

    # ---------- 血缘 ----------
    def test_lineage_recorded_for_both_transitions(self):
        out = self.eng.execute(self.input_data)
        summary = out["lineage"]["summary"]
        self.assertIn("ods_raw->dwd_standardized", summary)
        self.assertIn("dwd_standardized->ads_ready", summary)
        # ods->dwd 边数 == ods 总数（保留 + 去重合并各一条）
        self.assertEqual(summary["ods_raw->dwd_standardized"], 57)
        # dwd->ads 边数 == dwd 总数
        self.assertEqual(summary["dwd_standardized->ads_ready"], 54)
        # 血缘图：ods_raw -> dwd_standardized -> ads_ready
        graph = out["lineage"]["graph"]
        self.assertEqual(graph["ods_raw"], ["dwd_standardized"])
        self.assertEqual(graph["dwd_standardized"], ["ads_ready"])

    # ---------- 质量评分 ----------
    def test_quality_metrics_computed(self):
        out = self.eng.execute(self.input_data)
        quality = out["quality"]
        for zone in ("ods", "dwd", "ads"):
            self.assertIn(zone, quality)
            m = quality[zone]
            for k in ("completeness", "uniqueness", "consistency",
                      "overall_score"):
                self.assertIn(k, m)
                self.assertGreaterEqual(m[k], 0.0)
                self.assertLessEqual(m[k], 1.0)
        # DWD 已去重，唯一性应为 1.0
        self.assertEqual(quality["dwd"]["uniqueness"], 1.0)
        # ADS 为聚合宽表，综合质量应为 1.0
        self.assertEqual(quality["ads"]["overall_score"], 1.0)

    # ---------- 标准化效果 ----------
    def test_dwd_standardization_fields(self):
        self.eng.execute(self.input_data)
        dwd = self.eng.db.all("dwd_standardized")
        # 科目名称来自主数据
        ar = [r for r in dwd if r["account_code"] == "1122"]
        self.assertTrue(all(r["account_name"] == "应收账款" for r in ar))
        # 金额已转 float
        self.assertTrue(all(isinstance(r["amount"], float) for r in dwd))
        # 期间已标准化为 YYYY-MM
        periods = {r["period"] for r in dwd if r["period"]}
        self.assertTrue(all(p.startswith("2026-") for p in periods))

    def test_dwd_quality_flags_for_dirty_data(self):
        self.eng.execute(self.input_data)
        dwd = self.eng.db.all("dwd_standardized")
        all_flags = []
        for r in dwd:
            all_flags.extend(r["quality_flags"] or [])
        # 存在空金额被默认填 0
        self.assertIn("null_amount_defaulted", all_flags)
        # 存在空科目
        self.assertIn("null_account_code", all_flags)
        # 存在科目不在主数据（9999）
        self.assertIn("account_not_in_master", all_flags)
        # 存在金额类型转换（字符串→float）
        self.assertIn("amount_type_converted", all_flags)
        # 存在空公司代码（UNKNOWN）
        self.assertIn("null_company_code", all_flags)

    def test_amount_type_conversion_values(self):
        self.eng.execute(self.input_data)
        dwd = self.eng.db.all("dwd_standardized")
        by_key = {
            (r["source"], r["source_type"], r["company_code"],
             r["account_code"], r["period"], r["voucher_no"]): r
            for r in dwd
        }
        # "5,200.00"（带千分位）→ 5200.0
        r = by_key[("用友NC", "voucher", "C002", "2202", "2026-01", "V003")]
        self.assertEqual(r["amount"], 5200.0)
        # "15000.50"（字符串）→ 15000.5
        r = by_key[("ERP-SAP", "voucher", "C001", "1122", "2026-01", "V001")]
        self.assertEqual(r["amount"], 15000.5)
        # 9800000（int）→ 9800000.0
        r = by_key[("ERP-SAP", "voucher", "C001", "6001", "2026-01", "V002")]
        self.assertEqual(r["amount"], 9800000.0)

    # ---------- ODS→DWD→ADS 数据流转正确性 ----------
    def test_ads_aggregation_matches_dwd_sum(self):
        self.eng.execute(self.input_data)
        ads = self.eng.db.all("ads_ready")
        for a in ads:
            dwd_ids = a["dwd_ids"]
            dwd_rows = self.eng.db.query(
                "dwd_standardized", where="id IN (%s)"
                % ",".join("?" * len(dwd_ids)),
                params=dwd_ids,
            )
            expected = round(sum(r["amount"] for r in dwd_rows), 2)
            self.assertEqual(a["amount"], expected)
            # source_count 与 source_list 一致
            self.assertEqual(a["source_count"], len(a["source_list"]))

    def test_reuse_rate_reflects_cross_source(self):
        out = self.eng.execute(self.input_data)
        self.assertGreaterEqual(out["reuse_rate"], 0.0)
        self.assertLessEqual(out["reuse_rate"], 1.0)
        # 跨源复用率受数据分布影响，当前 fixture 约 0.48
        self.assertGreater(out["reuse_rate"], 0.4)
        ads = self.eng.db.all("ads_ready")
        reusable = sum(1 for a in ads if a["source_count"] >= 2)
        # reuse_rate 已 round 至 4 位，用 assertAlmostEqual 容忍舍入误差
        self.assertAlmostEqual(reusable / len(ads), out["reuse_rate"], places=4)

    def test_execute_does_not_modify_template(self):
        """execute() 仍是 预处理→推理→后处理 模板方法。"""
        import inspect
        from modules.shared.base_engine import AbstractEngine
        src = inspect.getsource(AbstractEngine.execute)
        self.assertIn("_preprocess", src)
        self.assertIn("_infer", src)
        self.assertIn("_postprocess", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
