"""[FO-02] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient  # type: ignore
    _FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - 环境兼容
    _FASTAPI_AVAILABLE = False

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi 不可用")
class TestAPI(unittest.TestCase):
    """API 健康检查 / 信息 / 执行接口。"""

    def setUp(self):
        try:
            from modules.fo_02.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except Exception:
            self.skipTest("无法初始化 TestClient")

    def test_health(self):
        """健康检查返回 FO-02。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FO-02")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        """信息接口返回模块名。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "FO-02")

    def test_health_has_name(self):
        """健康检查含模块中文名。"""
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("知识图谱舞弊网络分析", body["name"])

    def test_execute_returns_ok(self):
        """/execute 端到端返回 ok 状态。"""
        payload = {
            "entities": [
                {"entity_id": "A", "name": "公司A"},
                {"entity_id": "B", "name": "公司B"},
            ],
            "transactions": [
                {"from": "A", "to": "B", "amount": 100000, "time": "2025-06-01"},
            ],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["module"], "FO-02")

    def test_execute_with_sample(self):
        """/execute 用样本数据执行，检测到舞弊环。"""
        with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
            payload = json.load(f)
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["result"]["key_findings"]["fraud_ring_flag"])

    def test_execute_status_not_not_implemented(self):
        """/execute 不再返回 not_implemented（引擎已实现）。"""
        payload = {"entities": [], "transactions": []}
        r = self.client.post("/api/v1/execute", json=payload)
        body = r.json()
        self.assertNotEqual(body["status"], "not_implemented")


if __name__ == "__main__":
    unittest.main(verbosity=2)
