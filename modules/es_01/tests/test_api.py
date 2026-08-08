"""[ES-01] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestAPI(unittest.TestCase):
    """API 健康检查 / 信息 / 执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.es_01.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except ImportError:
            self.skipTest("fastapi/testclient 未安装")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "ES-01")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "ES-01")

    def test_execute_with_sample(self):
        """POST /execute 用 sample_input 跑通，返回 status=ok。"""
        r = self.client.post("/api/v1/execute", json=_load_sample_input())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["module"], "ES-01")
        self.assertEqual(len(body["result"]["data_catalog"]), 8)

    def test_execute_with_empty(self):
        """POST /execute 空输入 → status=ok，空数据目录。"""
        r = self.client.post("/api/v1/execute", json={"data_sources": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["data_catalog"], [])

    def test_execute_returns_quality_assessment(self):
        """POST /execute 结果含 quality_assessment。"""
        r = self.client.post("/api/v1/execute", json=_load_sample_input())
        body = r.json()
        self.assertIn("quality_assessment", body["result"])
        self.assertIn("overall", body["result"]["quality_assessment"])

    def test_execute_returns_rule_alerts(self):
        """POST /execute 结果含 rule_alerts（业务规则告警）。"""
        r = self.client.post("/api/v1/execute", json=_load_sample_input())
        body = r.json()
        self.assertIn("rule_alerts", body["result"])
        self.assertIn("conflict_alerts", body["result"]["rule_alerts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
