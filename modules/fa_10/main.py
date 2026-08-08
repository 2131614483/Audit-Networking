"""[FA-10] 知识图谱关联方发现引擎 —— 模块入口。

启动：python -m modules.fa_10.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.fa_10")

PORT = 8010

app = FastAPI(title="[FA-10] 知识图谱关联方发现引擎", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "FA-10",
        "name": "知识图谱关联方发现引擎",
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

    uvicorn.run("modules.fa_10.main:app", host="0.0.0.0", port=PORT, reload=True)
