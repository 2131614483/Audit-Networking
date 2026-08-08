"""FA-02 多源数据自动标准化 —— 端到端验证脚本。

用法（项目根目录）：
  python verify_fa_02.py

纯 stdlib，无第三方依赖。用隔离的临时 db 跑通 Pipeline.run()，并演示增量学习。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from modules.fa_02.pipeline import Pipeline  # noqa: E402
from modules.shared.portable_db import PortableDB  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    tag = "OK  " if cond else "FAIL"
    extra = f"  — {detail}" if detail and not cond else ""
    print(f"  [{tag}] {name}{extra}")


def main() -> int:
    mock_input = json.loads(
        (REPO / "modules" / "fa_02" / "tests" / "fixtures" / "mock_input.json")
        .read_text(encoding="utf-8")
    )

    tmp_dir = Path(tempfile.mkdtemp(prefix="fa_02_verify_"))
    db_path = tmp_dir / "fa_02_verify.db"

    # ================================================================
    print("=" * 70)
    print("1) 端到端：Pipeline.run(mock_input) 跑通多源字段标准化")
    print("=" * 70)
    pipe = Pipeline(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(db_path),
    })
    output = pipe.run(mock_input)

    check("Pipeline.run 返回 status=ok", output.get("status") == "ok", str(output.get("status")))
    check("含 standardized_fields 列表", isinstance(output.get("standardized_fields"), list))
    check("含 statistics 统计", isinstance(output.get("statistics"), dict))

    stats = output["statistics"]
    print(f"  统计：{json.dumps(stats, ensure_ascii=False)}")
    check("total == 输入字段数", stats["total"] == len(mock_input["fields"]),
          f"{stats['total']} vs {len(mock_input['fields'])}")
    check("mapped + unmapped == total",
          stats["mapped"] + stats["unmapped"] == stats["total"])
    check("存在未映射字段（Pending Settlement XYZQQ）", stats["unmapped"] >= 1)
    check("存在需复核字段", stats["need_review"] >= 1)

    # 抽样检查映射正确性
    by_raw = {f["raw_name"]: f for f in output["standardized_fields"]}
    check("应收账款 → accounts_receivable (1122)",
          by_raw["应收账款"]["standard_name"] == "accounts_receivable"
          and by_raw["应收账款"]["subject_code"] == "1122")
    check("A/R → accounts_receivable (同义映射)",
          by_raw["A/R"]["standard_name"] == "accounts_receivable")
    check("Accounts Receivable → accounts_receivable (英文映射)",
          by_raw["Accounts Receivable"]["standard_name"] == "accounts_receivable")
    check("营业收入/Revenue/主营业务收入 → revenue (6001)",
          all(by_raw[k]["standard_name"] == "revenue" and by_raw[k]["subject_code"] == "6001"
              for k in ["营业收入", "Revenue", "主营业务收入"]))
    check("PPE → fixed_assets (缩写映射)",
          by_raw["PPE"]["standard_name"] == "fixed_assets")
    check("Pending Settlement XYZQQ → unmapped, tier=manual",
          by_raw["Pending Settlement XYZQQ"]["unmapped"] is True
          and by_raw["Pending Settlement XYZQQ"]["tier"] == "manual")

    # 打印标准化字段汇总表
    print("\n  标准化字段汇总表：")
    print(f"  {'raw_name':<30} {'standard_name':<28} {'conf':<7} {'subj':<7} {'tier':<8} {'review'}")
    print("  " + "-" * 100)
    for f in output["standardized_fields"]:
        print(f"  {f['raw_name']:<30} {f['standard_name']:<28} "
              f"{f['confidence']:<7} {str(f['subject_code']):<7} "
              f"{f['tier']:<8} {f['need_review']}")

    # ================================================================
    print("\n" + "=" * 70)
    print("2) 多策略匹配：精确命中(1.0) + 相似度匹配 + Top-3 候选")
    print("=" * 70)
    # "应收款项" vs "应收账款"：SequenceMatcher 匹配 "应收"+"款"=3，ratio=2*3/(4+4)=0.75
    near_out = pipe.run({"fields": [{"raw_name": "应收款项", "value": 1}]})
    nf = near_out["standardized_fields"][0]
    check("近似名 应收款项 → accounts_receivable",
          nf["standard_name"] == "accounts_receivable")
    check("相似度置信度介于 0.6 和 0.85 之间（review 区间）",
          0.6 < nf["confidence"] < 0.85, f"conf={nf['confidence']}")
    check("tier=review", nf["tier"] == "review", nf["tier"])
    check("Top-3 候选按置信度降序",
          [c["confidence"] for c in nf["top3_candidates"]]
          == sorted([c["confidence"] for c in nf["top3_candidates"]], reverse=True))
    print(f"  近似名 应收款项 Top-3：{json.dumps(nf['top3_candidates'], ensure_ascii=False)}")

    # ================================================================
    print("\n" + "=" * 70)
    print("3) 增量学习：人工确认映射 → 下次 run 生效")
    print("=" * 70)
    out_before = pipe.run({"fields": [{"raw_name": "递延收益", "value": 1}]})
    check("学习前：递延收益 unmapped",
          out_before["standardized_fields"][0]["unmapped"] is True)

    pipe.engine.learn("递延收益", "deferred_income", subject_code="2401")
    out_after = pipe.run({"fields": [{"raw_name": "递延收益", "value": 1}]})
    af = out_after["standardized_fields"][0]
    check("学习后：递延收益 → deferred_income (2401), conf=1.0, tier=auto",
          af["standard_name"] == "deferred_income"
          and af["subject_code"] == "2401"
          and af["confidence"] == 1.0
          and af["tier"] == "auto",
          f"got {af['standard_name']}/{af['subject_code']}/{af['confidence']}/{af['tier']}")

    # 跨实例持久化
    pipe2 = Pipeline(config={
        "threshold": {"confidence": 0.85},
        "db_path": str(db_path),  # 同一个 db
    })
    out_persist = pipe2.run({"fields": [{"raw_name": "递延收益", "value": 1}]})
    pf = out_persist["standardized_fields"][0]
    check("增量学习持久化：新 Pipeline 实例加载时合并递延收益映射",
          pf["standard_name"] == "deferred_income" and pf["subject_code"] == "2401",
          f"got {pf['standard_name']}/{pf['subject_code']}")

    # ================================================================
    print("\n" + "=" * 70)
    print("4) PortableDB 持久化：standardization_results 落盘可查")
    print("=" * 70)
    with PortableDB(db_path) as db:
        tables = set(db.tables())
        check("含 field_mappings 表", "field_mappings" in tables)
        check("含 subject_codes 表", "subject_codes" in tables)
        check("含 increment_learnings 表", "increment_learnings" in tables)
        check("含 standardization_results 表", "standardization_results" in tables)
        fm_count = db.count("field_mappings")
        sc_count = db.count("subject_codes")
        il_count = db.count("increment_learnings")
        sr_count = db.count("standardization_results")
        print(f"  field_mappings: {fm_count} 行（≥20 种子）")
        print(f"  subject_codes:  {sc_count} 行（统一科目表）")
        print(f"  increment_learnings: {il_count} 行（递延收益）")
        print(f"  standardization_results: {sr_count} 行（本次跑批结果）")
        check("field_mappings ≥ 20 条种子", fm_count >= 20, f"实际 {fm_count}")
        check("subject_codes ≥ 15 条", sc_count >= 15, f"实际 {sc_count}")
        check("increment_learnings ≥ 1 条（递延收益）", il_count >= 1)
        check("standardization_results ≥ 1 条", sr_count >= 1)
        # 验证 payload JSON 软类型反序列化
        sample = db.all("standardization_results", limit=1)[0]
        check("payload 字段自动反序列化为 dict",
              isinstance(sample["payload"], dict) and "top3_candidates" in sample["payload"])

    # ================================================================
    print("\n" + "=" * 70)
    print(f"汇总：{len(PASS)} 通过 / {len(FAIL)} 失败")
    print("=" * 70)
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print("全部通过 ✅  FA-02 多源数据自动标准化端到端验证成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
