"""[SC-05] API 单测（unittest 风格，TestClient 懒加载避免环境兼容问题）。

fastapi/TestClient 不可用时全部跳过。
"""
from __future__ import annotations

import unittest


class TestAPI(unittest.TestCase):
    """API 健康检查、信息接口与执行接口。"""

    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from modules.sc_05.main import app
            self.client = TestClient(app)
        except ImportError:
            self.skipTest("fastapi/TestClient 不可用,跳过 API 测试")
        except TypeError:
            self.skipTest("TestClient 不兼容当前 starlette/httpx 版本")

    def test_health(self):
        """健康检查返回 SC-05 / ok。"""
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-05")
        self.assertEqual(body["status"], "ok")

    def test_info(self):
        """信息接口返回模块名。"""
        r = self.client.get("/api/v1/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["module"], "SC-05")

    def test_execute_returns_ok(self):
        """execute 接口对合法输入返回 status=ok。"""
        payload = {
            "price_history": [
                {"category": "钢材", "price": 4900, "source": "市场", "record_date": "2025-01-10"},
                {"category": "钢材", "price": 4920, "source": "市场", "record_date": "2025-02-10"},
                {"category": "钢材", "price": 4950, "source": "招标", "record_date": "2025-03-10"},
                {"category": "钢材", "price": 4980, "source": "市场", "record_date": "2025-04-10"},
                {"category": "钢材", "price": 5000, "source": "招标", "record_date": "2025-05-10"},
            ],
            "benchmark_queries": [
                {"benchmark_id": "B-API-1", "category": "钢材", "price": 5200},
            ],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["module"], "SC-05")

    def test_execute_result_structure(self):
        """execute 返回含 category_benchmarks / price_comparisons 结构。"""
        payload = {
            "price_history": [
                {"category": "水泥", "price": 390, "source": "市场"},
                {"category": "水泥", "price": 395, "source": "市场"},
                {"category": "水泥", "price": 400, "source": "招标"},
                {"category": "水泥", "price": 405, "source": "市场"},
                {"category": "水泥", "price": 410, "source": "招标"},
            ],
            "benchmark_queries": [
                {"benchmark_id": "B-API-2", "category": "水泥", "price": 397},
            ],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        body = r.json()
        result = body["result"]
        self.assertIn("category_benchmarks", result)
        self.assertIn("price_comparisons", result)
        self.assertEqual(result["statistics"]["category_count"], 1)
        self.assertEqual(result["statistics"]["query_count"], 1)

    def test_execute_empty_input(self):
        """execute 对空输入正常返回（category_count=0）。"""
        r = self.client.post(
            "/api/v1/execute",
            json={"price_history": [], "benchmark_queries": []},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["result"]["statistics"]["category_count"], 0)

    def test_execute_no_baseline_query(self):
        """execute 对无基准品类的查询返回 no_baseline。"""
        payload = {
            "price_history": [
                {"category": "钢材", "price": 4900},
                {"category": "钢材", "price": 4920},
                {"category": "钢材", "price": 4950},
                {"category": "钢材", "price": 4980},
                {"category": "钢材", "price": 5000},
            ],
            "benchmark_queries": [
                {"benchmark_id": "B-API-3", "category": "未知品类", "price": 100},
            ],
        }
        r = self.client.post("/api/v1/execute", json=payload)
        body = r.json()
        comparisons = body["result"]["price_comparisons"]
        self.assertEqual(comparisons[0]["position"], "no_baseline")
        self.assertEqual(comparisons[0]["grade"], "no_data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
