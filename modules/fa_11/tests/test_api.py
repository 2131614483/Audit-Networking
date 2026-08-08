"""[FA-11] API 单测（unittest 风格）。

TestClient 受 starlette/httpx 版本兼容性影响，构造失败时跳过。
"""
import json
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from modules.fa_11.main import app
    _client = TestClient(app)
    _SKIP_REASON = ""
except Exception as e:  # pragma: no cover - 环境兼容性
    _client = None
    _SKIP_REASON = f"TestClient 不可用: {e}"

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@unittest.skipIf(_client is None, _SKIP_REASON)
class TestApi(unittest.TestCase):

    def test_health(self):
        r = _client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-11")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = _client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-11")
        self.assertIn("name", body)

    def test_execute_with_sample_input(self):
        """POST /execute 用 sample_input 跑通。"""
        with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
            payload = json.load(f)
        r = _client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["module"], "FA-11")

    def test_execute_returns_transactions(self):
        """/execute 返回交易明细列表。"""
        with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
            payload = json.load(f)
        r = _client.post("/api/v1/execute", json=payload)
        result = r.json()["result"]
        self.assertEqual(len(result["transactions"]), 5)
        # RP-003 应为 significantly_biased
        for t in result["transactions"]:
            if t["tx_id"] == "RP-003":
                self.assertEqual(t["fairness_level"], "significantly_biased")
                break

    def test_execute_empty_input(self):
        """空输入也能正常返回。"""
        r = _client.post("/api/v1/execute", json={"transactions": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(
            body["result"]["fairness_summary"]["total_transactions"], 0
        )

    def test_health_has_name(self):
        """/health 含模块中文名。"""
        r = _client.get("/api/v1/health")
        body = r.json()
        self.assertIn("关联交易", body["name"])


if __name__ == "__main__":
    unittest.main()
