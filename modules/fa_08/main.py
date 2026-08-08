"""[FA-08] 底稿自动勾稽检查 —— 模块入口。

启动：python -m modules.fa_08.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.fa_08")

PORT = 8008

app = FastAPI(title="[FA-08] 底稿自动勾稽检查", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "FA-08",
        "name": "底稿自动勾稽检查",
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

    uvicorn.run("modules.fa_08.main:app", host="0.0.0.0", port=PORT, reload=True)
