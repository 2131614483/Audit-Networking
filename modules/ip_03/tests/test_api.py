"""[IP-03] API 单测骨架。"""
from fastapi.testclient import TestClient

from modules.ip_03.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "IP-03"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
