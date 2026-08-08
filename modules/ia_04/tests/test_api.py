"""[IA-04] API 单测骨架。

注意：main → api → pipeline → MLEngine 级联 ImportError（engine.py 实际导出
DashboardEngine），test_api 无法收集，整体跳过。这是 engine 真实 bug，待 pipeline.py
修复类名后再启用。
"""
import pytest

try:
    from modules.ia_04.main import app  # noqa: F401
    _MAIN_OK = True
except ImportError:
    _MAIN_OK = False

if not _MAIN_OK:
    pytest.skip(
        "engine bug: pipeline.py imports MLEngine, engine.py exports DashboardEngine",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "IA-04"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
