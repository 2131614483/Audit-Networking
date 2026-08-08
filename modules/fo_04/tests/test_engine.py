"""[FO-04] engine 单测：哈希计算 / 元数据提取 / 取证链 / 完整性验证 / 物证编目。

unittest 风格（不依赖 pytest），每个测试用独立 tmp 目录隔离 PortableDB。
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from modules.fo_04.engine import CVEngine

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_sample_input() -> dict:
    """加载 sample_input.json。"""
    with open(_FIXTURES / "sample_input.json", encoding="utf-8") as f:
        return json.load(f)


def _make_engine(tmpdir: str, **overrides) -> CVEngine:
    """构造隔离 db 的 engine 并加载模型。"""
    config = {
        "db_path": str(Path(tmpdir) / "fo_04_test.db"),
    }
    config.update(overrides)
    eng = CVEngine(config=config)
    eng.setup()
    return eng


class TestEngineLoadModel(unittest.TestCase):
    """_load_model：模型加载 + db 初始化。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_model_has_magic_numbers(self):
        """模型包含 magic_numbers 文件类型映射。"""
        self.assertIn("magic_numbers", self.engine.model)
        self.assertIn("ffd8ffe0", self.engine.model["magic_numbers"])

    def test_model_has_evidence_priority(self):
        """模型包含 evidence_priority 优先级映射。"""
        self.assertIn("evidence_priority", self.engine.model)
        self.assertIn("email", self.engine.model["evidence_priority"])

    def test_db_initialized(self):
        """_load_model 后 db 不为 None。"""
        self.assertIsNotNone(self.engine.db)


class TestEnginePreprocess(unittest.TestCase):
    """_preprocess：数据清洗 / 哈希计算 / 类型检测。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_preprocess_extracts_evidence_items(self):
        """预处理提取取证物列表。"""
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"evidence_id": "EV1", "filename": "a.pdf",
                 "content": "test", "timestamp": "2025-01-01"},
            ],
            "previous_chain_hash": "",
        })
        self.assertEqual(len(prepared["items"]), 1)
        self.assertEqual(prepared["items"][0]["evidence_id"], "EV1")

    def test_preprocess_computes_content_hash(self):
        """预处理计算 content_hash（SHA256）。"""
        content = "测试内容"
        expected_hash = hashlib.sha256(content.encode()).hexdigest()
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"evidence_id": "EV1", "filename": "a.txt",
                 "content": content, "timestamp": "2025-01-01"},
            ],
        })
        self.assertEqual(prepared["items"][0]["content_hash"], expected_hash)

    def test_preprocess_detects_file_type_by_extension(self):
        """通过扩展名识别文件类型。"""
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"filename": "doc.pdf", "content": "x", "timestamp": "t"},
                {"filename": "img.png", "content": "x", "timestamp": "t"},
                {"filename": "data.xlsx", "content": "x", "timestamp": "t"},
                {"filename": "mail.eml", "content": "x", "timestamp": "t"},
            ],
        })
        types = [it["file_type"] for it in prepared["items"]]
        self.assertIn("PDF文档", types)
        self.assertIn("图片", types)
        self.assertIn("Excel表格", types)
        self.assertIn("邮件", types)

    def test_preprocess_detects_explicit_file_type(self):
        """显式 file_type 优先于扩展名。"""
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"filename": "a.pdf", "content": "x", "timestamp": "t",
                 "file_type": "自定义类型"},
            ],
        })
        self.assertEqual(prepared["items"][0]["file_type"], "自定义类型")

    def test_preprocess_raises_on_non_dict(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine._preprocess([])

    def test_preprocess_uses_default_evidence_id(self):
        """无 evidence_id 时用 content_hash 前12位。"""
        content = "hello"
        expected_id = hashlib.sha256(content.encode()).hexdigest()[:12]
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"filename": "a.txt", "content": content, "timestamp": "t"},
            ],
        })
        self.assertEqual(prepared["items"][0]["evidence_id"], expected_id)

    def test_preprocess_passes_previous_chain_hash(self):
        """previous_chain_hash 透传到预处理结果。"""
        prepared = self.engine._preprocess({
            "evidence_items": [],
            "previous_chain_hash": "abc123",
        })
        self.assertEqual(prepared["previous_chain_hash"], "abc123")

    def test_preprocess_content_preview_truncated(self):
        """content_preview 截断为 500 字符。"""
        long_content = "x" * 600
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"filename": "a.txt", "content": long_content, "timestamp": "t"},
            ],
        })
        self.assertEqual(len(prepared["items"][0]["content_preview"]), 500)


class TestEngineHashComputation(unittest.TestCase):
    """哈希计算一致性。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_hash_consistency_same_content(self):
        """相同内容 → 相同哈希。"""
        p1 = self.engine._preprocess({
            "evidence_items": [
                {"evidence_id": "A", "filename": "a.txt",
                 "content": "same", "timestamp": "t1"},
            ],
        })
        p2 = self.engine._preprocess({
            "evidence_items": [
                {"evidence_id": "B", "filename": "b.txt",
                 "content": "same", "timestamp": "t2"},
            ],
        })
        self.assertEqual(
            p1["items"][0]["content_hash"],
            p2["items"][0]["content_hash"],
        )

    def test_hash_different_content(self):
        """不同内容 → 不同哈希。"""
        p = self.engine._preprocess({
            "evidence_items": [
                {"evidence_id": "A", "filename": "a.txt",
                 "content": "content1", "timestamp": "t1"},
                {"evidence_id": "B", "filename": "b.txt",
                 "content": "content2", "timestamp": "t2"},
            ],
        })
        self.assertNotEqual(
            p["items"][0]["content_hash"],
            p["items"][1]["content_hash"],
        )


class TestEngineInfer(unittest.TestCase):
    """_infer：链式哈希 / 时间线 / 重复检测 / 统计。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_infer_sorts_by_timestamp(self):
        """物证按时间戳排序。"""
        result = self.engine.execute(self.sample)
        timestamps = [it["timestamp"] for it in result["items"] if it["timestamp"]]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_infer_builds_chain_hash(self):
        """每个物证有 chain_hash（16位）。"""
        result = self.engine.execute(self.sample)
        for item in result["items"]:
            self.assertIn("chain_hash", item)
            self.assertEqual(len(item["chain_hash"]), 16)

    def test_infer_chain_hash_depends_on_previous(self):
        """链式哈希：第二项的 chain_hash 依赖第一项。"""
        prepared = self.engine._preprocess({
            "evidence_items": [
                {"evidence_id": "A", "filename": "a.txt",
                 "content": "content_a", "timestamp": "2025-01-01"},
                {"evidence_id": "B", "filename": "b.txt",
                 "content": "content_b", "timestamp": "2025-01-02"},
            ],
            "previous_chain_hash": "",
        })
        result = self.engine._infer(prepared)
        # 手动验证链式哈希
        chain = ""
        expected_first = hashlib.sha256(
            (chain + "A" + prepared["items"][0]["content_hash"]).encode()
        ).hexdigest()[:16]
        self.assertEqual(result["items"][0]["chain_hash"], expected_first)

    def test_infer_detects_duplicates(self):
        """相同内容的物证被识别为重复。"""
        result = self.engine.execute(self.sample)
        # EV-001 和 EV-005 内容相同
        dup_groups = result["duplicates"]
        self.assertGreater(len(dup_groups), 0)
        # 至少有一个重复组 count >= 2
        self.assertTrue(any(g["count"] >= 2 for g in dup_groups))

    def test_infer_builds_timeline(self):
        """时间线包含所有物证（按时间排序）。"""
        result = self.engine.execute(self.sample)
        timeline = result["timeline"]
        self.assertEqual(len(timeline), len(result["items"]))

    def test_infer_summary_stats(self):
        """summary 含 total_items / unique_hashes / duplicate_groups。"""
        result = self.engine.execute(self.sample)
        summary = result["summary"]
        self.assertEqual(summary["total_items"], len(self.sample["evidence_items"]))
        self.assertGreater(summary["unique_hashes"], 0)
        self.assertGreaterEqual(summary["duplicate_groups"], 1)

    def test_infer_chain_with_previous_hash(self):
        """previous_chain_hash 参与链式哈希计算。"""
        sample_a = dict(self.sample)
        sample_a["previous_chain_hash"] = "prev_hash_a"
        sample_b = dict(self.sample)
        sample_b["previous_chain_hash"] = "prev_hash_b"
        r1 = self.engine.execute(sample_a)
        r2 = self.engine.execute(sample_b)
        # 不同 previous_chain_hash → 不同最终链哈希
        self.assertNotEqual(r1["chain"], r2["chain"])

    def test_infer_counts_file_types(self):
        """summary.file_types 统计各类型数量。"""
        result = self.engine.execute(self.sample)
        file_types = result["summary"]["file_types"]
        self.assertIn("PDF文档", file_types)
        self.assertEqual(file_types["PDF文档"], 2)

    def test_infer_chain_complete_flag(self):
        """chain_complete 为 True（正常流程）。"""
        result = self.engine.execute(self.sample)
        self.assertTrue(result["summary"]["chain_complete"])

    def test_infer_final_chain_hash_matches_last_item(self):
        """最终链哈希等于最后一个物证的 chain_hash。"""
        result = self.engine.execute(self.sample)
        if result["items"]:
            self.assertEqual(
                result["chain"],
                result["items"][-1]["chain_hash"],
            )


class TestEnginePostprocess(unittest.TestCase):
    """_postprocess：完整性标记。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_postprocess_adds_forensic_integrity(self):
        """后处理添加 forensic_integrity 字段。"""
        result = self.engine.execute(self.sample)
        self.assertIn("forensic_integrity", result["summary"])

    def test_postprocess_integrity_complete(self):
        """链完整时 forensic_integrity = '完整'。"""
        result = self.engine.execute(self.sample)
        self.assertEqual(result["summary"]["forensic_integrity"], "完整")


class TestEngineEdgeCases(unittest.TestCase):
    """边界情况。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_empty_evidence_items(self):
        """空物证列表 → 0 items，空链。"""
        result = self.engine.execute({"evidence_items": []})
        self.assertEqual(result["summary"]["total_items"], 0)
        self.assertEqual(result["items"], [])

    def test_single_evidence_item(self):
        """单个物证 → chain_hash 正确计算。"""
        result = self.engine.execute({
            "evidence_items": [
                {"evidence_id": "S1", "filename": "a.txt",
                 "content": "solo", "timestamp": "2025-01-01"},
            ],
        })
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["evidence_id"], "S1")

    def test_non_dict_input_raises(self):
        """非 dict 输入抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.engine.execute("not a dict")

    def test_missing_evidence_items_key(self):
        """无 evidence_items 键 → 空列表处理。"""
        result = self.engine.execute({"previous_chain_hash": ""})
        self.assertEqual(result["summary"]["total_items"], 0)


class TestEngineEndToEnd(unittest.TestCase):
    """端到端 execute 全流程。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
        self.sample = _load_sample_input()

    def tearDown(self):
        self.engine.close()
        self.tmpdir.cleanup()

    def test_execute_full_flow(self):
        """execute 全流程：预处理 → 推理 → 后处理。"""
        result = self.engine.execute(self.sample)
        self.assertIn("items", result)
        self.assertIn("chain", result)
        self.assertIn("timeline", result)
        self.assertIn("duplicates", result)
        self.assertIn("summary", result)
        self.assertIn("forensic_integrity", result["summary"])

    def test_execute_all_items_have_chain_hash(self):
        """所有物证都有 chain_hash。"""
        result = self.engine.execute(self.sample)
        for item in result["items"]:
            self.assertTrue(item["chain_hash"])

    def test_execute_summary_authors_populated(self):
        """summary.authors 统计作者分布。"""
        result = self.engine.execute(self.sample)
        authors = result["summary"]["authors"]
        self.assertIn("张律师", authors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
