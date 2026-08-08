"""[SC-02] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest

_FIXTURES_INPUT = {
    "suppliers": [
        {"supplier_id": "A1", "name": "供应商甲", "node_type": "supplier"},
        {"supplier_id": "A2", "name": "供应商乙", "node_type": "supplier"},
        {"supplier_id": "A3", "name": "客户丙", "node_type": "customer"},
    ],
    "relations": [
        {"source": "A1", "target": "A3", "relation_type": "supplies", "weight": 1.0},
        {"source": "A2", "target": "A3", "relation_type": "supplies", "weight": 1.0},
    ],
}


class TestAPI(unittest.TestCase):
    """API 健康检查、信息接口与执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.sc_02.main import app
            self.client = TestClient(app)
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")
        except ImportError:
            self.skipTest("fastapi/httpx 未安装")

    def test_health(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-02")
        self.assertEqual(body["status"], "ok")

    def test_health_has_family(self):
        r = self.client.get("/api/v1/health")
        body = r.json()
        self.assertIn("family", body)
        self.assertEqual(body["family"], "kg_gnn")

    def test_info(self):
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-02")
        self.assertIn("name", body)

    def test_execute_returns_ok(self):
        r = self.client.post("/api/v1/execute", json=_FIXTURES_INPUT)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["module"], "SC-02")
        self.assertIn("network", result)

    def test_execute_network_nodes_match(self):
        r = self.client.post("/api/v1/execute", json=_FIXTURES_INPUT)
        body = r.json()
        self.assertEqual(
            len(body["result"]["network"]["nodes"]),
            len(_FIXTURES_INPUT["suppliers"]),
        )

    def test_execute_empty_input(self):
        r = self.client.post("/api/v1/execute",
                             json={"suppliers": [], "relations": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["statistics"]["node_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
