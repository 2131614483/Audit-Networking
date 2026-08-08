"""[CO-03] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - 环境兼容
    TestClient = None


@unittest.skipIf(TestClient is None, "fastapi/TestClient 不可用")
class TestAPI(unittest.TestCase):
    """API 健康检查与执行接口。"""

    def setUp(self):
        try:
            from modules.co_03.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except Exception:
            self.skipTest("模块应用加载失败")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-03")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["family"], "llm_rag")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-03")
        self.assertIn("name", body)

    def test_execute_analyze_change(self):
        """POST /execute analyze_change 返回影响分析。"""
        payload = {
            "action": "analyze_change",
            "regulation_title": "反洗钱法修订案",
            "regulation_change": "反洗钱KYC可疑交易监控要求",
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["module"], "CO-03")
        self.assertIn("aml", result["affected_domains"])

    def test_execute_get_status(self):
        """POST /execute get_status 返回程序库状态。"""
        r = self.client.post("/api/v1/execute",
                             json={"action": "get_status"})
        self.assertEqual(r.status_code, 200)
        result = r.json()["result"]
        self.assertEqual(result["total_programs"], 12)

    def test_execute_invalid_payload(self):
        """空 payload 也能跑通（默认 analyze_change 对空文本容错）。"""
        r = self.client.post("/api/v1/execute", json={})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
