"""PortableDB 单测 —— 零依赖（unittest），可独立运行：python test_portable_db.py

覆盖：建表/CRUD/JSON往返/DATETIME往返/参数化查询/upsert/jsonl导入导出/批量。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime

from modules.shared.portable_db import (
    PortableDB,
    _infer_type,
    _serialize,
    _deserialize,
)


def _new_db():
    """临时 db 文件，返回 (db, path)。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return PortableDB(tmp.name), tmp.name


class TestTypeAdapters(unittest.TestCase):
    def test_infer_type(self):
        self.assertEqual(_infer_type(True), "INTEGER")
        self.assertEqual(_infer_type(42), "INTEGER")
        self.assertEqual(_infer_type(3.14), "REAL")
        self.assertEqual(_infer_type({"a": 1}), "JSON")
        self.assertEqual(_infer_type([1, 2]), "JSON")
        self.assertEqual(_infer_type(datetime(2026, 1, 1)), "DATETIME")
        self.assertEqual(_infer_type("hello"), "TEXT")

    def test_serialize_json(self):
        self.assertEqual(_serialize({"a": 1}, "JSON"), '{"a": 1}')
        self.assertEqual(_serialize([1, 2], "JSON"), "[1, 2]")

    def test_serialize_datetime(self):
        self.assertEqual(
            _serialize(datetime(2026, 1, 1, 12, 0), "DATETIME"),
            "2026-01-01T12:00:00",
        )

    def test_deserialize_json(self):
        self.assertEqual(_deserialize('{"a": 1}', "JSON"), {"a": 1})
        # 非 JSON 字符串保持原样
        self.assertEqual(_deserialize("普通文本", "JSON"), "普通文本")

    def test_deserialize_datetime(self):
        self.assertEqual(
            _deserialize("2026-01-01T12:00:00", "DATETIME"),
            datetime(2026, 1, 1, 12, 0),
        )
        self.assertEqual(
            _deserialize("2026-01-01", "DATETIME"), datetime(2026, 1, 1, 0, 0)
        )


class TestCRUD(unittest.TestCase):
    def setUp(self):
        self.db, self.path = _new_db()
        self.db.create_table(
            "fields",
            {"id": "INTEGER PRIMARY KEY", "raw_name": "TEXT",
             "value": "REAL", "tags": "JSON"},
        )

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_insert_and_query(self):
        rid = self.db.insert(
            "fields", {"id": 1, "raw_name": "应收账款", "value": 1250000.0,
                       "tags": ["高风险", "ERP-A"]}
        )
        self.assertEqual(rid, 1)
        rows = self.db.query("fields")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["raw_name"], "应收账款")
        self.assertEqual(rows[0]["value"], 1250000.0)
        # JSON 列自动反序列化
        self.assertEqual(rows[0]["tags"], ["高风险", "ERP-A"])

    def test_insert_many(self):
        rows = [
            {"id": i, "raw_name": f"字段{i}", "value": float(i * 100),
             "tags": {"src": "ERP"}}
            for i in range(10)
        ]
        n = self.db.insert_many("fields", rows)
        self.assertEqual(n, 10)
        self.assertEqual(self.db.count("fields"), 10)

    def test_query_with_where_params(self):
        self.db.insert_many("fields", [
            {"id": 1, "raw_name": "A", "value": 50.0, "tags": []},
            {"id": 2, "raw_name": "B", "value": 200.0, "tags": []},
            {"id": 3, "raw_name": "C", "value": 500.0, "tags": []},
        ])
        # 命名参数
        rows = self.db.query(
            "fields", where="value > :v", params={"v": 100},
            order_by="value DESC",
        )
        self.assertEqual([r["raw_name"] for r in rows], ["C", "B"])
        # limit
        self.assertEqual(len(self.db.query("fields", limit=2)), 2)

    def test_count_with_where(self):
        self.db.insert_many("fields", [
            {"id": i, "raw_name": f"f{i}", "value": float(i), "tags": []}
            for i in range(5)
        ])
        self.assertEqual(self.db.count("fields", where="value >= :v",
                                       params={"v": 3}), 2)

    def test_get(self):
        self.db.insert("fields", {"id": 1, "raw_name": "X", "value": 1.0,
                                  "tags": {}})
        r = self.db.get("fields", "id = ?", [1])
        self.assertEqual(r["raw_name"], "X")
        self.assertIsNone(self.db.get("fields", "id = ?", [999]))

    def test_update(self):
        self.db.insert("fields", {"id": 1, "raw_name": "X", "value": 1.0,
                                  "tags": {}})
        n = self.db.update("fields", {"value": 99.9, "tags": ["u"]},
                           where="id = ?", params=[1])
        self.assertEqual(n, 1)
        r = self.db.get("fields", "id = ?", [1])
        self.assertEqual(r["value"], 99.9)
        self.assertEqual(r["tags"], ["u"])

    def test_delete(self):
        self.db.insert("fields", {"id": 1, "raw_name": "X", "value": 1.0,
                                  "tags": []})
        n = self.db.delete("fields", where="id = ?", params=[1])
        self.assertEqual(n, 1)
        self.assertEqual(self.db.count("fields"), 0)

    def test_upsert(self):
        self.db.upsert("fields", {"id": 1, "raw_name": "A", "value": 10.0,
                                  "tags": []})
        self.db.upsert("fields", {"id": 1, "raw_name": "A2", "value": 20.0,
                                  "tags": ["upd"]})
        self.assertEqual(self.db.count("fields"), 1)
        r = self.db.get("fields", "id = ?", [1])
        self.assertEqual(r["raw_name"], "A2")
        self.assertEqual(r["value"], 20.0)
        self.assertEqual(r["tags"], ["upd"])


class TestSchemaIntrospection(unittest.TestCase):
    def setUp(self):
        self.db, self.path = _new_db()

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)

    def test_tables_and_columns(self):
        self.db.create_table("t1", {"a": "TEXT", "b": "INTEGER"})
        self.db.create_table("t2", {"x": "REAL"})
        self.assertEqual(self.db.tables(), ["t1", "t2"])
        self.assertEqual(self.db.columns("t1"), ["a", "b"])

    def test_drop(self):
        self.db.create_table("tmp", {"a": "TEXT"})
        self.assertIn("tmp", self.db.tables())
        self.db.drop("tmp")
        self.assertNotIn("tmp", self.db.tables())


class TestJsonlRoundtrip(unittest.TestCase):
    def setUp(self):
        self.db, self.path = _new_db()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        self.db.close()
        os.unlink(self.path)
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_import_roundtrip(self):
        self.db.create_table(
            "fields",
            {"id": "INTEGER", "raw_name": "TEXT", "value": "REAL",
             "tags": "JSON"},
        )
        seed = [
            {"id": 1, "raw_name": "应收账款", "value": 1250000.0,
             "tags": ["高", "ERP"]},
            {"id": 2, "raw_name": "Revenue", "value": 4100000.0,
             "tags": {"src": "GL"}},
        ]
        self.db.insert_many("fields", seed)

        jsonl_path = os.path.join(self.tmpdir, "fields.jsonl")
        n_export = self.db.export_jsonl("fields", jsonl_path)
        self.assertEqual(n_export, 2)

        # 清空后从 jsonl 导入
        self.db.drop("fields")
        n_import = self.db.import_jsonl("fields", jsonl_path)
        self.assertEqual(n_import, 2)

        rows = self.db.query("fields", order_by="id")
        self.assertEqual(rows[0]["raw_name"], "应收账款")
        self.assertEqual(rows[0]["tags"], ["高", "ERP"])
        self.assertEqual(rows[1]["tags"], {"src": "GL"})

    def test_import_auto_schema(self):
        """无 schema 时由首行推断列类型。"""
        jsonl_path = os.path.join(self.tmpdir, "auto.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write('{"name": "A", "amount": 100.5, "flag": true, "meta": {"k": 1}}\n')
            f.write('{"name": "B", "amount": 200.0, "flag": false, "meta": [1, 2]}\n')
        n = self.db.import_jsonl("auto", jsonl_path)
        self.assertEqual(n, 2)
        cols = self.db._columns("auto")
        self.assertEqual(cols["name"], "TEXT")
        self.assertEqual(cols["amount"], "REAL")
        self.assertEqual(cols["flag"], "INTEGER")
        self.assertEqual(cols["meta"], "JSON")
        rows = self.db.all("auto")
        self.assertEqual(rows[0]["meta"], {"k": 1})
        self.assertEqual(rows[1]["meta"], [1, 2])

    def test_load_fixture(self):
        jsonl_path = os.path.join(self.tmpdir, "seed.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as f:
            f.write('{"id": 1, "name": "种子"}\n')
        n = self.db.load_fixture("seed_tbl", jsonl_path)
        self.assertEqual(n, 1)
        self.assertEqual(self.db.get("seed_tbl", "id = ?", [1])["name"], "种子")

    def test_export_all_import_all(self):
        self.db.create_table("a", {"x": "TEXT"})
        self.db.create_table("b", {"y": "INTEGER"})
        self.db.insert("a", {"x": "hello"})
        self.db.insert("b", {"y": 42})

        exp = self.db.export_all(self.tmpdir)
        self.assertEqual(exp, {"a": 1, "b": 1})

        # 新库导入
        new_db, new_path = _new_db()
        try:
            imp = new_db.import_all(self.tmpdir)
            self.assertEqual(imp, {"a": 1, "b": 1})
            self.assertEqual(new_db.get("a", "x = ?", ["hello"])["x"], "hello")
        finally:
            new_db.close()
            os.unlink(new_path)


class TestContextManager(unittest.TestCase):
    def test_with_block(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            with PortableDB(tmp.name) as db:
                db.create_table("t", {"a": "TEXT"})
                db.insert("t", {"a": "x"})
                self.assertEqual(db.count("t"), 1)
            # 退出后连接已关闭
            self.assertIsNone(db._conn)
        finally:
            os.unlink(tmp.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
