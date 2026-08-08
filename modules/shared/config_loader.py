"""三级配置加载：default.yaml ← custom.yaml ← 运行时覆盖。

加载顺序（后者覆盖前者）：
  1. config/default.yaml   出厂默认
  2. config/custom.yaml    用户定制
  3. overrides 参数         运行时覆盖
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(module_dir: str | Path, overrides: dict | None = None) -> dict:
    """加载模块配置。module_dir 指向模块根目录（含 config/ 子目录）。"""
    cfg_dir = Path(module_dir) / "config"
    default = _read_yaml(cfg_dir / "default.yaml")
    custom = _read_yaml(cfg_dir / "custom.yaml")
    merged = _deep_merge(default, custom)
    if overrides:
        merged = _deep_merge(merged, overrides)
    return merged
