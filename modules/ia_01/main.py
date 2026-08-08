"""[IA-01] 动态风险地图与智能审计计划 —— 模块入口。

启动：python -m modules.ia_01.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.ia_01")

PORT = 8101

app = FastAPI(title="[IA-01] 动态风险地图与智能审计计划", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "IA-01",
        "name": "动态风险地图与智能审计计划",
        "family": "llm_rag",
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

    uvicorn.run("modules.ia_01.main:app", host="0.0.0.0", port=PORT, reload=True)
