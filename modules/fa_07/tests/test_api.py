"""[FA-07] API 单测（unittest 风格，直接调用端点函数，不依赖 TestClient）。

注：当前环境的 starlette TestClient 与 httpx 版本签名不兼容
（TestClient(app=...) 报 unexpected keyword argument 'app'），
故直接调用 router 端点函数，聚焦业务逻辑验证。
"""
from __future__ import annotations

import unittest

from modules.fa_07.api import info
from modules.fa_07.main import health


class APITest(unittest.TestCase):
    """API 端点函数单测。"""

    def test_info(self) -> None:
        body = info()
        self.assertEqual(body["module"], "FA-07")
        self.assertEqual(body["name"], "智能底稿自动生成平台")

    def test_health(self) -> None:
        body = health()
        self.assertEqual(body["module"], "FA-07")
        self.assertEqual(body["family"], "kg_gnn")
        self.assertEqual(body["status"], "ok")


if __name__ == "__main__":
    unittest.main()
