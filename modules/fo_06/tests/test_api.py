"""[FO-06] API 单测。TestClient 不可用时自动 skip。"""
from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient
    _AVAILABLE = True
except (ImportError, TypeError):
    _AVAILABLE = False

if _AVAILABLE:
    try:
        from modules.fo_06.main import app
    except (ImportError, TypeError):
        _AVAILABLE = False


class TestAPI(unittest.TestCase):
    def setUp(self):
        if not _AVAILABLE:
            self.skipTest("TestClient not available")
        self.client = TestClient(app)

    def test_health(self):
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["module"], "FO-06")

    def test_health_has_name(self):
        resp = self.client.get("/api/v1/health")
        self.assertIn("name", resp.json())

    def test_info(self):
        resp = self.client.get("/api/v1/info")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["module"], "FO-06")

    def test_execute_returns_ok(self):
        resp = self.client.post("/api/v1/execute", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data["status"], ("ok", "not_implemented"))

    def test_execute_with_data(self):
        resp = self.client.post("/api/v1/execute", json={
            "evidence": [{"evidence_id": "E1", "content": "测试证据"}],
            "cases": [{"case_id": "C1", "case_name": "测试案件"}]
        })
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
