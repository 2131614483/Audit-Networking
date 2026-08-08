"""[FA-02] API 单测骨架。"""
import pytest

# 缺 fastapi/httpx 时跳过整个文件，避免 collection error 拖累 engine/pipeline 测试
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from modules.fa_02.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "FA-02"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
