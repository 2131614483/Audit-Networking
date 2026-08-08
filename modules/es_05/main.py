"""[ES-05] ESG审计知识库与AI助手 —— 模块入口。

启动：python -m modules.es_05.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.es_05")

PORT = 8705

app = FastAPI(title="[ES-05] ESG审计知识库与AI助手", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "ES-05",
        "name": "ESG审计知识库与AI助手",
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

    uvicorn.run("modules.es_05.main:app", host="0.0.0.0", port=PORT, reload=True)
