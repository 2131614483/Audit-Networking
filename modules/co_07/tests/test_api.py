"""[CO-07] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

try:
    from fastapi.testclient import TestClient
    from modules.co_07.main import app
    _client = TestClient(app)
    _CLIENT_OK = True
except TypeError:
    _client = None
    _CLIENT_OK = False
except Exception:  # pragma: no cover - 环境缺失 fastapi 时跳过
    _client = None
    _CLIENT_OK = False


@unittest.skipUnless(_CLIENT_OK, "TestClient 不可用（fastapi/httpx 未安装或版本不兼容）")
class TestAPI(unittest.TestCase):
    """API 健康检查与执行接口。"""

    def setUp(self):
        self.client = _client

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-07")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-07")

    def test_execute_with_sample(self):
        """POST /execute 用 sample_input → status=ok + asset_catalog。"""
        with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
            payload = json.load(f)
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("result", body)

    def test_execute_returns_catalog(self):
        """执行结果含 asset_catalog 与 statistics。"""
        with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
            payload = json.load(f)
        r = self.client.post("/api/v1/execute", json=payload)
        body = r.json()
        result = body["result"]
        self.assertIn("asset_catalog", result)
        self.assertIn("statistics", result)
        self.assertEqual(len(result["asset_catalog"]), 5)

    def test_execute_empty_assets(self):
        """空资产列表 → status=ok，0 资产。"""
        r = self.client.post("/api/v1/execute", json={"assets": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["statistics"]["total_assets"], 0)

    def test_execute_single_asset(self):
        """单资产输入 → 正常分类。"""
        r = self.client.post("/api/v1/execute", json={"assets": [
            {"asset_id": "A1", "name": "测试",
             "fields": [{"field_name": "邮箱", "sample_values": ["a@b.com"]}]},
        ]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(len(body["result"]["asset_catalog"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
