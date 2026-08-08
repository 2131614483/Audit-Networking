"""[FA-02] 多源数据自动标准化引擎 —— 纯 stdlib 多策略字段映射。

算法设计（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，不引入任何第三方依赖）：

  * 策略 ① 精确同义词命中：清洗后的 raw_name 命中同义词字典 → 置信度 1.0
  * 策略 ② 字符相似度：difflib.SequenceMatcher 对所有已知 raw 名打分，
                    取每个标准字段的最高分作为候选置信度
  * Top-3 候选：按置信度降序取前 3 个 (standard_name, score)
  * 科目代码标准化：标准字段 → 统一科目表 subject_code（企业会计准则口径）
  * 阈值标记：confidence < threshold.confidence(默认 0.85) → need_review
  * 增量学习：learn(raw_name, standard_name) 写入 PortableDB，下次 _load_model 合并

模型结构（self.model）：
  {
    "raw_to_std":      {cleaned_raw_name: standard_name},   # 同义词映射
    "std_to_subject":  {standard_name: subject_code},       # 标准字段→统一科目代码
    "subject_meta":    {subject_code: {subject_name, category, ...}},
    "known_raws":      [cleaned_raw_name, ...],             # 已知 raw 名（相似度匹配用）
  }
"""
from __future__ import annotations

import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# 模块根目录（用于定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fa_02.db"

# 默认最低相似度阈值：低于此值视为未匹配（避免噪声匹配）
# 0.4 的取值依据：中英文混合字段名在 0.3-0.4 区间易出现噪声命中
# （如 "pending settlement xyzqq" vs "prepayments" ≈ 0.34），0.4 可安全剔除
_MIN_SIMILARITY = 0.4
# Top-N 候选数
_TOP_N = 3

# 字段映射表 schema
_FIELD_MAPPING_SCHEMA = {
    "raw_name": "TEXT",
    "standard_name": "TEXT",
    "subject_code": "TEXT",
    "source": "TEXT",
}
# 统一科目表 schema
_SUBJECT_CODE_SCHEMA = {
    "subject_code": "TEXT",
    "subject_name": "TEXT",
    "standard_name": "TEXT",
    "category": "TEXT",
}
# 增量学习记录 schema
_INCREMENT_LEARNING_SCHEMA = {
    "raw_name": "TEXT",
    "standard_name": "TEXT",
    "subject_code": "TEXT",
    "created_at": "DATETIME",
}
# 标准化结果 schema
_RESULT_SCHEMA = {
    "source": "TEXT",
    "raw_name": "TEXT",
    "standard_name": "TEXT",
    "confidence": "REAL",
    "subject_code": "TEXT",
    "tier": "TEXT",
    "created_at": "DATETIME",
    "payload": "JSON",
}


def _clean(name: str) -> str:
    """字段名清洗：去首尾空格 + 统一小写 + 去标点（保留中英文/数字/下划线/空格）。"""
    if not isinstance(name, str):
        name = str(name)
    name = name.strip().lower()
    # 保留中文字符 (\u4e00-\u9fff) / 英文 / 数字 / 下划线 / 空格；其余替换为空
    name = re.sub(r"[^\w\u4e00-\u9fff\s]", "", name, flags=re.UNICODE)
    # 多空格合一
    name = re.sub(r"\s+", " ", name).strip()
    return name


class MLEngine(AbstractEngine):
    """多源字段标准化引擎（纯 stdlib 实现）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改：预处理 → 推理 → 后处理。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        # 允许 config 覆盖 fixtures / db 路径，便于测试隔离
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载字段映射表 + 统一科目表，合并 PortableDB 中的增量学习记录。

        数据来源（按优先级合并）：
          1. tests/fixtures/field_mappings.jsonl   同义词种子数据
          2. tests/fixtures/subject_codes.jsonl    统一科目表
          3. PortableDB increment_learnings 表     人工确认的增量映射（最高优先级）
        """
        # 1. 初始化 PortableDB（中心化公用辐射）
        self.db = PortableDB(self.db_path)

        # 2. 建表（若不存在）
        if "field_mappings" not in self.db.tables():
            self.db.create_table("field_mappings", _FIELD_MAPPING_SCHEMA)
        if "subject_codes" not in self.db.tables():
            self.db.create_table("subject_codes", _SUBJECT_CODE_SCHEMA)
        if "increment_learnings" not in self.db.tables():
            self.db.create_table("increment_learnings", _INCREMENT_LEARNING_SCHEMA)
        if "standardization_results" not in self.db.tables():
            self.db.create_table("standardization_results", _RESULT_SCHEMA)

        # 3. 若表为空，从 fixtures 导入种子数据（仅首次）
        if self.db.count("field_mappings") == 0:
            fm_fixture = self.fixtures_dir / "field_mappings.jsonl"
            if fm_fixture.exists():
                self.db.import_jsonl(
                    "field_mappings", fm_fixture,
                    schema=_FIELD_MAPPING_SCHEMA, drop_if_exists=False,
                )
        if self.db.count("subject_codes") == 0:
            sc_fixture = self.fixtures_dir / "subject_codes.jsonl"
            if sc_fixture.exists():
                self.db.import_jsonl(
                    "subject_codes", sc_fixture,
                    schema=_SUBJECT_CODE_SCHEMA, drop_if_exists=False,
                )

        # 4. 合并 DB 字段映射 + 科目元信息 + 增量学习记录
        raw_to_std: dict[str, str] = {}
        std_to_subject: dict[str, str] = {}
        subject_meta: dict[str, dict] = {}

        # 4.1 字段映射表 → raw_to_std + std_to_subject
        for row in self.db.all("field_mappings"):
            raw_clean = _clean(row["raw_name"])
            std = row["standard_name"]
            if raw_clean and std:
                raw_to_std[raw_clean] = std
            if row.get("subject_code"):
                std_to_subject[std] = row["subject_code"]

        # 4.2 统一科目表 → subject_meta + std_to_subject（补全）
        for row in self.db.all("subject_codes"):
            subject_meta[row["subject_code"]] = {
                "subject_name": row.get("subject_name"),
                "standard_name": row.get("standard_name"),
                "category": row.get("category"),
            }
            if row.get("standard_name") and row.get("subject_code"):
                std_to_subject[row["standard_name"]] = row["subject_code"]

        # 4.3 增量学习记录（人工确认的映射，最高优先级，覆盖前面）
        for row in self.db.all("increment_learnings"):
            raw_clean = _clean(row["raw_name"])
            std = row["standard_name"]
            if raw_clean and std:
                raw_to_std[raw_clean] = std
            if row.get("subject_code"):
                std_to_subject[std] = row["subject_code"]

        # 4.4 已知 raw 名清单（用于相似度匹配）
        known_raws = list(raw_to_std.keys())

        self.model = {
            "raw_to_std": raw_to_std,
            "std_to_subject": std_to_subject,
            "subject_meta": subject_meta,
            "known_raws": known_raws,
        }

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """提取字段列表，清洗字段名（保留原始名用于展示）。"""
        # 懒加载：若未显式 setup()，execute() 时自动加载模型
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 fields 列表")

        fields = input_data.get("fields", [])
        if not isinstance(fields, list):
            raise ValueError("input_data['fields'] 必须为列表")

        cleaned_fields = []
        default_source = input_data.get("source", "unknown")
        for f in fields:
            if not isinstance(f, dict) or "raw_name" not in f:
                continue
            raw_name = f["raw_name"]
            cleaned_fields.append({
                "raw_name": raw_name,                            # 原始名（展示用）
                "cleaned": _clean(raw_name),                     # 清洗后名（匹配用）
                "value": f.get("value"),
                "source": f.get("source", default_source),
            })
        return {
            "source": default_source,
            "sources": input_data.get("sources", []),
            "fields": cleaned_fields,
        }

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """多策略匹配：①精确同义词命中（1.0）②字符相似度；给出 Top-3 候选。"""
        model = self.model or {}
        raw_to_std = model.get("raw_to_std", {})
        known_raws = model.get("known_raws", [])

        results = []
        for f in prepared["fields"]:
            cleaned = f["cleaned"]
            # 候选打分：{standard_name: 最高置信度}
            scored: dict[str, float] = {}

            # 策略 ① 精确同义词命中 → 1.0
            exact_std = raw_to_std.get(cleaned)
            if exact_std:
                scored[exact_std] = 1.0

            # 策略 ② 字符相似度：对所有已知 raw 名打分，
            # 取该 raw 名对应标准字段的最高分
            for known_raw in known_raws:
                ratio = SequenceMatcher(None, cleaned, known_raw).ratio()
                if ratio <= 0.0:
                    continue
                std = raw_to_std.get(known_raw)
                if std and ratio > scored.get(std, 0.0):
                    scored[std] = ratio

            # Top-N 候选（按分数降序）
            top = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:_TOP_N]
            best_std, best_score = (top[0] if top else (None, 0.0))

            # 低于最小相似度且无精确命中 → 视为未匹配
            if best_std is None or best_score < _MIN_SIMILARITY:
                best_std = None
                best_score = 0.0
                top = []

            results.append({
                "raw_name": f["raw_name"],
                "cleaned": cleaned,
                "value": f.get("value"),
                "source": f.get("source"),
                "best_match": best_std,
                "confidence": round(best_score, 4),
                "top3_candidates": [
                    {"standard_name": s, "confidence": round(c, 4)} for s, c in top
                ],
            })
        return {"fields": results, "source": prepared.get("source")}

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """科目代码标准化 + 阈值标记 need_review / unmapped。"""
        model = self.model or {}
        std_to_subject = model.get("std_to_subject", {})
        subject_meta = model.get("subject_meta", {})
        threshold = float(self.config.get("threshold", {}).get("confidence", 0.85))

        for f in result["fields"]:
            std = f.get("best_match")
            subject_code = std_to_subject.get(std) if std else None
            f["subject_code"] = subject_code
            f["subject_meta"] = subject_meta.get(subject_code, {}) if subject_code else {}
            # 阈值标记（精细分级由 custom_thresholds 负责，此处只打 need_review）
            f["need_review"] = (f["confidence"] < threshold) or (std is None)
            f["unmapped"] = std is None
        return result

    # ------------------------------------------------------------------
    # 增量学习（人工确认映射 → PortableDB 持久化 + 当前模型即时合并）
    # ------------------------------------------------------------------
    def learn(self, raw_name: str, standard_name: str,
              subject_code: str | None = None) -> bool:
        """人工确认映射 → 写入 PortableDB increment_learnings 表，并合并进当前模型。

        - 持久化：写入 PortableDB，下次 _load_model 自动合并
        - 即时生效：当前 self.model 立即更新，无需重新加载
        """
        if self.db is None:
            self._load_model()
        assert self.db is not None

        self.db.insert("increment_learnings", {
            "raw_name": raw_name,
            "standard_name": standard_name,
            "subject_code": subject_code,
            "created_at": datetime.now(),
        })

        # 合并进当前内存模型
        model = self.model or {
            "raw_to_std": {}, "std_to_subject": {},
            "subject_meta": {}, "known_raws": [],
        }
        cleaned = _clean(raw_name)
        if cleaned:
            model["raw_to_std"][cleaned] = standard_name
            if cleaned not in model["known_raws"]:
                model["known_raws"].append(cleaned)
        if subject_code:
            model["std_to_subject"][standard_name] = subject_code
        self.model = model
        return True

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 PortableDB 连接。"""
        if self.db is not None:
            self.db.close()
            self.db = None
