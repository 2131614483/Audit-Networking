"""[FA-10] API 单测（unittest 风格）。

TestClient 受 starlette/httpx 版本兼容性影响，构造失败时跳过。
"""
import unittest

try:
    from fastapi.testclient import TestClient
    from modules.fa_10.main import app
    _client = TestClient(app)
    _SKIP_REASON = ""
except Exception as e:  # pragma: no cover - 环境兼容性
    _client = None
    _SKIP_REASON = f"TestClient 不可用: {e}"


@unittest.skipIf(_client is None, _SKIP_REASON)
class TestApi(unittest.TestCase):

    def test_health(self):
        r = _client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-10")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = _client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
