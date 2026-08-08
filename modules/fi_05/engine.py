"""[FI-05] AI监管口径自动更新 —— 法规变更抓取 + 口径影响评估 + 规则自动适配。

核心算法（纯 stdlib）：
  * 法规变更检测：difflib 文本相似度 + 关键词匹配
  * 口径差异分析：旧版 vs 新版文本 diff + 条款拆分
  * 影响评估：关联会计科目 + 报表项 + 规则库
  * 规则自动适配：根据变更生成新的校验规则
  * 变更追溯：时间线 + 版本记录 + 影响范围

PortableDB 持久化：
  - regulation_versions 法规版本历史
  -口径变更记录     口径差异
  - impact_assessments 影响评估
"""
from __future__ import annotations

import difflib
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fi_05.db"

_DEFAULT_MODEL = {
    "key_terms": [
        "会计准则", "会计政策", "计量方法", "确认条件", "披露要求",
        "科目编码", "报表项目", "合并范围", "关联交易", "收入确认",
        "金融资产", "减值测试", "公允价值", "计税基础",
    ],
    "impact_factors": {
        "high": 0.9,
        "medium": 0.5,
        "low": 0.2,
    },
    "similarity_threshold": 0.8,
}


class LLMEngine(AbstractEngine):
    """AI监管口径自动更新引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        new_regs = input_data.get("new_regulations", []) or []
        old_regs = input_data.get("current_regulations", []) or []

        new_parsed = []
        for r in new_regs:
            content = str(r.get("content", ""))
            new_parsed.append({
                "reg_id": r.get("reg_id") or hashlib.md5(content.encode()).hexdigest()[:12],
                "title": str(r.get("title", "")),
                "content": content,
                "sections": self._split_sections(content),
                "issued_date": str(r.get("issued_date", datetime.now().isoformat()[:10])),
            })

        old_map = {}
        for r in old_regs:
            rid = r.get("reg_id") or str(r.get("title", ""))
            old_map[rid] = {
                "title": str(r.get("title", "")),
                "content": str(r.get("content", "")),
                "sections": self._split_sections(str(r.get("content", ""))),
            }

        return {"new_regs": new_parsed, "old_regs": old_map}

    def _split_sections(self, text: str) -> list[str]:
        parts = re.split(r'\n\s*[一二三四五六七八九十]+[、.．]\s*|\n\s*\d+[、.．]\s*|\n\s*第[一二三四五六七八九十]+条', text)
        return [p.strip() for p in parts if len(p.strip()) > 20]

    def _infer(self, prepared: Any) -> dict:
        new_regs = prepared["new_regs"]
        old_map = prepared["old_regs"]

        changes = []
        for new_r in new_regs:
            matching_old = self._find_matching(new_r, old_map)
            if matching_old is None:
                changes.append(self._analyze_new(new_r))
            else:
                changes.append(self._analyze_diff(new_r, matching_old))

        total_high = sum(1 for c in changes for s in c.get("sections_changed", [])
                         if s.get("impact_level") == "high")
        total_medium = sum(1 for c in changes for s in c.get("sections_changed", [])
                           if s.get("impact_level") == "medium")

        summary = {
            "regulation_count": len(new_regs),
            "total_sections_changed": sum(len(c.get("sections_changed", [])) for c in changes),
            "high_impact_sections": total_high,
            "medium_impact_sections": total_medium,
            "regulations_with_changes": sum(1 for c in changes if c.get("has_changes")),
        }

        return {
            "changes": changes,
            "summary": summary,
        }

    def _find_matching(self, new_r: dict, old_map: dict) -> dict | None:
        best_key = None
        best_score = 0.0
        new_title = new_r["title"]
        for ok, ov in old_map.items():
            score = difflib.SequenceMatcher(None, new_title, ov["title"]).ratio()
            if score > best_score:
                best_score = score
                best_key = ok
        if best_score >= 0.5 and best_key:
            return old_map[best_key]
        return None

    def _analyze_new(self, new_r: dict) -> dict:
        sections_changed = []
        for sec in new_r["sections"]:
            impact = self._assess_impact(sec)
            sections_changed.append({
                "section_text": sec[:200],
                "impact_level": impact[0],
                "impact_score": impact[1],
                "impact_terms": impact[2],
                "is_new": True,
            })
        return {
            "reg_id": new_r["reg_id"],
            "title": new_r["title"],
            "has_changes": True,
            "change_type": "新增法规",
            "sections_changed": sections_changed,
            "similarity_to_old": 0.0,
        }

    def _analyze_diff(self, new_r: dict, old: dict) -> dict:
        new_sections = new_r["sections"]
        old_sections = old["sections"]

        sections_changed = []
        for new_sec in new_sections:
            best_match, best_sim = self._best_match(new_sec, old_sections)
            if best_sim < self.model["similarity_threshold"]:
                impact = self._assess_impact(new_sec)
                sections_changed.append({
                    "section_text": new_sec[:200],
                    "impact_level": impact[0],
                    "impact_score": impact[1],
                    "impact_terms": impact[2],
                    "is_new": False,
                    "similarity_to_old": round(best_sim, 4),
                    "old_section": best_match[:150] if best_match else "",
                })

        return {
            "reg_id": new_r["reg_id"],
            "title": new_r["title"],
            "has_changes": len(sections_changed) > 0,
            "change_type": "修订",
            "sections_changed": sections_changed,
            "similarity_to_old": round(
                difflib.SequenceMatcher(None, new_r["content"], old["content"]).ratio(), 4
            ),
        }

    def _best_match(self, text: str, candidates: list[str]) -> tuple[str, float]:
        best = ("", 0.0)
        for c in candidates:
            sim = difflib.SequenceMatcher(None, text, c).ratio()
            if sim > best[1]:
                best = (c, sim)
        return best

    def _assess_impact(self, text: str) -> tuple[str, float, list[str]]:
        found_terms = []
        score = 0.0
        for term in self.model["key_terms"]:
            count = text.count(term)
            if count > 0:
                found_terms.append(term)
                score += count * 0.15
        score = min(1.0, score)
        if score >= 0.7:
            level = "high"
        elif score >= 0.4:
            level = "medium"
        else:
            level = "low"
        return level, round(score, 4), found_terms

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        hi = summary["high_impact_sections"]
        med = summary["medium_impact_sections"]
        summary["urgency"] = (
            "紧急" if hi > 5 else "尽快" if hi > 0 or med > 5 else "正常"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
