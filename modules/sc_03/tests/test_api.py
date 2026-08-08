"""[SC-03] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。

fastapi/httpx 未安装或版本冲突时，所有用例自动 skip，不阻塞 unittest discover。
"""
from __future__ import annotations

import unittest

_FIXTURES_INPUT = {
    "suppliers": [
        {
            "supplier_id": "B1",
            "name": "测试供应商乙",
            "metrics": {
                "payment_delay_days": [2, 2, 2, 3, 2, 3, 2, 2, 3, 25, 45, 80],
                "quality_failure_rate": [0.5, 0.5, 0.5, 0.6, 0.5, 0.6,
                                         0.5, 0.5, 0.6, 5.0, 9.0, 15.0],
            },
        },
        {
            "supplier_id": "A1",
            "name": "测试供应商甲",
            "metrics": {
                "payment_delay_days": [1, 2, 1, 1, 2, 1, 2, 1, 1, 2, 1, 1],
            },
        },
    ]
}


class TestAPI(unittest.TestCase):
    """API 健康检查、信息接口与执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.sc_03.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except ImportError:
            self.skipTest("fastapi/httpx 未安装")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-03")
        self.assertEqual(body["status"], "ok")

    def test_health_has_family(self):
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("family", body)
        self.assertEqual(body["family"], "ml_nlp")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-03")
        self.assertIn("name", body)

    def test_execute_returns_ok(self):
        r = self.client.post("/api/v1/execute", json=_FIXTURES_INPUT)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["module"], "SC-03")
        self.assertIn("suppliers", result)
        self.assertIn("recommendations", result)
        self.assertIn("statistics", result)

    def test_execute_suppliers_match_input(self):
        r = self.client.post("/api/v1/execute", json=_FIXTURES_INPUT)
        body = r.json()
        self.assertEqual(
            len(body["result"]["suppliers"]),
            len(_FIXTURES_INPUT["suppliers"]),
        )
        # 高风险供应商 B1 应排在首位
        self.assertEqual(body["result"]["suppliers"][0]["supplier_id"], "B1")

    def test_execute_empty_input(self):
        r = self.client.post("/api/v1/execute", json={"suppliers": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["statistics"]["supplier_count"], 0)

    def test_execute_statistics_populated(self):
        r = self.client.post("/api/v1/execute", json=_FIXTURES_INPUT)
        body = r.json()
        stats = body["result"]["statistics"]
        self.assertEqual(stats["supplier_count"], 2)
        self.assertIn("avg_risk_score", stats)
        self.assertIn("alerts_by_level", stats)
        self.assertIn("risk_tier_distribution", stats)
        self.assertIn("rule_summary", stats)


if __name__ == "__main__":
    unittest.main(verbosity=2)
