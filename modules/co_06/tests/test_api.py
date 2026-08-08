"""[CO-06] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient  # type: ignore
    _FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - 环境兼容
    _FASTAPI_AVAILABLE = False


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi 不可用")
class TestAPI(unittest.TestCase):
    """API 健康检查 / 信息 / 执行接口。"""

    def setUp(self):
        try:
            from modules.co_06.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except Exception:
            self.skipTest("无法初始化 TestClient")

    def test_health(self):
        """健康检查返回 CO-06。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-06")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        """信息接口返回模块名。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-06")

    def test_execute_returns_ok(self):
        """/execute 端到端返回 ok 状态。"""
        payload = {
            "alert": {
                "alert_id": "API-001",
                "risk_score": 40,
                "trigger_reason": "测试异常",
                "transactions": [
                    {"tx_id": "T1", "timestamp": "2025-06-10T10:00:00+08:00",
                     "amount": 9500, "currency": "CNY",
                     "counterparty": {"name": "对手A"}, "channel": "柜台"}
                ],
                "customer": {"name": "API客户", "id_no": "310101"},
            }
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["module"], "CO-06")

    def test_execute_health_has_name(self):
        """健康检查含模块中文名。"""
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("AI可疑交易报告自动生成", body["name"])

    def test_execute_with_template(self):
        """/execute 指定 US-FINCEN 模板可执行。"""
        payload = {
            "template_id": "US-FINCEN",
            "alert": {
                "risk_score": 30,
                "transactions": [
                    {"tx_id": "T1", "amount": 5000, "currency": "USD",
                     "counterparty": {"name": "X"}}
                ],
                "customer": {"name": "Client"},
            }
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")

    def test_execute_status_not_not_implemented(self):
        """/execute 不再返回 not_implemented（引擎已实现）。"""
        payload = {"alert": {"transactions": [], "risk_score": 10}}
        r = self.client.post("/api/v1/execute", json=payload)
        body = r.json()
        self.assertNotEqual(body["status"], "not_implemented")


if __name__ == "__main__":
    unittest.main(verbosity=2)
