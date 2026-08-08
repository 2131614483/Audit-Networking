"""[FA-09] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample():
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


class TestAPI(unittest.TestCase):
    """API 健康检查、信息接口与执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.fa_09.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except ImportError:
            self.skipTest("fastapi/TestClient 不可用")

    def test_health(self):
        """健康检查返回 module=FA-09, status=ok。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-09")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        """信息接口返回模块名称。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FA-09")
        self.assertEqual(body["name"], "AI底稿质量复核助手")

    def test_execute_with_sample(self):
        """执行接口处理 sample_input 返回 ok 结果。"""
        r = self.client.post("/api/v1/execute", json=_load_sample())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("result", body)

    def test_execute_empty(self):
        """执行接口处理空输入不报错。"""
        r = self.client.post("/api/v1/execute", json={})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")

    def test_execute_result_has_summary(self):
        """执行结果含 summary 结构。"""
        r = self.client.post("/api/v1/execute", json=_load_sample())
        body = r.json()
        result = body["result"]
        self.assertIn("summary", result)
        self.assertIn("total_workpapers", result["summary"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
