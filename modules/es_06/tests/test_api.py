"""[ES-06] API 单测骨架。"""
from fastapi.testclient import TestClient

from modules.es_06.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "ES-06"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
