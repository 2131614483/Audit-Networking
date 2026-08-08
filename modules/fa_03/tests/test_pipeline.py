"""[FA-03] pipeline 单测 —— 端到端编排 collect→execute→thresholds→rules→output。

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

from modules.fa_03.pipeline import Pipeline  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mock_input.json"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_input():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.input_data = _load_input()
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        self.pipe = Pipeline(config={
            "db_path": self.db_path,
            "threshold": {"confidence": 0.85},
        })

    def tearDown(self):
        self.pipe.close()
        for ext in ("", "-wal", "-shm"):
            p = self.db_path + ext
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def test_run_end_to_end_overview(self):
        out = self.pipe.run(self.input_data)
        # 顶层概览结构
        self.assertEqual(out["module"], "FA-03")
        self.assertEqual(out["name"], "审计数据湖建设")
        self.assertEqual(out["status"], "ok")
        # 三区统计
        z = out["三区统计"]
        self.assertEqual(z["ods"]["count"], 57)
        self.assertEqual(z["dwd"]["count"], 54)
        self.assertGreater(z["ads"]["count"], 0)
        self.assertEqual(set(z["ods"]["sources"]),
                         {"ERP-SAP", "用友NC", "工商银行"})
        # 质量分布覆盖三区
        qd = out["质量分布"]
        for zone in ("ods", "dwd", "ads"):
            self.assertIn(zone, qd)
            self.assertIn("overall_score", qd[zone])
            self.assertIn("grade", qd[zone])

    def test_run_thresholds_and_governance_applied(self):
        out = self.pipe.run(self.input_data)
        # 阈值回写
        self.assertEqual(out["阈值"], {"confidence": 0.85})
        # ADS 综合质量 1.0 → 优质
        self.assertEqual(out["质量分布"]["ads"]["grade"], "优质")
        self.assertTrue(out["质量分布"]["ads"]["meets_threshold"])
        # 治理动作（去重产生可归档标记）
        actions = out["治理动作"]
        self.assertIsInstance(actions, list)
        self.assertTrue(any(a["action"] == "archive_expired" for a in actions))

    def test_run_lineage_summary_in_output(self):
        out = self.pipe.run(self.input_data)
        ls = out["血缘摘要"]
        self.assertEqual(ls["summary"]["ods_raw->dwd_standardized"], 57)
        self.assertEqual(ls["summary"]["dwd_standardized->ads_ready"], 54)
        self.assertEqual(ls["edge_count"], 57 + 54)
        self.assertEqual(ls["graph"]["ods_raw"], ["dwd_standardized"])

    def test_run_reuse_rate_in_range(self):
        out = self.pipe.run(self.input_data)
        self.assertIsInstance(out["复用率"], float)
        self.assertGreater(out["复用率"], 0.4)
        self.assertLessEqual(out["复用率"], 1.0)

    def test_run_accepts_json_file_path(self):
        # _collect 支持传入 json 文件路径
        out = self.pipe.run(str(FIXTURE))
        self.assertEqual(out["三区统计"]["ods"]["count"], 57)

    def test_run_persists_zone_jsonl(self):
        # _output 把 ADS/DWD 区导出为 jsonl（跨模块交换）
        out = self.pipe.run(self.input_data)
        self.assertEqual(out["status"], "ok")
        ads_jsonl = DATA_DIR / "ads_ready.jsonl"
        dwd_jsonl = DATA_DIR / "dwd_standardized.jsonl"
        self.assertTrue(ads_jsonl.exists())
        self.assertTrue(dwd_jsonl.exists())
        # 导出文件行数 == ADS 区记录数，且可被解析为 JSON
        with open(ads_jsonl, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), out["三区统计"]["ads"]["count"])
        # 抽样校验首行可解析为 JSON
        first = json.loads(lines[0])
        self.assertIn("theme", first)
        self.assertEqual(first["theme"], "account_monthly_summary")


if __name__ == "__main__":
    unittest.main(verbosity=2)
