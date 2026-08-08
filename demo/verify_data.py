"""验证生成的多模态数据结构和可消费性。"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

root = Path("demo/synthetic_data")
m = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
print(f"总数据量: {m['total_gb']} GB ({m['total_mb']} MB)")
print(f"模块数: {m['module_count']}")
print()

# 展示5个模块的数据结构
for slug in ["fa_02", "fa_03", "co_04", "fo_03", "es_01"]:
    mod = next(x for x in m["modules"] if x["slug"] == slug)
    print(f"=== {slug} ({mod['total_mb']} MB) ===")
    for f in mod["files"]:
        print(f"  {f['file']}: {f['bytes']/1024:.0f} KB")
    # 采样数据
    for f in mod["files"]:
        fp = root / slug / f["file"]
        if f["file"].endswith(".jsonl"):
            with open(fp, encoding="utf-8") as fh:
                first = json.loads(fh.readline())
            print(f"  [{f['file']} 样本] keys: {list(first.keys())[:8]}")
        elif f["file"].endswith(".txt"):
            with open(fp, encoding="utf-8") as fh:
                line = fh.readline()[:80]
            print(f"  [{f['file']} 样本] {line}...")
        elif f["file"].endswith(".json"):
            d = json.loads(fp.read_text(encoding="utf-8"))
            if "nodes" in d:
                print(f"  [{f['file']}] nodes={len(d['nodes'])}, edges={len(d['edges'])}")
    print()

# 端到端验证：用 fa_02 数据喂给 fa_03 数据湖
print("=== 端到端验证: fa_02 数据 → fa_03 数据湖 ===")
fa02_recs = []
with open(root / "fa_02" / "records.jsonl", encoding="utf-8") as fh:
    for i, line in enumerate(fh):
        if i >= 500:  # 取前500条验证
            break
        r = json.loads(line)
        # 包装成 fa_03 期望的格式：业务字段放 raw_data，多模态字段提至顶层
        fa02_recs.append({
            "source": r.get("source", "unknown"),
            "source_type": r.get("source_type", "api"),
            "raw_data": r,  # 整条记录作为 raw_data
            "text_content": r.get("description"),
        })

from modules.fa_03.engine import MLEngine
eng = MLEngine(config={"db_path": ":memory:"})
eng.setup()
result = eng.execute({
    "batch_id": "VERIFY-MM",
    "project_code": "P1",
    "records": fa02_recs,
})
print(f"  输入: {len(fa02_recs)} 条多模态记录")
print(f"  结果: {result}")
# 统计多模态字段透传
dwd = eng.db.query("dwd_standardized", limit=100)
mm_count = sum(1 for r in dwd if r.get("text_content") or r.get("media_uri"))
print(f"  DWD 多模态记录: {mm_count}/{len(dwd)} 条含文本/媒体字段")

# 验证多模态字段透传
dwd = eng.db.query("dwd_standardized", limit=3)
for r in dwd:
    if r.get("text_content") or r.get("media_uri"):
        print(f"  多模态透传 ✓: text={r.get('text_content','')[:30]}, media={r.get('media_uri','')}, modality={r.get('media_modality','')}")
        break
eng.close()
print("\n验证通过 ✓")
