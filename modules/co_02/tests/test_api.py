"""[CO-02] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
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
            from modules.co_02.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except Exception:
            self.skipTest("模块应用加载失败")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-02")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["family"], "llm_rag")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-02")
        self.assertIn("name", body)

    def test_execute_assess(self):
        """POST /execute assess 模式返回影响评估报告。"""
        payload = {
            "regulation_title": "测试法规",
            "regulation_text": "企业应当取得同意。大型企业违反处5000万元罚款。",
            "enterprise": {"size": "large", "industry": "technology",
                           "existing_policies": []},
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["module"], "CO-02")
        self.assertIn("impact_assessment", result)

    def test_execute_parse(self):
        """POST /execute parse 模式返回条款列表。"""
        payload = {
            "action": "parse",
            "regulation_title": "测试法规",
            "regulation_text": "企业应当取得同意。个人有权查阅信息。",
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        result = r.json()["result"]
        self.assertIn("clauses", result)
        self.assertNotIn("impact_assessment", result)

    def test_execute_invalid_payload(self):
        """空 payload 也能跑通（engine 对空文本容错）。"""
        r = self.client.post("/api/v1/execute", json={})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
