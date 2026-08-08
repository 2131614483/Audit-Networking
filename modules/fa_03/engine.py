"""[ml_nlp] 家族核心引擎 —— FA-03 审计数据湖（三区架构 + 血缘 + 质量）。

纯 stdlib 模拟数据湖：sqlite3(PortableDB) 做存储，json/pathlib 做交换，
collections 做聚合。三区架构：
  - ODS 原始区 (ods_raw)：多源原始数据，只读不改，记录来源/时间戳/原始 schema。
  - DWD 标准化区 (dwd_standardized)：字段名标准化、类型转换、去重、空值处理。
  - ADS 分析就绪区 (ads_ready)：按分析主题聚合（科目+月份汇总）生成宽表。
元数据治理：lineage 血缘表 + quality_metrics 质量表（完整性/唯一性/一致性）。

填充规则：仅填充 4 个抽象方法体，不改 execute() 模板方法。类名保持 MLEngine。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# ------------------------------------------------------------------
# 数据湖"模型"：标准化规则（分层提升规则）
# ------------------------------------------------------------------

# 多源字段名 → 标准字段名（键统一小写比对，解决字段名不统一）
FIELD_NAME_MAP: dict[str, str] = {
    "companycode": "company_code", "company_code": "company_code",
    "公司代码": "company_code", "company": "company_code", "co_code": "company_code",
    "acct_code": "account_code", "account_code": "account_code",
    "gl_acct": "account_code", "gl_account": "account_code",
    "科目代码": "account_code", "accountcode": "account_code", "acct": "account_code",
    "acct_name": "account_name", "account_name": "account_name",
    "科目名称": "account_name", "accountname": "account_name",
    "period": "period", "accounting_period": "period",
    "期间": "period", "period_code": "period", "年月": "period",
    "amount": "amount", "balance": "amount", "period_balance": "amount",
    "金额": "amount", "amt": "amount", "借方金额": "amount", "贷方金额": "amount",
    "cur": "currency", "currency": "currency", "币种": "currency",
    "desc": "description", "description": "description",
    "摘要": "description", "narration": "description", "remark": "description",
    "vouch_no": "voucher_no", "voucher_no": "voucher_no",
    "凭证号": "voucher_no", "voucher": "voucher_no", "doc_no": "voucher_no",
}

# 科目代码 → 科目名称（统一主数据，模拟 chart of accounts）
ACCOUNT_MASTER: dict[str, str] = {
    "1001": "库存现金", "1002": "银行存款", "1122": "应收账款",
    "1123": "预付账款", "2202": "应付账款", "2203": "预收账款",
    "6001": "主营业务收入", "6601": "销售费用", "1401": "原材料",
    "1405": "库存商品",
}

# ODS 原始区表结构（v2.0 扩展多模态引用存储）
ODS_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "batch_id": "TEXT",
    "source": "TEXT",
    "source_type": "TEXT",
    "project_code": "TEXT",
    "raw_data": "JSON",
    "raw_schema": "JSON",
    "ingested_at": "DATETIME",
    # v2.0 多模态字段（内容寻址存储 CAS：uri+hash 去重，DB 只存引用）
    "text_content": "TEXT",        # 文本内容（财报/舆情/合同文本）
    "media_uri": "TEXT",           # 媒体对象存储 URI
    "media_hash": "TEXT",          # 内容哈希（CAS 去重键）
    "media_mime": "TEXT",          # MIME 类型（image/jpeg, video/mp4, ...）
    "media_modality": "TEXT",      # 模态（image/video/audio/text/timeseries）
    "event_time": "TEXT",          # 事件时间戳（ISO8601 UTC，时序对齐用）
}

# DWD 标准化区表结构（v2.0 扩展多模态引用透传）
DWD_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "batch_id": "TEXT",
    "ods_id": "INTEGER",
    "source": "TEXT",
    "source_type": "TEXT",
    "project_code": "TEXT",
    "company_code": "TEXT",
    "account_code": "TEXT",
    "account_name": "TEXT",
    "period": "TEXT",
    "amount": "REAL",
    "currency": "TEXT",
    "voucher_no": "TEXT",
    "description": "TEXT",
    "quality_flags": "JSON",
    "standardized_at": "DATETIME",
    # v2.0 多模态字段（从 ODS 透传，供下游多模态模块消费）
    "text_content": "TEXT",
    "media_uri": "TEXT",
    "media_hash": "TEXT",
    "media_mime": "TEXT",
    "media_modality": "TEXT",
    "event_time": "TEXT",
}

# ADS 分析就绪区表结构
ADS_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "batch_id": "TEXT",
    "theme": "TEXT",
    "company_code": "TEXT",
    "account_code": "TEXT",
    "account_name": "TEXT",
    "period": "TEXT",
    "amount": "REAL",
    "record_count": "INTEGER",
    "source_count": "INTEGER",
    "source_list": "JSON",
    "dwd_ids": "JSON",
    "aggregated_at": "DATETIME",
}

# 血缘表结构
LINEAGE_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "batch_id": "TEXT",
    "source_table": "TEXT",
    "source_id": "INTEGER",
    "target_table": "TEXT",
    "target_id": "INTEGER",
    "transform": "TEXT",
    "created_at": "DATETIME",
}

# 质量度量表结构
QUALITY_SCHEMA: dict[str, str] = {
    "id": "INTEGER PRIMARY KEY",
    "zone": "TEXT",
    "table_name": "TEXT",
    "batch_id": "TEXT",
    "completeness": "REAL",
    "uniqueness": "REAL",
    "consistency": "REAL",
    "overall_score": "REAL",
    "details": "JSON",
    "evaluated_at": "DATETIME",
}

_CRITICAL_FIELDS = ("company_code", "account_code", "period", "amount")


class MLEngine(AbstractEngine):
    """ml_nlp 家族引擎 —— 审计数据湖三区分层提升与治理。"""

    # ------------------------------------------------------------------
    # 模型 / 数据湖初始化
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载模型 / 初始化数据湖：PortableDB + 三区表 + 元数据表 + 提升规则。"""
        if getattr(self, "db", None) is not None:
            return  # 幂等：同一实例只初始化一次
        db_path = self.config.get("db_path") or str(
            Path(__file__).parent / "data" / "fa_03.db"
        )
        self.db = PortableDB(db_path)
        # 三区表（drop_if_exists 保证每个实例干净起点，实现测试隔离）
        self.db.create_table("ods_raw", ODS_SCHEMA, drop_if_exists=True)
        self.db.create_table("dwd_standardized", DWD_SCHEMA, drop_if_exists=True)
        self.db.create_table("ads_ready", ADS_SCHEMA, drop_if_exists=True)
        # 元数据表：血缘 + 质量
        self.db.create_table("lineage", LINEAGE_SCHEMA, drop_if_exists=True)
        self.db.create_table("quality_metrics", QUALITY_SCHEMA, drop_if_exists=True)
        # 加载分层提升规则
        self.model = {
            "field_map": FIELD_NAME_MAP,
            "account_master": ACCOUNT_MASTER,
        }
        # 运行期上下文
        self._batch_id: str | None = None
        self._project_code: str | None = None
        self._sources: list[str] = []

    def _ensure_loaded(self) -> None:
        """惰性初始化（支持不显式调用 setup() 直接 execute()）。"""
        if getattr(self, "db", None) is None:
            self._load_model()

    def close(self) -> None:
        """关闭数据湖连接。"""
        if getattr(self, "db", None) is not None:
            self.db.close()
            self.db = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # 预处理：多源原始数据写入 ODS 原始区
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """把输入的多源原始 records 写入 ODS 原始区，记录来源/时间戳/原始 schema。"""
        self._ensure_loaded()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict（含 batch_id/project_code/records）")
        batch_id = input_data.get("batch_id") or (
            f"BATCH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        project_code = input_data.get("project_code") or "UNKNOWN"
        records = input_data.get("records") or []
        self._batch_id = batch_id
        self._project_code = project_code
        now = datetime.now()
        sources_seen: set[str] = set()
        ingested = 0
        for rec in records:
            raw_data = rec.get("raw_data")
            if raw_data is None:
                raw_data = {}
            if not isinstance(raw_data, dict):
                raw_data = {"value": raw_data}
            source = rec.get("source") or "unknown"
            source_type = rec.get("source_type") or "unknown"
            rec_project = rec.get("project_code") or project_code
            ingested_at = rec.get("ingested_at") or now
            # v2.0 多模态字段提取（从 rec 或 raw_data 中）
            text_content = rec.get("text_content") or raw_data.get("text_content")
            media_uri = rec.get("media_uri") or raw_data.get("media_uri") or raw_data.get("image_ref") or raw_data.get("video_ref")
            media_hash = rec.get("media_hash") or raw_data.get("media_hash")
            media_mime = rec.get("media_mime") or raw_data.get("media_mime")
            media_modality = rec.get("media_modality") or raw_data.get("media_modality")
            if media_uri and not media_modality:
                # 根据 MIME 推断模态
                if media_mime:
                    media_modality = "image" if media_mime.startswith("image") else "video" if media_mime.startswith("video") else "audio" if media_mime.startswith("audio") else ""
                elif "image" in str(media_uri).lower():
                    media_modality = "image"
                elif "video" in str(media_uri).lower():
                    media_modality = "video"
            event_time = rec.get("event_time") or raw_data.get("event_time")
            self.db.insert("ods_raw", {
                "batch_id": batch_id,
                "source": source,
                "source_type": source_type,
                "project_code": rec_project,
                "raw_data": raw_data,
                "raw_schema": list(raw_data.keys()),
                "ingested_at": ingested_at,
                "text_content": text_content,
                "media_uri": media_uri,
                "media_hash": media_hash,
                "media_mime": media_mime,
                "media_modality": media_modality,
                "event_time": event_time,
            })
            sources_seen.add(source)
            ingested += 1
        self._sources = sorted(sources_seen)
        return {
            "batch_id": batch_id,
            "project_code": project_code,
            "ingested": ingested,
            "sources": self._sources,
        }

    # ------------------------------------------------------------------
    # 推理：ODS → DWD → ADS 分层提升 + 血缘 + 质量
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """执行三区分层提升：ODS→DWD 标准化清洗，DWD→ADS 主题聚合，计算质量与血缘。"""
        batch_id = self._batch_id or ""
        ods_rows = self.db.query(
            "ods_raw", where="batch_id = ?", params=[batch_id], order_by="id"
        )

        # ---------- ① ODS → DWD：标准化与清洗 ----------
        seen: dict[tuple, int] = {}
        dedup_removed = 0
        now = datetime.now()
        for ods in ods_rows:
            std, flags = self._standardize_record(ods, batch_id)
            # 去重键含 source：仅同源同业务键视为真重复，跨源数据予以保留
            key = (
                std["source"],
                std["source_type"],
                std["company_code"],
                std["account_code"],
                std["period"],
                std["voucher_no"] or "",
            )
            if key in seen:
                # 重复数据：合并到已保留的 DWD 记录，记录血缘
                dedup_removed += 1
                self._add_lineage(
                    "ods_raw", ods["id"], "dwd_standardized", seen[key],
                    "dedup:merged_into",
                )
                continue
            dwd_id = self.db.insert("dwd_standardized", {
                "batch_id": batch_id,
                "ods_id": ods["id"],
                "source": std["source"],
                "source_type": std["source_type"],
                "project_code": std["project_code"],
                "company_code": std["company_code"],
                "account_code": std["account_code"],
                "account_name": std["account_name"],
                "period": std["period"],
                "amount": std["amount"],
                "currency": std["currency"],
                "voucher_no": std["voucher_no"],
                "description": std["description"],
                "quality_flags": flags,
                "standardized_at": now,
                # v2.0 多模态字段透传
                "text_content": std.get("text_content"),
                "media_uri": std.get("media_uri"),
                "media_hash": std.get("media_hash"),
                "media_mime": std.get("media_mime"),
                "media_modality": std.get("media_modality"),
                "event_time": std.get("event_time"),
            })
            seen[key] = dwd_id
            self._add_lineage(
                "ods_raw", ods["id"], "dwd_standardized", dwd_id,
                "standardize:field_rename,type_convert,null_fill",
            )

        # ---------- ② DWD → ADS：按科目+月份主题聚合 ----------
        dwd_rows = self.db.query(
            "dwd_standardized", where="batch_id = ?", params=[batch_id], order_by="id"
        )
        groups: dict[tuple, dict[str, Any]] = defaultdict(
            lambda: {
                "amount": 0.0, "count": 0,
                "sources": set(), "dwd_ids": [], "account_name": "",
            }
        )
        for dwd in dwd_rows:
            key = (dwd["company_code"], dwd["account_code"], dwd["period"])
            g = groups[key]
            g["amount"] += dwd["amount"] or 0.0
            g["count"] += 1
            if dwd["source"]:
                g["sources"].add(dwd["source"])
            g["dwd_ids"].append(dwd["id"])
            if not g["account_name"] and dwd["account_name"]:
                g["account_name"] = dwd["account_name"]

        ads_count = 0
        reusable = 0
        for (company, acct, period), g in groups.items():
            src_list = sorted(g["sources"])
            ads_id = self.db.insert("ads_ready", {
                "batch_id": batch_id,
                "theme": "account_monthly_summary",
                "company_code": company,
                "account_code": acct,
                "account_name": g["account_name"],
                "period": period,
                "amount": round(g["amount"], 2),
                "record_count": g["count"],
                "source_count": len(src_list),
                "source_list": src_list,
                "dwd_ids": g["dwd_ids"],
                "aggregated_at": now,
            })
            for did in g["dwd_ids"]:
                self._add_lineage(
                    "dwd_standardized", did, "ads_ready", ads_id,
                    "aggregate:sum,count,distinct_source",
                )
            ads_count += 1
            if len(src_list) >= 2:
                reusable += 1
        reuse_rate = reusable / ads_count if ads_count else 0.0

        # ---------- ③ 计算各分区数据质量评分 ----------
        ads_rows = self.db.query(
            "ads_ready", where="batch_id = ?", params=[batch_id], order_by="id"
        )
        self._compute_quality(batch_id, ods_rows, dwd_rows, ads_rows, now)

        return {
            "batch_id": batch_id,
            "project_code": self._project_code,
            "ods_count": len(ods_rows),
            "dwd_count": len(dwd_rows),
            "ads_count": ads_count,
            "dedup_removed": dedup_removed,
            "reuse_rate": round(reuse_rate, 4),
            "sources": self._sources,
        }

    # ------------------------------------------------------------------
    # 后处理：生成数据湖统计报告
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """生成数据湖统计报告：三区记录数、质量评分、血缘关系图、复用率。"""
        batch_id = result["batch_id"]
        lineage_rows = self.db.query(
            "lineage", where="batch_id = ?", params=[batch_id], order_by="id"
        )
        quality_rows = self.db.query(
            "quality_metrics", where="batch_id = ?", params=[batch_id], order_by="id"
        )

        edges = [
            {
                "source_table": r["source_table"],
                "source_id": r["source_id"],
                "target_table": r["target_table"],
                "target_id": r["target_id"],
                "transform": r["transform"],
            }
            for r in lineage_rows
        ]
        summary: dict[str, int] = defaultdict(int)
        graph: dict[str, set[str]] = defaultdict(set)
        for e in edges:
            summary[f"{e['source_table']}->{e['target_table']}"] += 1
            graph[e["source_table"]].add(e["target_table"])

        quality: dict[str, dict[str, Any]] = {}
        for q in quality_rows:
            quality[q["zone"]] = {
                "table": q["table_name"],
                "completeness": round(q["completeness"], 4),
                "uniqueness": round(q["uniqueness"], 4),
                "consistency": round(q["consistency"], 4),
                "overall_score": round(q["overall_score"], 4),
            }

        return {
            "module": "FA-03",
            "batch_id": batch_id,
            "project_code": result["project_code"],
            "zones": {
                "ods": {
                    "table": "ods_raw",
                    "count": result["ods_count"],
                    "sources": result["sources"],
                },
                "dwd": {
                    "table": "dwd_standardized",
                    "count": result["dwd_count"],
                },
                "ads": {
                    "table": "ads_ready",
                    "count": result["ads_count"],
                    "theme": "account_monthly_summary",
                },
            },
            "quality": quality,
            "lineage": {
                "edges": edges,
                "summary": dict(summary),
                "graph": {k: sorted(v) for k, v in graph.items()},
            },
            "reuse_rate": result["reuse_rate"],
            "dedup_removed": result["dedup_removed"],
            "generated_at": datetime.now().isoformat(),
        }

    # ==================================================================
    # 私有辅助方法
    # ==================================================================
    def _std_field(self, key: str) -> str:
        """原始字段名 → 标准字段名。"""
        k = str(key).strip().lower()
        return FIELD_NAME_MAP.get(k, key)

    def _parse_amount(self, val: Any) -> float | None:
        """金额类型转换：字符串/带千分位/空值 → float。无法解析返回 None。"""
        if val is None:
            return None
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(",", "").replace("，", "")
        if s in ("", "-", "N/A", "null", "None", "NA"):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def _norm_period(self, val: Any) -> str | None:
        """期间标准化：202601 / 2026/01 / 2026.01 → 2026-01。"""
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        m = re.match(r"^(\d{4})(\d{2})$", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = re.match(r"^(\d{4})[/.\-](\d{1,2})$", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        return s

    def _standardize_record(self, ods: dict, batch_id: str) -> tuple[dict, list]:
        """把一条 ODS 记录标准化为 DWD 记录，返回 (std_dict, quality_flags)。"""
        raw = ods.get("raw_data") or {}
        mapped: dict[str, Any] = {}
        for k, v in raw.items():
            sf = self._std_field(k)
            if sf not in mapped:
                mapped[sf] = v
        flags: list[str] = []

        company = mapped.get("company_code")
        if not company or str(company).strip() == "":
            company = "UNKNOWN"
            flags.append("null_company_code")
        else:
            company = str(company).strip()

        acct = mapped.get("account_code")
        if not acct or str(acct).strip() == "":
            acct = None
            flags.append("null_account_code")
        else:
            acct = str(acct).strip()

        acct_name = mapped.get("account_name")
        if not acct_name and acct:
            acct_name = self.model["account_master"].get(acct, "")
            if not acct_name:
                flags.append("account_not_in_master")

        period = self._norm_period(mapped.get("period"))
        if not period:
            flags.append("null_period")

        amt_raw = mapped.get("amount")
        amount = self._parse_amount(amt_raw)
        if amount is None:
            amount = 0.0
            flags.append("null_amount_defaulted")
        elif isinstance(amt_raw, str):
            flags.append("amount_type_converted")

        currency = mapped.get("currency") or "CNY"
        voucher_no = mapped.get("voucher_no")
        if voucher_no:
            voucher_no = str(voucher_no).strip()
        description = mapped.get("description") or ""

        std = {
            "batch_id": batch_id,
            "source": ods.get("source") or "unknown",
            "source_type": ods.get("source_type") or "unknown",
            "project_code": ods.get("project_code") or self._project_code or "UNKNOWN",
            "company_code": company,
            "account_code": acct,
            "account_name": acct_name,
            "period": period,
            "amount": amount,
            "currency": currency,
            "voucher_no": voucher_no,
            "description": description,
            # v2.0 多模态字段透传（从 ODS 原样传递到 DWD，供下游模块消费）
            "text_content": ods.get("text_content"),
            "media_uri": ods.get("media_uri"),
            "media_hash": ods.get("media_hash"),
            "media_mime": ods.get("media_mime"),
            "media_modality": ods.get("media_modality"),
            "event_time": ods.get("event_time"),
        }
        return std, flags

    def _add_lineage(self, src_table: str, src_id: int, tgt_table: str,
                     tgt_id: int, transform: str) -> None:
        """记录一条血缘关系。"""
        self.db.insert("lineage", {
            "batch_id": self._batch_id,
            "source_table": src_table,
            "source_id": src_id,
            "target_table": tgt_table,
            "target_id": tgt_id,
            "transform": transform,
            "created_at": datetime.now(),
        })

    def _uniqueness(self, keys: list) -> float:
        """唯一性评分：唯一值数 / 总数。"""
        if not keys:
            return 1.0
        return len(set(keys)) / len(keys)

    def _ods_completeness(self, ods_rows: list) -> float:
        """ODS 完整性：4 个关键字段在 raw_data（映射后）中的非空比例。"""
        if not ods_rows:
            return 1.0
        present = 0
        total = 0
        for r in ods_rows:
            raw = r.get("raw_data") or {}
            mapped = {self._std_field(k): v for k, v in raw.items()}
            for f in _CRITICAL_FIELDS:
                total += 1
                v = mapped.get(f)
                if v not in (None, "", "null", "None"):
                    present += 1
        return present / total if total else 1.0

    def _dwd_completeness(self, dwd_rows: list) -> float:
        """DWD 完整性：关键字段非空（company_code 非UNKNOWN）比例。"""
        if not dwd_rows:
            return 1.0
        present = 0
        total = 0
        for r in dwd_rows:
            total += 4
            if r.get("company_code") and r["company_code"] != "UNKNOWN":
                present += 1
            if r.get("account_code"):
                present += 1
            if r.get("period"):
                present += 1
            if r.get("amount") is not None:
                present += 1
        return present / total if total else 1.0

    def _dwd_consistency(self, dwd_rows: list) -> float:
        """DWD 一致性：无严重问题标记（无空科目/科目不在主数据）的比例。"""
        if not dwd_rows:
            return 1.0
        ok = 0
        for r in dwd_rows:
            flags = r.get("quality_flags") or []
            if "null_account_code" not in flags and "account_not_in_master" not in flags:
                ok += 1
        return ok / len(dwd_rows)

    def _compute_quality(self, batch_id: str, ods_rows: list,
                         dwd_rows: list, ads_rows: list, now: datetime) -> None:
        """计算并写入三分区质量评分（完整性/唯一性/一致性/综合）。"""
        def _overall(c, u, cons):
            return round(0.4 * c + 0.3 * u + 0.3 * cons, 4)

        # ODS
        ods_c = round(self._ods_completeness(ods_rows), 4)
        ods_u = round(self._uniqueness([
            hashlib.md5(
                json.dumps(r.get("raw_data") or {}, sort_keys=True,
                           ensure_ascii=False).encode("utf-8")
            ).hexdigest() for r in ods_rows
        ]), 4)
        ods_cons = 1.0
        self.db.insert("quality_metrics", {
            "zone": "ods", "table_name": "ods_raw", "batch_id": batch_id,
            "completeness": ods_c, "uniqueness": ods_u, "consistency": ods_cons,
            "overall_score": _overall(ods_c, ods_u, ods_cons),
            "details": {"row_count": len(ods_rows), "sources": self._sources},
            "evaluated_at": now,
        })

        # DWD
        dwd_c = round(self._dwd_completeness(dwd_rows), 4)
        dwd_u = 1.0  # 已去重
        dwd_cons = round(self._dwd_consistency(dwd_rows), 4)
        self.db.insert("quality_metrics", {
            "zone": "dwd", "table_name": "dwd_standardized", "batch_id": batch_id,
            "completeness": dwd_c, "uniqueness": dwd_u, "consistency": dwd_cons,
            "overall_score": _overall(dwd_c, dwd_u, dwd_cons),
            "details": {"row_count": len(dwd_rows),
                        "dedup_kept": len(dwd_rows),
                        "dedup_removed": len(ods_rows) - len(dwd_rows)},
            "evaluated_at": now,
        })

        # ADS
        ads_c, ads_u, ads_cons = 1.0, 1.0, 1.0
        self.db.insert("quality_metrics", {
            "zone": "ads", "table_name": "ads_ready", "batch_id": batch_id,
            "completeness": ads_c, "uniqueness": ads_u, "consistency": ads_cons,
            "overall_score": _overall(ads_c, ads_u, ads_cons),
            "details": {"row_count": len(ads_rows),
                        "theme": "account_monthly_summary"},
            "evaluated_at": now,
        })
