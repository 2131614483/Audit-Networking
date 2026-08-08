"""PortableDB —— 便携式数据库（sqlite3 主存 + jsonl 导入导出双模）。

零第三方依赖（sqlite3 / json / pathlib 均为 stdlib）。每个模块实例化独立
.db 文件，实现便携、隔离、可复制的本地数据底座，替代外部 PG / Neo4j / MinIO。

设计理念（中心化公用辐射）：
  - 中心：本类位于 modules/shared/，所有子模块辐射复用，统一数据访问范式。
  - 便携：单文件 .db，可随模块包复制、随 fixtures 分发。
  - 双模：sqlite3 为主存储（支持 SQL 查询/索引/事务）；jsonl 为导入导出格式
    （便于种子数据、模块间数据交换、人工调试、版本管理 diff）。
  - 自动类型适配：Python dict/list 自动 JSON 序列化往返；datetime iso 化。

典型用法：
  from modules.shared.portable_db import PortableDB
  db = PortableDB("modules/fa_02/data/fa_02.db")
  db.create_table("fields", {"raw_name": "TEXT", "value": "REAL"})
  db.insert_many("fields", [{"raw_name": "应收账款", "value": 1250000}, ...])
  rows = db.query("fields", where="value > :v", params={"v": 100000})
  db.export_jsonl("fields", "modules/fa_02/data/fields.jsonl")   # 导出
  db.import_jsonl("fields", "modules/fa_02/tests/fixtures/fields.jsonl")  # 导入
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

# sqlite3 支持的列类型 + 扩展的"软"类型（由本类负责序列化/反序列化）
_SCALAR_TYPES = {"TEXT", "INTEGER", "REAL", "NUMERIC", "BLOB"}
_SOFT_TYPES = {"JSON", "DATETIME"}


def _quote(ident: str) -> str:
    """转义 SQLite 标识符（表名/列名），用双引号包裹并转义内部双引号。"""
    return '"' + ident.replace('"', '""') + '"'


def _infer_type(value: Any) -> str:
    """由 Python 值推断 SQLite 列类型（用于 import_jsonl 自动建表）。"""
    if isinstance(value, bool):
        return "INTEGER"
    if isinstance(value, int):
        return "INTEGER"
    if isinstance(value, float):
        return "REAL"
    if isinstance(value, (dict, list, tuple)):
        return "JSON"
    if isinstance(value, (datetime, date)):
        return "DATETIME"
    return "TEXT"


def _serialize(value: Any, col_type: str) -> Any:
    """Python 值 → sqlite 存储值（按列类型序列化）。"""
    if value is None:
        return None
    if col_type == "JSON":
        return json.dumps(value, ensure_ascii=False)
    if col_type == "DATETIME":
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return str(value)
    if col_type == "INTEGER" and isinstance(value, bool):
        return int(value)
    return value


def _deserialize(value: Any, col_type: str) -> Any:
    """sqlite 存储值 → Python 值（按列类型反序列化）。"""
    if value is None:
        return None
    if col_type == "JSON":
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return value
        return value
    if col_type == "DATETIME" and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return value
    return value


class PortableDB:
    """便携式 SQLite 数据库（sqlite3 主存 + jsonl 导入导出）。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        # 启用 WAL 提升并发读；外键约束开启
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._col_types: dict[str, dict[str, str]] = {}

    # ---------- 内部工具 ----------
    def _table_exists(self, name: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        return cur.fetchone() is not None

    def _load_columns(self, name: str) -> dict[str, str]:
        """读取表的列名→类型映射（含本类的软类型标记）。"""
        cur = self._conn.execute(f"PRAGMA table_info({_quote(name)})")
        cols = {row["name"]: (row["type"] or "TEXT").upper() for row in cur.fetchall()}
        return cols

    def _columns(self, name: str) -> dict[str, str]:
        if name not in self._col_types:
            self._col_types[name] = self._load_columns(name)
        return self._col_types[name]

    # ---------- DDL ----------
    def create_table(self, name: str, schema: dict[str, str],
                     drop_if_exists: bool = False) -> None:
        """建表。schema = {列名: 类型}，类型可为 TEXT/INTEGER/REAL/JSON/DATETIME 等。

        JSON / DATETIME 为本类的"软类型"：底层以 TEXT 存储，但 insert/query 时
        自动做 JSON 序列化 / isoformat 往返。
        """
        if drop_if_exists and self._table_exists(name):
            self._conn.execute(f"DROP TABLE {_quote(name)}")
        cols = ", ".join(
            f"{_quote(col)} {typ}" for col, typ in schema.items()
        )
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS {_quote(name)} ({cols})")
        self._col_types[name] = {col: typ.upper() for col, typ in schema.items()}
        self._conn.commit()

    def drop(self, name: str) -> None:
        if self._table_exists(name):
            self._conn.execute(f"DROP TABLE {_quote(name)}")
            self._col_types.pop(name, None)
            self._conn.commit()

    def tables(self) -> list[str]:
        cur = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r[0] for r in cur.fetchall()]

    def columns(self, name: str) -> list[str]:
        return list(self._columns(name).keys())

    # ---------- DML ----------
    def insert(self, name: str, row: dict) -> int:
        """插入一行，返回 rowid。dict/list 值自动 JSON 序列化。"""
        cols = self._columns(name)
        keys = [k for k in row.keys() if k in cols]
        vals = [_serialize(row[k], cols[k]) for k in keys]
        placeholders = ", ".join("?" * len(keys))
        col_list = ", ".join(_quote(k) for k in keys)
        cur = self._conn.execute(
            f"INSERT INTO {_quote(name)} ({col_list}) VALUES ({placeholders})",
            vals,
        )
        self._conn.commit()
        return cur.lastrowid

    def insert_many(self, name: str, rows: Iterable[dict]) -> int:
        """批量插入，返回插入行数。以表列为准，跳过多余键。"""
        cols = self._columns(name)
        rows = list(rows)
        if not rows:
            return 0
        keys = [k for k in cols.keys() if any(k in r for r in rows)]
        placeholders = ", ".join("?" * len(keys))
        col_list = ", ".join(_quote(k) for k in keys)
        data = [
            [_serialize(r.get(k), cols[k]) for k in keys]
            for r in rows
        ]
        self._conn.executemany(
            f"INSERT INTO {_quote(name)} ({col_list}) VALUES ({placeholders})",
            data,
        )
        self._conn.commit()
        return len(data)

    def upsert(self, name: str, row: dict, pk: str = "id") -> None:
        """按主键 pk 插入或更新（pk 列须存在且在 row 中）。

        采用 DELETE + INSERT 策略，兼容无 PRIMARY KEY / UNIQUE 约束的表。
        """
        cols = self._columns(name)
        keys = [k for k in row.keys() if k in cols]
        if pk not in keys:
            raise KeyError(f"upsert 缺少主键列 {pk}")
        pk_val = _serialize(row[pk], cols.get(pk, "TEXT"))
        self._conn.execute(
            f"DELETE FROM {_quote(name)} WHERE {_quote(pk)}=?",
            (pk_val,),
        )
        self.insert(name, row)

    def query(self, name: str, columns: str = "*", where: str | None = None,
              params: dict | list | None = None, order_by: str | None = None,
              limit: int | None = None) -> list[dict]:
        """条件查询，返回 dict 列表（自动反序列化 JSON/DATETIME）。"""
        sql = f"SELECT {columns} FROM {_quote(name)}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        cur = self._conn.execute(sql, params or [])
        rows = cur.fetchall()
        col_types = self._columns(name) if columns == "*" else {}
        out = []
        for r in rows:
            d = dict(r)
            for k, v in d.items():
                if k in col_types:
                    d[k] = _deserialize(v, col_types[k])
            out.append(d)
        return out

    def all(self, name: str, order_by: str | None = None,
            limit: int | None = None) -> list[dict]:
        return self.query(name, order_by=order_by, limit=limit)

    def get(self, name: str, where: str, params: dict | list | None = None) -> dict | None:
        rows = self.query(name, where=where, params=params, limit=1)
        return rows[0] if rows else None

    def count(self, name: str, where: str | None = None,
              params: dict | list | None = None) -> int:
        sql = f"SELECT COUNT(*) FROM {_quote(name)}"
        if where:
            sql += f" WHERE {where}"
        cur = self._conn.execute(sql, params or [])
        return cur.fetchone()[0]

    def update(self, name: str, sets: dict, where: str,
               params: dict | list | None = None) -> int:
        cols = self._columns(name)
        set_clause = ", ".join(
            f"{_quote(k)}=?" for k in sets.keys() if k in cols
        )
        set_vals = [_serialize(v, cols[k]) for k, v in sets.items() if k in cols]
        sql = f"UPDATE {_quote(name)} SET {set_clause} WHERE {where}"
        p = list(params) if isinstance(params, list) else (
            list(params.values()) if isinstance(params, dict) else []
        )
        cur = self._conn.execute(sql, set_vals + p)
        self._conn.commit()
        return cur.rowcount

    def delete(self, name: str, where: str,
               params: dict | list | None = None) -> int:
        cur = self._conn.execute(
            f"DELETE FROM {_quote(name)} WHERE {where}", params or []
        )
        self._conn.commit()
        return cur.rowcount

    # ---------- jsonl 双模 ----------
    def export_jsonl(self, name: str, path: str | Path) -> int:
        """导出整表为 jsonl（每行一个 JSON 对象）。返回行数。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.all(name)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        return len(rows)

    def import_jsonl(self, name: str, path: str | Path,
                     schema: dict[str, str] | None = None,
                     drop_if_exists: bool = True) -> int:
        """从 jsonl 导入。无 schema 时由首行推断列类型并自动建表。返回导入行数。"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"jsonl 不存在: {path}")
        rows = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        if not rows:
            if drop_if_exists:
                self.drop(name)
            elif not self._table_exists(name) and schema:
                self.create_table(name, schema)
            return 0
        if schema is None:
            schema = {}
            for k, v in rows[0].items():
                schema[k] = _infer_type(v)
        self.create_table(name, schema, drop_if_exists=drop_if_exists)
        return self.insert_many(name, rows)

    def load_fixture(self, name: str, path: str | Path,
                     schema: dict[str, str] | None = None) -> int:
        """加载 tests/fixtures 下的 jsonl 种子数据（import_jsonl 的语义别名）。"""
        return self.import_jsonl(name, path, schema=schema, drop_if_exists=True)

    def export_all(self, dir_path: str | Path) -> dict[str, int]:
        """导出所有表到目录（每表一个 {table}.jsonl）。返回 {表名: 行数}。"""
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        return {t: self.export_jsonl(t, dir_path / f"{t}.jsonl") for t in self.tables()}

    def import_all(self, dir_path: str | Path) -> dict[str, int]:
        """导入目录下所有 {table}.jsonl。返回 {表名: 行数}。"""
        dir_path = Path(dir_path)
        result = {}
        for p in sorted(dir_path.glob("*.jsonl")):
            result[p.stem] = self.import_jsonl(p.stem, p)
        return result

    # ---------- 生命周期 ----------
    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None  # type: ignore[assignment]

    def __enter__(self) -> "PortableDB":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
