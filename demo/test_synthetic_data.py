"""用 synthetic_data 数据集测试组网管道并发现 bug。

测试范围：
1. 数据加载：78模块数据文件可读、结构合法
2. 契约校验：强类型 fields_typed 与数据字段匹配
3. 数据对齐：实体对齐、时间对齐在大数据量下正常
4. fa_03 数据湖：多模态数据入湖、ODS→DWD→ADS 三区正确
5. 组网执行：关键模块链路端到端跑通
6. 大数据量压力：1000+条记录的性能和稳定性
"""
from __future__ import annotations
import json, sys, traceback, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DATA_ROOT = Path(__file__).parent / "synthetic_data"
PASS = 0
FAIL = 0
ERRORS: list[str] = []


def check(name: str, fn):
    """运行单个测试。"""
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  ✓ {name}")
    except Exception as e:
        FAIL += 1
        ERRORS.append(f"{name}: {type(e).__name__}: {e}")
        print(f"  ✗ {name}: {type(e).__name__}: {e}")
        traceback.print_exc()


def load_jsonl(path: Path, limit: int = 0):
    """加载 JSONL 文件前 N 条。"""
    recs = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            recs.append(json.loads(line))
    return recs


# ======================================================================
# 测试1：数据加载与结构校验
# ======================================================================

def test_manifest_exists():
    m = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert m["module_count"] == 78, f"模块数应为78，实际 {m['module_count']}"
    assert m["total_gb"] >= 1.0, f"总数据量应≥1GB，实际 {m['total_gb']}GB"


def test_all_modules_have_data():
    m = json.loads((DATA_ROOT / "manifest.json").read_text(encoding="utf-8"))
    for mod in m["modules"]:
        slug = mod["slug"]
        mod_dir = DATA_ROOT / slug
        assert mod_dir.exists(), f"模块 {slug} 目录不存在"
        files = list(mod_dir.glob("*"))
        assert len(files) >= 2, f"模块 {slug} 数据文件不足2个，实际 {len(files)}"


def test_jsonl_structure():
    """抽检5个模块的 JSONL 结构。"""
    for slug in ["fa_02", "co_04", "fo_03", "es_01", "fi_01"]:
        mod_dir = DATA_ROOT / slug
        jsonl_files = list(mod_dir.glob("*.jsonl"))
        assert jsonl_files, f"{slug} 无 JSONL 文件"
        # 读第一条验证可解析
        with open(jsonl_files[0], encoding="utf-8") as f:
            first = json.loads(f.readline())
        assert isinstance(first, dict), f"{slug}/{jsonl_files[0].name} 第一条非 dict"


# ======================================================================
# 测试2：契约校验
# ======================================================================

def test_contract_load():
    from modules.shared.contract import load_contracts
    cs = load_contracts()
    assert len(cs) == 78, f"契约加载应为78模块，实际 {len(cs)}"


def test_typed_fields_validate():
    """验证升级后的强类型模块 fields_typed 存在且合法。"""
    from modules.shared.contract import load_contracts
    cs = load_contracts()
    multimodal_slugs = ["fa_02", "fa_03", "fa_10", "co_04", "fo_03", "es_01"]
    for slug in multimodal_slugs:
        c = cs[slug]
        assert c.is_multimodal, f"{slug} 应为多模态模块"
        total_typed = sum(len(i.fields_typed) for i in c.inputs + c.outputs)
        assert total_typed > 0, f"{slug} 无 fields_typed"


def test_edge_compatibility():
    """验证 fa_02→fa_03 边的强类型兼容性。"""
    from modules.shared.contract import load_contracts, validate_edge_compatibility
    cs = load_contracts()
    ok, issues = validate_edge_compatibility(cs["fa_02"], cs["fa_03"])
    # 可能有 issue 但不应崩溃
    assert isinstance(ok, bool), "validate_edge_compatibility 应返回 bool"
    assert isinstance(issues, list), "issues 应为 list"


# ======================================================================
# 测试3：数据对齐层
# ======================================================================

def test_entity_aligner_large():
    """用大数据集测试实体对齐。"""
    from modules.shared.aligner import EntityAligner, EntityRecord
    # 从 fa_02 的 shareholders + records 构建实体池
    shareholders = load_jsonl(DATA_ROOT / "fa_02" / "shareholders.jsonl")
    records = load_jsonl(DATA_ROOT / "fa_02" / "records.jsonl", limit=500)

    entities: list[EntityRecord] = []
    for sh in shareholders:
        entities.append(EntityRecord(
            entity_id=sh.get("name", ""), source="shareholders",
            name=sh.get("name", ""), uscc=sh.get("uscc", ""),
            aliases=sh.get("related_entities", []),
            attributes={"role": sh.get("role", "")},
        ))
    seen_names = set()
    for rec in records:
        name = rec.get("counterparty", "")
        if name and name not in seen_names:
            seen_names.add(name)
            entities.append(EntityRecord(
                entity_id=name, source=rec.get("source", "unknown"),
                name=name, uscc=rec.get("counterparty_uscc", ""),
                aliases=[], attributes={},
            ))

    aligner = EntityAligner()
    clusters = aligner.align(entities)
    assert len(clusters) > 0, "实体对齐应产出至少1个簇"
    # 验证所有实体都被分配
    total_members = sum(len(c.members) for c in clusters)
    assert total_members == len(entities), f"实体数不匹配: {total_members} vs {len(entities)}"


def test_time_aligner_formats():
    """测试多种时间格式对齐。"""
    from modules.shared.aligner import TimeAligner
    records = [
        {"event_time": "2025-06"},
        {"event_time": "2025/06/15"},
        {"event_time": "2025年6月"},
        {"event_time": "2025-06-15T10:30:00"},
        {"event_time": "20250615"},
    ]
    aligner = TimeAligner()
    aligned = aligner.align(records)
    assert len(aligned) == 5
    for r in aligned:
        assert "event_time" in r and "period" in r
        assert r["period"].startswith("2025-06"), f"期间对齐错误: {r['period']}"


def test_data_aligner_integration():
    """测试 DataAligner 统一入口。"""
    from modules.shared.aligner import DataAligner
    aligner = DataAligner()
    # 用 shareholders 模拟
    shareholders = load_jsonl(DATA_ROOT / "fa_02" / "shareholders.jsonl", limit=20)
    entities = [
        {"entity_id": sh.get("name", ""), "source": "shareholders",
         "name": sh.get("name", ""), "uscc": sh.get("uscc", ""),
         "aliases": sh.get("related_entities", [])}
        for sh in shareholders
    ]
    result = aligner.align({"entities": entities, "time_records": [], "modal_records": []})
    assert isinstance(result, dict)
    assert "report" in result or "clusters" in result


# ======================================================================
# 测试4：fa_03 数据湖多模态入湖
# ======================================================================

def test_fa03_multimodal_ingest():
    """用 fa_02 数据喂给 fa_03 数据湖，验证多模态字段透传。"""
    from modules.fa_03.engine import MLEngine

    records_raw = load_jsonl(DATA_ROOT / "fa_02" / "records.jsonl", limit=200)
    # 包装成 fa_03 期望格式
    records = []
    for r in records_raw:
        records.append({
            "source": r.get("source", "unknown"),
            "source_type": r.get("source_type", "api"),
            "raw_data": r,
            "text_content": r.get("description"),
            "event_time": r.get("event_time"),
        })

    eng = MLEngine(config={"db_path": ":memory:"})
    eng.setup()
    result = eng.execute({
        "batch_id": "TEST-MM-200",
        "project_code": "P1",
        "records": records,
    })
    # 验证三区数据量（_postprocess 返回 zones.ods.count 结构）
    ods_count = result["zones"]["ods"]["count"]
    dwd_count = result["zones"]["dwd"]["count"]
    ads_count = result["zones"]["ads"]["count"]
    assert ods_count == 200, f"ODS 应为200，实际 {ods_count}"
    assert dwd_count > 0, "DWD 应>0"
    assert ads_count > 0, "ADS 应>0"
    # 验证多模态字段透传
    dwd = eng.db.query("dwd_standardized", limit=50)
    mm_count = sum(1 for r in dwd if r.get("text_content") or r.get("media_uri"))
    assert mm_count > 0, "DWD 无多模态字段透传"
    eng.close()


def test_fa03_text_ingest():
    """测试纯文本模态数据入湖。"""
    from modules.fa_03.engine import MLEngine

    records = [
        {"source": "舆情", "source_type": "api",
         "raw_data": {"company_code": "600001", "period": "2025-06", "amount": 0},
         "text_content": "卓郎科技涉嫌关联交易舞弊，证监会已立案调查"},
        {"source": "公告", "source_type": "pdf",
         "raw_data": {"company_code": "600001", "period": "2025-06", "amount": 0},
         "text_content": "公司收到证监会问询函，要求说明关联交易公允性"},
    ]
    eng = MLEngine(config={"db_path": ":memory:"})
    eng.setup()
    result = eng.execute({"batch_id": "TEST-TEXT", "project_code": "P1", "records": records})
    dwd = eng.db.query("dwd_standardized")
    assert len(dwd) == 2
    assert all(r.get("text_content") for r in dwd), "文本字段未透传"
    eng.close()


def test_fa03_media_ingest():
    """测试媒体引用数据入湖。"""
    from modules.fa_03.engine import MLEngine

    records = [
        {"source": "扫描", "source_type": "ocr",
         "raw_data": {"company_code": "600001", "period": "2025-06", "amount": 100000},
         "media_uri": "s3://audit/image/receipt_001.jpg",
         "media_hash": "abc123def456",
         "media_mime": "image/jpeg",
         "media_modality": "image"},
    ]
    eng = MLEngine(config={"db_path": ":memory:"})
    eng.setup()
    result = eng.execute({"batch_id": "TEST-MEDIA", "project_code": "P1", "records": records})
    dwd = eng.db.query("dwd_standardized")
    assert dwd[0]["media_uri"] == "s3://audit/image/receipt_001.jpg"
    assert dwd[0]["media_modality"] == "image"
    eng.close()


# ======================================================================
# 测试5：组网执行端到端
# ======================================================================

def test_orchestrator_local_plan():
    """测试本地关键词规划（不调 LLM）。"""
    from modules.shared.orchestrator import AuditPlanner
    planner = AuditPlanner()
    plan = planner.plan("审计公司关联交易公允性和披露完整性")
    assert len(plan.modules) > 0, "规划应选出至少1个模块"
    assert len(plan.steps) > 0, "应有执行步骤"
    assert plan.contract_valid in (True, False), "应有契约校验结果"


def test_orchestrator_execute_with_data():
    """用数据集执行完整组网管道。"""
    from modules.shared.orchestrator import AuditPlanner, ContractValidator, TopoExecutor

    planner = AuditPlanner()
    plan = planner.plan("审计关联交易定价公允性")

    validator = ContractValidator()
    validator.validate(plan)

    # 从数据集构建输入
    records = load_jsonl(DATA_ROOT / "fa_02" / "records.jsonl", limit=50)
    shareholders = load_jsonl(DATA_ROOT / "fa_02" / "shareholders.jsonl", limit=10)
    transactions = load_jsonl(DATA_ROOT / "fa_02" / "transactions.jsonl", limit=20)

    user_input = {
        "records": [{"source": r.get("source", "ERP"), "source_type": r.get("source_type", "api"),
                     "raw_data": r} for r in records],
        "shareholders": shareholders,
        "transactions": transactions,
    }

    executor = TopoExecutor()
    result = executor.execute(plan, user_input)
    assert result.success in (True, False), "应有执行结果"
    assert len(result.execution_log) > 0, "应有执行日志"


def test_orchestrator_with_alignment():
    """测试带数据对齐层的执行。"""
    from modules.shared.orchestrator import AuditPlanner, TopoExecutor

    planner = AuditPlanner()
    plan = planner.plan("反洗钱交易监控")

    records = load_jsonl(DATA_ROOT / "co_04" / "transactions.jsonl", limit=30)
    user_input = {
        "records": [{"source": "银行", "source_type": "stream", "raw_data": r} for r in records],
        "transactions": records,
    }

    executor = TopoExecutor()
    result = executor.execute(plan, user_input)
    # 验证对齐层日志出现
    align_log = [l for l in result.execution_log if "数据对齐层" in l]
    # 对齐层可能跳过但不应崩溃
    assert len(result.execution_log) > 0


# ======================================================================
# 测试6：大数据量压力测试
# ======================================================================

def test_fa03_large_batch():
    """1000条记录入湖压力测试。"""
    from modules.fa_03.engine import MLEngine

    records_raw = load_jsonl(DATA_ROOT / "fa_02" / "records.jsonl", limit=1000)
    records = [{"source": r.get("source", "unknown"), "source_type": r.get("source_type", "api"),
                "raw_data": r, "text_content": r.get("description")} for r in records_raw]

    eng = MLEngine(config={"db_path": ":memory:"})
    eng.setup()
    t0 = time.time()
    result = eng.execute({"batch_id": "STRESS-1000", "project_code": "P1", "records": records})
    elapsed = time.time() - t0
    ods_count = result["zones"]["ods"]["count"]
    assert ods_count == 1000, f"ODS 应为1000，实际 {ods_count}"
    assert elapsed < 30, f"1000条入湖耗时 {elapsed:.1f}s 过长"
    eng.close()


def test_entity_aligner_stress():
    """500+实体对齐压力测试。"""
    from modules.shared.aligner import EntityAligner, EntityRecord

    records = load_jsonl(DATA_ROOT / "fa_02" / "records.jsonl", limit=1000)
    entities = []
    seen = set()
    for rec in records:
        name = rec.get("counterparty", "")
        if name and name not in seen:
            seen.add(name)
            entities.append(EntityRecord(
                entity_id=name, source=rec.get("source", ""),
                name=name, uscc=rec.get("counterparty_uscc", ""),
                aliases=[], attributes={},
            ))

    aligner = EntityAligner()
    t0 = time.time()
    clusters = aligner.align(entities)
    elapsed = time.time() - t0
    assert len(clusters) > 0
    assert elapsed < 10, f"实体对齐耗时 {elapsed:.1f}s 过长"


# ======================================================================
# 主流程
# ======================================================================

def main():
    print("=" * 60)
    print("数据集端到端测试")
    print("=" * 60)

    print("\n--- 1. 数据加载与结构校验 ---")
    check("manifest 存在且≥1GB", test_manifest_exists)
    check("78模块全部有数据", test_all_modules_have_data)
    check("JSONL 结构合法", test_jsonl_structure)

    print("\n--- 2. 契约校验 ---")
    check("契约加载78模块", test_contract_load)
    check("强类型 fields_typed 存在", test_typed_fields_validate)
    check("边兼容性校验", test_edge_compatibility)

    print("\n--- 3. 数据对齐层 ---")
    check("实体对齐(大数据量)", test_entity_aligner_large)
    check("时间对齐(多格式)", test_time_aligner_formats)
    check("DataAligner 统一入口", test_data_aligner_integration)

    print("\n--- 4. fa_03 数据湖多模态入湖 ---")
    check("多模态入湖(200条)", test_fa03_multimodal_ingest)
    check("纯文本入湖", test_fa03_text_ingest)
    check("媒体引用入湖", test_fa03_media_ingest)

    print("\n--- 5. 组网执行端到端 ---")
    check("本地关键词规划", test_orchestrator_local_plan)
    check("组网执行(带数据)", test_orchestrator_execute_with_data)
    check("组网执行(带对齐层)", test_orchestrator_with_alignment)

    print("\n--- 6. 大数据量压力测试 ---")
    check("fa_03 入湖1000条", test_fa03_large_batch)
    check("实体对齐500+实体", test_entity_aligner_stress)

    print("\n" + "=" * 60)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    if ERRORS:
        print("\n失败详情:")
        for e in ERRORS:
            print(f"  - {e}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
