"""[SC-04] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。

fastapi/TestClient 不可用时全部跳过。
"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查、信息接口与执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.sc_04.main import app
            self.client = TestClient(app)
        except ImportError:
            self.skipTest("fastapi/TestClient 不可用,跳过 API 测试")
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")

    def test_health(self):
        """健康检查返回 SC-04 / ok。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-04")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        """信息接口返回模块名。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-04")

    def test_execute_returns_ok(self):
        """execute 接口对合法输入返回 status=ok。"""
        payload = {
            "orders": [
                {"order_id": "API-1", "supplier_id": "S1", "category": "测试",
                 "unit_price": 100, "quantity": 10, "total_amount": 1000},
                {"order_id": "API-2", "supplier_id": "S2", "category": "测试",
                 "unit_price": 120, "quantity": 10, "total_amount": 1200},
            ]
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["module"], "SC-04")

    def test_execute_result_structure(self):
        """execute 返回含 flagged_transactions / statistics 结构。"""
        payload = {
            "orders": [
                {"order_id": "API-1", "supplier_id": "S1", "category": "测试",
                 "unit_price": 100, "quantity": 10, "total_amount": 1000},
                {"order_id": "API-2", "supplier_id": "S2", "category": "测试",
                 "unit_price": 110, "quantity": 10, "total_amount": 1100},
            ]
        }
        r = self.client.post("/api/v1/execute", json=payload)
        body = r.json()
        result = body["result"]
        self.assertIn("flagged_transactions", result)
        self.assertIn("statistics", result)
        self.assertEqual(result["statistics"]["order_count"], 2)

    def test_execute_empty_orders(self):
        """execute 对空订单列表正常返回（order_count=0）。"""
        r = self.client.post("/api/v1/execute", json={"orders": []})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["statistics"]["order_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
