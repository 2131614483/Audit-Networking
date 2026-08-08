"""自定义业务规则。在 engine 之后执行，可覆盖/补充结果。"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    # TODO[custom]: 在此补充业务规则（如剔除、重分类、标记）
    return result
