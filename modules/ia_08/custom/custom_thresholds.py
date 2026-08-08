"""自定义阈值。从 config 读取，便于不改代码调参。"""
from __future__ import annotations

from typing import Any


def apply_thresholds(result: Any, config: dict) -> Any:
    # TODO[custom]: 应用 config 中的阈值（如置信度门槛、告警分级）
    # threshold = config.get("threshold", {})
    return result
