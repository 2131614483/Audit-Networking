"""[IA-07] API 单测骨架。"""
from fastapi.testclient import TestClient

from modules.ia_07.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "IA-07"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
