"""[CO-06] AI可疑交易报告自动生成 —— 模块入口。

启动：python -m modules.co_06.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.co_06")

PORT = 8206

app = FastAPI(title="[CO-06] AI可疑交易报告自动生成", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "CO-06",
        "name": "AI可疑交易报告自动生成",
        "family": "kg_gnn",
        "status": "ok",
    }


def register_to_bus():
    """注册到组网总线（本次未实现总线，留桩；模块可独立运行）。"""
    logger.info("register_to_bus: 组网总线未启用，跳过")
    return False


@app.on_event("startup")
def _on_startup():
    register_to_bus()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("modules.co_06.main:app", host="0.0.0.0", port=PORT, reload=True)
