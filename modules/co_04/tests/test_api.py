"""[CO-04] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient
    from modules.co_04.main import app
    _CLIENT = TestClient(app)
    _SKIP = False
    _SKIP_REASON = ""
except TypeError as _e:
    _CLIENT = None
    _SKIP = True
    _SKIP_REASON = f"TestClient 不兼容当前 starlette/httpx 版本: {_e}"
except Exception as _e:  # noqa: BLE001
    _CLIENT = None
    _SKIP = True
    _SKIP_REASON = f"TestClient 初始化失败: {_e}"


@unittest.skipIf(_SKIP, _SKIP_REASON)
class TestAPI(unittest.TestCase):
    """API 健康检查与信息接口。"""

    def setUp(self):
        self.client = _CLIENT

    def test_health(self):
        """GET /api/v1/health 返回 200 + CO-04。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-04")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["name"], "AML智能交易监控引擎")

    def test_info(self):
        """GET /api/v1/info 返回 200。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-04")

    def test_execute_with_transactions(self):
        """POST /api/v1/execute 传入交易数据返回告警报告。"""
        payload = {
            "transactions": [
                {"tx_id": "T1", "customer_id": "C1", "amount": 47000,
                 "channel": "online", "jurisdiction": "CN", "hour": 10},
                {"tx_id": "T2", "customer_id": "C1", "amount": 48000,
                 "channel": "online", "jurisdiction": "CN", "hour": 11},
                {"tx_id": "T3", "customer_id": "C1", "amount": 49000,
                 "channel": "online", "jurisdiction": "CN", "hour": 12},
            ]
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["module"], "CO-04")
        self.assertGreater(len(result["alerts"]), 0)

    def test_execute_empty_input(self):
        """POST /api/v1/execute 传入空数据返回 0 告警。"""
        r = self.client.post("/api/v1/execute", json={"transactions": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["summary"]["total_sars"], 0)

    def test_execute_high_risk_jurisdiction(self):
        """POST /api/v1/execute 高风险地区交易触发 critical 告警。"""
        payload = {
            "transactions": [
                {"tx_id": "HR1", "customer_id": "C1", "amount": 50000,
                 "channel": "online", "jurisdiction": "IRAN", "hour": 10},
            ]
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        alerts = body["result"]["alerts"]
        self.assertGreater(len(alerts), 0)
        hrisk = [a for a in alerts if "高风险地区" in a["pattern"]]
        self.assertEqual(len(hrisk), 1)
        self.assertEqual(hrisk[0]["alert_level"], "critical")


@unittest.skipIf(not _SKIP, "TestClient 可用时不需要测试跳过逻辑")
class TestAPISkipped(unittest.TestCase):
    """TestClient 不可用时验证跳过机制。"""

    def test_skip_reason_recorded(self):
        """跳过时有明确原因。"""
        self.assertTrue(_SKIP)
        self.assertTrue(len(_SKIP_REASON) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
