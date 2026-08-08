"""[FA-05] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查 / 信息 / 存证执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.fa_05.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except ImportError:
            self.skipTest("fastapi/TestClient 未安装")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-05")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-05")
        self.assertIn("name", body)

    def test_execute_store(self):
        """POST /execute：store 模式 → 存证证书。"""
        payload = {"mode": "store", "transactions": [
            {"tx_id": "API-1", "bank_id": "B1", "confirmation_id": "CF1"},
        ]}
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["certificate"]["tx_ids"], ["API-1"])

    def test_execute_sign(self):
        """POST /execute：sign 模式 → 交易上链。"""
        payload = {"mode": "sign", "transactions": [
            {"tx_id": "API-2", "bank_id": "B1", "confirmation_id": "CF2"},
        ]}
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["chain_summary"]["transactions_total"], 1)

    def test_execute_empty_store(self):
        """POST /execute：空交易 store → 仅创世块。"""
        r = self.client.post("/api/v1/execute", json={"mode": "store", "transactions": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["chain_summary"]["blocks"], 1)

    def test_execute_verify_not_found(self):
        """POST /execute：verify 不存在的交易 → found_on_chain=False。"""
        payload = {"mode": "verify", "transactions": [{"tx_id": "NOPE"}]}
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertFalse(body["result"]["verification"]["found_on_chain"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
