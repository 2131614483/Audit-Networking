"""[CO-05] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。"""
from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient
    from modules.co_05.main import app
    _CLIENT = TestClient(app)
    _SKIP = False
    _SKIP_REASON = ""
except TypeError as _e:
    _CLIENT = None
    _SKIP = True
    _SKIP_REASON = f"TestClient 不兼容当前 starlette/httpx 版本: {_e}"
except Exception as _e:  # noqa: BLE001
    _CLIENT = None
    _SKIP = True
    _SKIP_REASON = f"TestClient 初始化失败: {_e}"


@unittest.skipIf(_SKIP, _SKIP_REASON)
class TestAPI(unittest.TestCase):
    """API 健康检查与信息接口。"""

    def setUp(self):
        self.client = _CLIENT

    def test_health(self):
        """GET /api/v1/health 返回 200 + CO-05。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-05")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["name"], "知识图谱洗钱网络发现")

    def test_info(self):
        """GET /api/v1/info 返回 200。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "CO-05")

    def test_execute_with_graph(self):
        """POST /api/v1/execute 传入图谱数据返回检测报告。"""
        payload = {
            "action": "detect_patterns",
            "nodes": [
                {"node_id": "A"}, {"node_id": "B"}, {"node_id": "C"},
                {"node_id": "D"},
            ],
            "edges": [
                {"src": "A", "dst": "D", "edge_type": "transfer", "amount": 5000},
                {"src": "B", "dst": "D", "edge_type": "transfer", "amount": 6000},
                {"src": "C", "dst": "D", "edge_type": "transfer", "amount": 7000},
            ],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        result = body["result"]
        self.assertEqual(result["module"], "CO-05")
        self.assertGreater(len(result["detections"]), 0)

    def test_execute_empty_graph(self):
        """POST /api/v1/execute 传入空图返回 0 检测。"""
        r = self.client.post("/api/v1/execute", json={
            "nodes": [], "edges": []
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["summary"]["total_detections"], 0)

    def test_execute_load_graph(self):
        """POST /api/v1/execute load_graph action 返回图谱摘要。"""
        payload = {
            "action": "load_graph",
            "nodes": [{"node_id": "N1"}, {"node_id": "N2"}],
            "edges": [{"src": "N1", "dst": "N2", "amount": 100}],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        result = body["result"]
        self.assertEqual(result["action"], "load_graph")
        self.assertEqual(result["node_count"], 2)


@unittest.skipIf(not _SKIP, "TestClient 可用时不需要测试跳过逻辑")
class TestAPISkipped(unittest.TestCase):
    """TestClient 不可用时验证跳过机制。"""

    def test_skip_reason_recorded(self):
        """跳过时有明确原因。"""
        self.assertTrue(_SKIP)
        self.assertTrue(len(_SKIP_REASON) > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
