"""AbstractEngine —— 预制菜模块核心引擎基类（模板方法模式）。

所有家族引擎继承此类，实现 _load_model / _preprocess / _infer / _postprocess。
execute() 为不可修改的模板方法：预处理 → 推理 → 后处理。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AbstractEngine(ABC):
    """模块核心引擎基类。"""

    def __init__(self, config: dict | None = None):
        self.config: dict = config or {}
        self.model: Any = None

    def setup(self) -> "AbstractEngine":
        """显式触发模型/连接加载（可选）。"""
        self._load_model()
        return self

    def execute(self, input_data: Any) -> Any:
        """模板方法：预处理 → 推理 → 后处理。子类不要覆盖本方法。"""
        prepared = self._preprocess(input_data)
        result = self._infer(prepared)
        return self._postprocess(result)

    @abstractmethod
    def _load_model(self) -> None:
        """加载模型 / 连接共享平台。"""

    @abstractmethod
    def _preprocess(self, input_data: Any) -> Any:
        """数据预处理 / 特征工程。"""

    @abstractmethod
    def _infer(self, prepared: Any) -> Any:
        """核心推理 / 计算。"""

    @abstractmethod
    def _postprocess(self, result: Any) -> Any:
        """结果后处理 / 格式化。"""
