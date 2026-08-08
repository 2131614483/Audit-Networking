"""[IT-01] API 单测骨架。"""
from fastapi.testclient import TestClient

from modules.it_01.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "IT-01"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
