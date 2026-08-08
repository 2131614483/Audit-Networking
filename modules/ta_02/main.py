"""[TA-02] 发票四单自动匹配引擎 —— 模块入口。

启动：python -m modules.ta_02.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.ta_02")

PORT = 8502

app = FastAPI(title="[TA-02] 发票四单自动匹配引擎", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "TA-02",
        "name": "发票四单自动匹配引擎",
        "family": "ml_nlp",
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

    uvicorn.run("modules.ta_02.main:app", host="0.0.0.0", port=PORT, reload=True)
