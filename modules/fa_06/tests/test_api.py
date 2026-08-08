"""[FA-06] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。

fastapi 未安装时自动跳过。
"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查与执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.fa_06.main import app
            self.client = TestClient(app)
        except ImportError:
            self.skipTest("fastapi 未安装，跳过 API 测试")
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")

    def test_health(self):
        """健康检查返回 module=FA-06, status=ok。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-06")
        self.assertEqual(body["status"], "ok")

    def test_health_name_field(self):
        """健康检查含 name 字段。"""
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("name", body)

    def test_info(self):
        """info 接口返回模块信息。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["module"], "FA-06")

    def test_execute_returns_ok(self):
        """execute 接口对合法输入返回 status=ok。"""
        payload = {
            "materiality": 50000,
            "items": [
                {"item_id": "A1", "subject": "银行存款",
                 "book_amount": 1000000, "reply_amount": 1004000,
                 "book_text": "账面余额", "reply_text": "在途资金4000"},
            ],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["module"], "FA-06")

    def test_execute_empty_input(self):
        """execute 接口对空输入返回 status=ok 且 0 项。"""
        r = self.client.post("/api/v1/execute", json={"items": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["summary"]["total_items"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
