"""[CO-06] REST API 骨架。"""
from __future__ import annotations

from fastapi import APIRouter

from .pipeline import Pipeline

router = APIRouter()


@router.get("/info")
def info():
    return {"module": "CO-06", "name": "AI可疑交易报告自动生成"}


@router.post("/execute")
def execute(payload: dict):
    """触发模块执行。核心算法未填充时返回 501 提示。"""
    pipe = Pipeline()
    try:
        return {"status": "ok", "result": pipe.run(payload)}
    except NotImplementedError as e:
        return {"status": "not_implemented", "todo": str(e)}
