"""[FO-01] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查与信息接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.fo_01.main import app
            self.client = TestClient(app)
        except TypeError:
            # starlette/httpx 版本不兼容时跳过
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FO-01")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
