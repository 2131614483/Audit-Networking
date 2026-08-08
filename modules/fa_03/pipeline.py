"""[FA-03] 执行管道 —— 采集 → 数据湖分层提升 → 阈值 → 治理 → 输出。

编排顺序：
  collect(接入多源原始数据) → engine.execute(ODS→DWD→ADS 分层提升)
  → apply_thresholds(质量分级) → apply_custom_rules(治理动作)
  → output(数据湖概览 + PortableDB 持久化 / jsonl 导出)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .engine import MLEngine
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = MLEngine(config)

    def run(self, input_data: Any) -> Any:
        # 显式初始化数据湖（_load_model 幂等，重复调用安全）
        self.engine.setup()
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        """数据采集 / 接入：支持 dict 直接传入或 json 文件路径加载。"""
        if isinstance(input_data, (str, Path)):
            path = Path(input_data)
            with open(path, encoding="utf-8") as f:
                input_data = json.load(f)
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict 或指向 json 文件的路径")
        # 兜底：保证关键字段存在
        input_data.setdefault("records", [])
        input_data.setdefault("sources", sorted({
            r.get("source", "unknown") for r in input_data["records"]
        }))
        return input_data

    def _output(self, result: Any) -> Any:
        """结果输出：格式化为数据湖概览，并把 ADS/DWD 区导出 jsonl 供跨模块交换。"""
        formatted = format_output(result)
        self._persist(result)
        return formatted

    def _persist(self, result: Any) -> None:
        """把分析就绪区 / 标准化区导出为 jsonl，便于跨模块数据交换。"""
        db = getattr(self.engine, "db", None)
        if db is None:
            return
        batch_id = result.get("batch_id")
        export_dir = Path(__file__).parent / "data"
        export_dir.mkdir(parents=True, exist_ok=True)
        try:
            # 导出当前批次的 ADS / DWD 到 jsonl
            for table in ("ads_ready", "dwd_standardized"):
                rows = db.query(
                    table, where="batch_id = ?", params=[batch_id]
                ) if batch_id else db.all(table)
                out_path = export_dir / f"{table}.jsonl"
                with open(out_path, "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(
                            json.dumps(r, ensure_ascii=False, default=str) + "\n"
                        )
        except Exception:
            # 导出失败不影响主流程
            pass

    def close(self) -> None:
        self.engine.close()
