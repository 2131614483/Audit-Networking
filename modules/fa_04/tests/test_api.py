"""[FA-04] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查 / 信息 / 执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.fa_04.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except ImportError:
            self.skipTest("fastapi/TestClient 未安装")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-04")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-04")
        self.assertIn("name", body)

    def test_execute_with_reconciled_confirmation(self):
        """POST /execute：已回函且一致 → reconciled。"""
        payload = {"confirmations": [
            {"confirmation_id": "API-1", "status": "replied",
             "audit_values": {"balance": 100}, "bank_values": {"balance": 100}},
        ]}
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["confirmations"][0]["status"], "reconciled")

    def test_execute_with_difference(self):
        """POST /execute：回函差异 → difference。"""
        payload = {"confirmations": [
            {"confirmation_id": "API-2", "status": "replied",
             "audit_values": {"balance": 1000}, "bank_values": {"balance": 900}},
        ]}
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["dashboard"]["diff_count"], 1)

    def test_execute_empty(self):
        """POST /execute：空函证列表 → total=0。"""
        r = self.client.post("/api/v1/execute", json={"confirmations": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["dashboard"]["total"], 0)

    def test_execute_timeout_confirmation(self):
        """POST /execute：超时函证 → timeout + 催函。"""
        from datetime import datetime, timedelta
        sent_at = (datetime.now() - timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%S")
        payload = {"confirmations": [
            {"confirmation_id": "API-3", "status": "sent",
             "sent_at": sent_at, "bank_name": "工行"},
        ]}
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["result"]["confirmations"][0]["status"], "timeout")
        self.assertEqual(len(body["result"]["escalations"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
