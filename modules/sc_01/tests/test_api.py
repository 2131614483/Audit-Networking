"""[SC-01] API 单测：直接调用路由处理函数（unittest 风格，纯 stdlib）。

不使用 fastapi.testclient.TestClient —— starlette/httpx 版本签名冲突
（TypeError: __init__() got an unexpected keyword argument 'app'），
改为直接调用路由处理函数，验证返回结构，零第三方依赖。
"""
from __future__ import annotations

import unittest

from modules.sc_01.api import info
from modules.sc_01.main import health


class TestApiHandlers(unittest.TestCase):
    def test_health(self):
        r = health()
        self.assertEqual(r["module"], "SC-01")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["family"], "ml_nlp")

    def test_info(self):
        r = info()
        self.assertEqual(r["module"], "SC-01")
        self.assertEqual(r["name"], "供应商风险智能评分平台")


if __name__ == "__main__":
    unittest.main()
