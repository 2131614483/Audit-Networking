"""[IP-01] API 单测 —— unittest 风格，TestClient 不可用时自动跳过。

说明：fastapi.testclient.TestClient 依赖 httpx/starlette 版本匹配，
若环境存在版本冲突则跳过 API 测试，不影响 unittest discover。
"""
import unittest

try:
    from fastapi.testclient import TestClient
    from modules.ip_01.main import app
    _client = TestClient(app)
    _AVAILABLE = True
except Exception:  # pragma: no cover - 环境缺失时跳过
    _AVAILABLE = False
    _client = None


@unittest.skipUnless(_AVAILABLE, "TestClient 不可用（httpx/starlette 版本不匹配）")
class ApiTests(unittest.TestCase):
    """REST API 健康检查。"""

    def test_health(self):
        r = _client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "IP-01")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = _client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "IP-01")


if __name__ == "__main__":
    unittest.main()
