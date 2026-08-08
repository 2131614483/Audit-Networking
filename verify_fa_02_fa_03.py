"""FA-02 + FA-03 端到端验证（纯 stdlib，不依赖 pytest）。

用法（仓库根目录）：
    python verify_fa_02_fa_03.py

验证内容：
  FA-02 多源数据标准化：多策略匹配 / 置信度 / Top-3 / 科目标准化 /
                         阈值分级 / 增量学习 / Pipeline 端到端 / PortableDB 持久化
  FA-03 审计数据湖：三区分层(ODS/DWD/ADS) / 去重 / 血缘 / 质量评分 /
                     Pipeline 端到端 / jsonl 导出
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    tag = "OK  " if cond else "FAIL"
    extra = f"  — {detail}" if detail and not cond else ""
    print(f"  [{tag}] {name}{extra}")


# ====================================================================
# FA-02 多源数据自动标准化
# ====================================================================
print("=" * 70)
print("FA-02 多源数据自动标准化 —— 端到端验证")
print("=" * 70)

from modules.fa_02.engine import MLEngine, _clean
from modules.fa_02.pipeline import Pipeline as FA02Pipeline
from modules.shared.portable_db import PortableDB

# 隔离测试 db
_fa02_db = tempfile.mktemp(suffix="_fa02.db")

# ---------- 1. 字段清洗 ----------
check("FA-02 清洗: A/R -> ar", _clean("  A/R !! ") == "ar")
check("FA-02 清洗: Accounts Receivable -> accounts receivable",
      _clean("Accounts Receivable") == "accounts receivable")
check("FA-02 清洗: 中文保留", _clean("应收账款") == "应收账款")

# ---------- 2. 精确同义词匹配 ----------
eng = MLEngine(config={"threshold": {"confidence": 0.85}, "db_path": _fa02_db})
eng.setup()
result = eng.execute({
    "source": "ERP-A",
    "fields": [
        {"raw_name": "应收账款", "value": 100},
        {"raw_name": "A/R", "value": 200},
        {"raw_name": "Accounts Receivable", "value": 300},
    ],
})
for f in result["fields"]:
    check(f"FA-02 精确匹配 {f['raw_name']}->accounts_receivable (conf=1.0, code=1122)",
          f["best_match"] == "accounts_receivable"
          and f["confidence"] == 1.0
          and f["subject_code"] == "1122"
          and f["unmapped"] is False)

# ---------- 3. 多源同义字段映射到同一标准字段 ----------
result = eng.execute({
    "fields": [
        {"raw_name": "营业收入", "value": 1},
        {"raw_name": "Revenue", "value": 1},
        {"raw_name": "主营业务收入", "value": 1},
        {"raw_name": "Sales Revenue", "value": 1},
    ],
})
stds = {f["raw_name"]: f["best_match"] for f in result["fields"]}
codes = {f["raw_name"]: f["subject_code"] for f in result["fields"]}
check("FA-02 多源同义->revenue", all(v == "revenue" for v in stds.values()))
check("FA-02 多源科目代码=6001", all(v == "6001" for v in codes.values()))

# ---------- 4. 字符相似度匹配（review 区间） ----------
result = eng.execute({"fields": [{"raw_name": "应收款项", "value": 100}]})
f = result["fields"][0]
check("FA-02 相似度匹配 应收款项->accounts_receivable",
      f["best_match"] == "accounts_receivable")
check("FA-02 相似度 0.6<0.75<0.85 (review)",
      0.6 < f["confidence"] < 0.85,
      f"confidence={f['confidence']}")
check("FA-02 相似度 need_review=True", f["need_review"] is True)

# ---------- 5. Top-3 候选降序 ----------
result = eng.execute({"fields": [{"raw_name": "应收账款", "value": 1}]})
f = result["fields"][0]
check("FA-02 Top-3 非空且≤3", 1 <= len(f["top3_candidates"]) <= 3)
check("FA-02 Top-3 首个=accounts_receivable",
      f["top3_candidates"][0]["standard_name"] == "accounts_receivable")
confs = [c["confidence"] for c in f["top3_candidates"]]
check("FA-02 Top-3 降序", confs == sorted(confs, reverse=True))

# ---------- 6. 未映射字段 ----------
result = eng.execute({"fields": [{"raw_name": "Pending Settlement XYZQQ", "value": 1}]})
f = result["fields"][0]
check("FA-02 未映射 best_match=None", f["best_match"] is None)
check("FA-02 未映射 unmapped=True", f["unmapped"] is True)
check("FA-02 未映射 confidence=0.0", f["confidence"] == 0.0)
check("FA-02 未映射 need_review=True", f["need_review"] is True)

# ---------- 7. 科目代码标准化 ----------
result = eng.execute({
    "fields": [
        {"raw_name": "应收账款", "value": 1},
        {"raw_name": "应付账款", "value": 1},
        {"raw_name": "固定资产", "value": 1},
        {"raw_name": "营业收入", "value": 1},
        {"raw_name": "存货", "value": 1},
    ],
})
codes = {f["raw_name"]: f["subject_code"] for f in result["fields"]}
check("FA-02 科目标准化 应收=1122/应付=2202/固定=1601/营收=6001/存货=1241",
      codes["应收账款"] == "1122"
      and codes["应付账款"] == "2202"
      and codes["固定资产"] == "1601"
      and codes["营业收入"] == "6001"
      and codes["存货"] == "1241")

# ---------- 8. 科目元信息 ----------
result = eng.execute({"fields": [{"raw_name": "固定资产", "value": 1}]})
f = result["fields"][0]
check("FA-02 科目元信息 subject_name=固定资产",
      f["subject_meta"].get("subject_name") == "固定资产")
check("FA-02 科目元信息 category=asset_noncurrent",
      f["subject_meta"].get("category") == "asset_noncurrent")

# ---------- 9. 增量学习：即时生效 ----------
# 注意：测试词必须与所有已知 raw 名相似度 < _MIN_SIMILARITY(0.4)，
# 否则会被相似度策略误匹配。用纯英文无语义词避免干扰。
r1 = eng.execute({"fields": [{"raw_name": "zzz_unmapped_qqq", "value": 1}]})
check("FA-02 增量学习前 未映射", r1["fields"][0]["best_match"] is None,
      f"best_match={r1['fields'][0]['best_match']}")
eng.learn("zzz_unmapped_qqq", "misc_prepayments", subject_code="9999")
r2 = eng.execute({"fields": [{"raw_name": "zzz_unmapped_qqq", "value": 1}]})
f = r2["fields"][0]
check("FA-02 增量学习后 精确命中 misc_prepayments",
      f["best_match"] == "misc_prepayments"
      and f["confidence"] == 1.0
      and f["subject_code"] == "9999")

# ---------- 10. 增量学习：跨实例持久化 ----------
_persist_db = tempfile.mktemp(suffix="_fa02_persist.db")
eng1 = MLEngine(config={"threshold": {"confidence": 0.85}, "db_path": _persist_db})
eng1.setup()
eng1.learn("研发支出", "rd_expenses", subject_code="6602")
eng1.close()
eng2 = MLEngine(config={"threshold": {"confidence": 0.85}, "db_path": _persist_db})
eng2.setup()
r = eng2.execute({"fields": [{"raw_name": "研发支出", "value": 1}]})
f = r["fields"][0]
check("FA-02 增量学习持久化 跨实例命中",
      f["best_match"] == "rd_expenses"
      and f["confidence"] == 1.0
      and f["subject_code"] == "6602")

# ---------- 11. 增量学习：覆盖 fixtures（最高优先级） ----------
eng.learn("应收账款", "other_receivables", subject_code="1221")
r = eng.execute({"fields": [{"raw_name": "应收账款", "value": 1}]})
f = r["fields"][0]
check("FA-02 增量学习覆盖fixtures ->other_receivables/1221",
      f["best_match"] == "other_receivables" and f["subject_code"] == "1221")

# ---------- 12. Pipeline 端到端 ----------
_fa02_pipe_db = tempfile.mktemp(suffix="_fa02_pipe.db")
pipe = FA02Pipeline(config={
    "threshold": {"confidence": 0.85},
    "db_path": _fa02_pipe_db,
})
mock_input = json.loads(
    (REPO / "modules" / "fa_02" / "tests" / "fixtures" / "mock_input.json")
    .read_text(encoding="utf-8")
)
output = pipe.run(mock_input)
check("FA-02 Pipeline status=ok", output["status"] == "ok")
check("FA-02 Pipeline 有 standardized_fields", "standardized_fields" in output)
check("FA-02 Pipeline 有 statistics", "statistics" in output)
stats = output["statistics"]
check("FA-02 Pipeline total=20", stats["total"] == 20, f"total={stats['total']}")
check("FA-02 Pipeline mapped+unmapped=total",
      stats["mapped"] + stats["unmapped"] == stats["total"])
check("FA-02 Pipeline unmapped>=1", stats["unmapped"] >= 1)
check("FA-02 Pipeline need_review>=1", stats["need_review"] >= 1)

# ---------- 13. Pipeline 阈值分级 ----------
_fa02_tier_db = tempfile.mktemp(suffix="_fa02_tier.db")
pipe2 = FA02Pipeline(config={
    "threshold": {"confidence": 0.85},
    "db_path": _fa02_tier_db,
})
output = pipe2.run({
    "fields": [
        {"raw_name": "应收账款", "value": 1},                    # auto
        {"raw_name": "应收款项", "value": 1},                    # review
        {"raw_name": "Pending Settlement XYZQQ", "value": 1},   # manual
    ],
})
tiers = {f["raw_name"]: f["tier"] for f in output["standardized_fields"]}
check("FA-02 Pipeline tier: 应收账款=auto", tiers["应收账款"] == "auto")
check("FA-02 Pipeline tier: 应收款项=review", tiers["应收款项"] == "review")
check("FA-02 Pipeline tier: 未映射=manual",
      tiers["Pending Settlement XYZQQ"] == "manual")

# ---------- 14. Pipeline PortableDB 持久化 ----------
with PortableDB(_fa02_pipe_db) as db:
    rows = db.all("standardization_results")
check("FA-02 PortableDB 持久化结果数=20", len(rows) == 20, f"实际={len(rows)}")
check("FA-02 PortableDB payload自动反序列化为dict",
      all(isinstance(r["payload"], dict) and "top3_candidates" in r["payload"]
          for r in rows))

# ---------- 15. PortableDB 种子表 ----------
with PortableDB(_fa02_pipe_db) as db:
    tables = set(db.tables())
    fm_count = db.count("field_mappings")
    sc_count = db.count("subject_codes")
check("FA-02 PortableDB 含4张表",
      {"field_mappings", "subject_codes", "increment_learnings",
       "standardization_results"}.issubset(tables))
check(f"FA-02 种子 field_mappings>=20 (实际{fm_count})", fm_count >= 20)
check(f"FA-02 种子 subject_codes>=15 (实际{sc_count})", sc_count >= 15)

# 清理 FA-02 engine 连接
eng.close()
eng2.close()


# ====================================================================
# FA-03 审计数据湖建设
# ====================================================================
print("\n" + "=" * 70)
print("FA-03 审计数据湖建设 —— 端到端验证")
print("=" * 70)

from modules.fa_03.engine import MLEngine as FA03Engine
from modules.fa_03.pipeline import Pipeline as FA03Pipeline

_fa03_db = tempfile.mktemp(suffix="_fa03.db")
fa03_input = json.loads(
    (REPO / "modules" / "fa_03" / "tests" / "fixtures" / "mock_input.json")
    .read_text(encoding="utf-8")
)

eng3 = FA03Engine(config={
    "db_path": _fa03_db,
    "threshold": {"confidence": 0.85},
})
eng3.setup()

# ---------- 1. 三区表 + 元数据表创建 ----------
tables = eng3.db.tables()
for t in ("ods_raw", "dwd_standardized", "ads_ready", "lineage", "quality_metrics"):
    check(f"FA-03 建表 {t}", t in tables)
check("FA-03 model 含 account_master", "account_master" in eng3.model)

# ---------- 2. 幂等加载 ----------
db_ref = eng3.db
eng3._load_model()
check("FA-03 _load_model 幂等", db_ref is eng3.db)

# ---------- 3. ODS 写入 ----------
prepared = eng3._preprocess(fa03_input)
check(f"FA-03 ODS 写入 {prepared['ingested']} 条", prepared["ingested"] == 57)
check(f"FA-03 ODS count={eng3.db.count('ods_raw')}",
      eng3.db.count("ods_raw") == 57)
check("FA-03 sources={ERP-SAP,用友NC,工商银行}",
      set(prepared["sources"]) == {"ERP-SAP", "用友NC", "工商银行"})

# 清空 ODS（#3 单独测了 _preprocess；#4 起 execute 内部会重新 _preprocess 写 ODS）
eng3.db._conn.execute("DELETE FROM ods_raw")
eng3.db._conn.commit()

# ---------- 4. 三区分层提升 + 去重 ----------
out = eng3.execute(fa03_input)
check(f"FA-03 ODS=57", out["zones"]["ods"]["count"] == 57)
check(f"FA-03 DWD=54 (去重3)", out["zones"]["dwd"]["count"] == 54,
      f"实际={out['zones']['dwd']['count']}")
check(f"FA-03 dedup_removed=3", out["dedup_removed"] == 3,
      f"实际={out['dedup_removed']}")
check("FA-03 ADS>0 且≤54",
      0 < out["zones"]["ads"]["count"] <= 54)
check("FA-03 ADS theme=account_monthly_summary",
      out["zones"]["ads"]["theme"] == "account_monthly_summary")

# ---------- 5. 血缘 ----------
summary = out["lineage"]["summary"]
check("FA-03 血缘 ods->dwd=57",
      summary.get("ods_raw->dwd_standardized") == 57,
      f"实际={summary.get('ods_raw->dwd_standardized')}")
check("FA-03 血缘 dwd->ads=54",
      summary.get("dwd_standardized->ads_ready") == 54,
      f"实际={summary.get('dwd_standardized->ads_ready')}")
graph = out["lineage"]["graph"]
check("FA-03 血缘图 ods_raw->dwd_standardized",
      graph.get("ods_raw") == ["dwd_standardized"])
check("FA-03 血缘图 dwd_standardized->ads_ready",
      graph.get("dwd_standardized") == ["ads_ready"])

# ---------- 6. 质量评分 ----------
quality = out["quality"]
for zone in ("ods", "dwd", "ads"):
    m = quality[zone]
    ok = all(0.0 <= m[k] <= 1.0
             for k in ("completeness", "uniqueness", "consistency", "overall_score"))
    check(f"FA-03 质量 {zone} 评分在[0,1]", ok)
check("FA-03 DWD uniqueness=1.0 (已去重)",
      quality["dwd"]["uniqueness"] == 1.0)
check("FA-03 ADS overall_score=1.0 (聚合宽表)",
      quality["ads"]["overall_score"] == 1.0)

# ---------- 7. 标准化字段效果 ----------
dwd_rows = eng3.db.all("dwd_standardized")
ar_rows = [r for r in dwd_rows if r["account_code"] == "1122"]
check("FA-03 DWD 1122科目名=应收账款",
      all(r["account_name"] == "应收账款" for r in ar_rows))
check("FA-03 DWD amount全为float",
      all(isinstance(r["amount"], float) for r in dwd_rows))
periods = {r["period"] for r in dwd_rows if r["period"]}
check("FA-03 DWD period标准化为YYYY-MM",
      all(p.startswith("2026-") for p in periods))

# ---------- 8. 脏数据标记 ----------
all_flags = []
for r in dwd_rows:
    all_flags.extend(r["quality_flags"] or [])
for flag in ("null_amount_defaulted", "null_account_code",
             "account_not_in_master", "amount_type_converted",
             "null_company_code"):
    check(f"FA-03 脏数据标记 {flag}", flag in all_flags)

# ---------- 9. 金额类型转换 ----------
by_key = {
    (r["source"], r["source_type"], r["company_code"],
     r["account_code"], r["period"], r["voucher_no"]): r
    for r in dwd_rows
}
r = by_key.get(("用友NC", "voucher", "C002", "2202", "2026-01", "V003"))
check('FA-03 金额转换 "5,200.00"->5200.0',
      r is not None and r["amount"] == 5200.0, f"r={r}")
r = by_key.get(("ERP-SAP", "voucher", "C001", "1122", "2026-01", "V001"))
check('FA-03 金额转换 "15000.50"->15000.5',
      r is not None and r["amount"] == 15000.5, f"r={r}")
r = by_key.get(("ERP-SAP", "voucher", "C001", "6001", "2026-01", "V002"))
check("FA-03 金额转换 9800000(int)->9800000.0",
      r is not None and r["amount"] == 9800000.0, f"r={r}")

# ---------- 10. ADS 聚合求和校验 ----------
ads_rows = eng3.db.all("ads_ready")
agg_ok = True
for a in ads_rows:
    dwd_ids = a["dwd_ids"]
    if not dwd_ids:
        continue
    placeholders = ",".join("?" * len(dwd_ids))
    dwd_sub = eng3.db.query(
        "dwd_standardized",
        where=f"id IN ({placeholders})", params=dwd_ids,
    )
    expected = round(sum(r["amount"] for r in dwd_sub), 2)
    if a["amount"] != expected:
        agg_ok = False
        break
check("FA-03 ADS聚合=DWD求和", agg_ok)

# ---------- 11. 复用率 ----------
# 复用率 = ADS中来源≥2的记录占比；单模块测试偏低属正常（跨模块复用才高）
check("FA-03 复用率在[0,1]",
      0.0 <= out["reuse_rate"] <= 1.0)
check(f"FA-03 复用率>0.3 (实际{out['reuse_rate']})",
      out["reuse_rate"] > 0.3,
      f"实际={out['reuse_rate']}")

# ---------- 12. execute() 模板方法未改 ----------
import inspect
from modules.shared.base_engine import AbstractEngine
src = inspect.getsource(AbstractEngine.execute)
check("FA-03 execute模板方法含_preprocess/_infer/_postprocess",
      "_preprocess" in src and "_infer" in src and "_postprocess" in src)

eng3.close()

# ---------- 13. Pipeline 端到端 ----------
_fa03_pipe_db = tempfile.mktemp(suffix="_fa03_pipe.db")
pipe3 = FA03Pipeline(config={
    "db_path": _fa03_pipe_db,
    "threshold": {"confidence": 0.85},
})
out3 = pipe3.run(fa03_input)
check("FA-03 Pipeline module=FA-03", out3["module"] == "FA-03")
check("FA-03 Pipeline status=ok", out3["status"] == "ok")
z = out3["三区统计"]
check(f"FA-03 Pipeline ODS=57", z["ods"]["count"] == 57)
check(f"FA-03 Pipeline DWD=54", z["dwd"]["count"] == 54)
check("FA-03 Pipeline ADS>0", z["ads"]["count"] > 0)
check("FA-03 Pipeline sources正确",
      set(z["ods"]["sources"]) == {"ERP-SAP", "用友NC", "工商银行"})

# ---------- 14. Pipeline 阈值与治理 ----------
check("FA-03 Pipeline 阈值=0.85", out3["阈值"] == {"confidence": 0.85})
check("FA-03 Pipeline ADS grade=优质",
      out3["质量分布"]["ads"]["grade"] == "优质")
check("FA-03 Pipeline ADS meets_threshold=True",
      out3["质量分布"]["ads"]["meets_threshold"] is True)
actions = out3["治理动作"]
check("FA-03 Pipeline 含archive_expired治理动作",
      any(a["action"] == "archive_expired" for a in actions))

# ---------- 15. Pipeline 血缘摘要 ----------
ls = out3["血缘摘要"]
check("FA-03 Pipeline 血缘 ods->dwd=57",
      ls["summary"].get("ods_raw->dwd_standardized") == 57)
check("FA-03 Pipeline 血缘 dwd->ads=54",
      ls["summary"].get("dwd_standardized->ads_ready") == 54)
check("FA-03 Pipeline 血缘 edge_count=111",
      ls["edge_count"] == 57 + 54, f"实际={ls['edge_count']}")

# ---------- 16. Pipeline jsonl 导出 ----------
data_dir = REPO / "modules" / "fa_03" / "data"
ads_jsonl = data_dir / "ads_ready.jsonl"
dwd_jsonl = data_dir / "dwd_standardized.jsonl"
check("FA-03 jsonl ads_ready.jsonl 存在", ads_jsonl.exists())
check("FA-03 jsonl dwd_standardized.jsonl 存在", dwd_jsonl.exists())
if ads_jsonl.exists():
    with open(ads_jsonl, encoding="utf-8") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    check("FA-03 jsonl ADS行数与count一致",
          len(lines) == z["ads"]["count"], f"jsonl={len(lines)}, count={z['ads']['count']}")
    if lines:
        first = json.loads(lines[0])
        check("FA-03 jsonl 首行theme正确",
              first.get("theme") == "account_monthly_summary")

pipe3.close()

# ====================================================================
# 汇总
# ====================================================================
print("\n" + "=" * 70)
total = len(PASS) + len(FAIL)
print(f"验证汇总：{len(PASS)}/{total} 通过，{len(FAIL)} 失败")
print("=" * 70)
if FAIL:
    print("\n失败项：")
    for name in FAIL:
        print(f"  [FAIL] {name}")
    sys.exit(1)
else:
    print("\n全部验证通过！FA-02 + FA-03 四层填充完成，端到端跑通。")
    sys.exit(0)
