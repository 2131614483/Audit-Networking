"""读取模块根目录的 module.yaml 元数据。"""
from __future__ import annotations

from pathlib import Path

import yaml


def load_module_yaml(module_dir: str | Path) -> dict:
    """返回 module.yaml 解析后的 dict。"""
    p = Path(module_dir) / "module.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
