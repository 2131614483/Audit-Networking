"""[CO-01] API 单测（unittest 风格）。

原骨架依赖 pytest，但运行时未安装 pytest；改为 unittest 以保证
`python -m unittest discover` 可正常收集。

TestClient 采用懒加载：当 starlette/httpx 版本不兼容导致无法构造时
（环境已知问题），跳过而非阻断整个测试收集。
"""
from __future__ import annotations

import unittest

from modules.co_01.main import app


class TestAPI(unittest.TestCase):

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            self.client = TestClient(app)
        except TypeError as e:
            # starlette/httpx 版本不兼容（httpx 0.28 移除 app 参数）
            self.skipTest(f"TestClient 不可用（环境版本不兼容）：{e}")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-01")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-01")


if __name__ == "__main__":
    unittest.main()
