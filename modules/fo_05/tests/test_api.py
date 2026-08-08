"""[FO-05] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查与信息接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.fo_05.main import app
            self.client = TestClient(app)
        except ImportError:
            self.skipTest("fastapi 未安装，跳过 API 测试")
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FO-05")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FO-05")

    def test_health_has_name(self):
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("name", body)
        self.assertEqual(body["name"], "多语言智能翻译与分析")

    def test_health_has_family(self):
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("family", body)

    def test_info_has_name(self):
        r = self.client.get("/api/v1/info")
        body = r.json()
        self.assertEqual(body["name"], "多语言智能翻译与分析")

    def test_execute_endpoint(self):
        """/execute 端点返回 ok 状态。"""
        r = self.client.post("/api/v1/execute", json={
            "texts": [
                {"text_id": "T1", "content": "合同违约赔偿",
                 "source_lang": "zh", "target_lang": "en"},
            ],
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("result", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
