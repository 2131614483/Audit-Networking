"""逐个跑78个模块的 Pipeline.run()，用数据集验证模块程序本身。

流程：data_adapter.adapt_data_for_module(slug) → Pipeline.run(input) → 检查返回结果
模块代码不动，只做数据侧对齐。
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo.data_adapter import adapt_data_for_module

PASS = 0
FAIL = 0
SKIP = 0
RESULTS: list[dict] = []


def run_module(slug: str) -> dict:
    """跑单个模块的 pipeline.run()。"""
    t0 = time.time()
    result_info = {"slug": slug, "status": "unknown", "error": "", "duration": 0, "input_size": 0, "output_keys": []}
    try:
        # 1. 对齐数据
        input_data = adapt_data_for_module(slug, limit=50)
        if isinstance(input_data, list):
            result_info["input_size"] = len(input_data)
        elif isinstance(input_data, dict):
            result_info["input_size"] = sum(len(v) for v in input_data.values() if isinstance(v, list))

        # 2. 动态导入 Pipeline
        mod = importlib.import_module(f"modules.{slug}.pipeline")
        Pipeline = getattr(mod, "Pipeline")
        pipe = Pipeline()

        # 3. 执行
        output = pipe.run(input_data)
        elapsed = time.time() - t0
        result_info["duration"] = round(elapsed, 2)

        # 4. 检查输出
        if output is None:
            result_info["status"] = "warn"
            result_info["error"] = "输出为 None"
        elif isinstance(output, dict):
            result_info["output_keys"] = list(output.keys())[:10]
            result_info["status"] = "pass"
        elif isinstance(output, list):
            result_info["output_keys"] = [f"list[{len(output)}]"]
            result_info["status"] = "pass"
        elif isinstance(output, str):
            result_info["output_keys"] = [f"str[{len(output)}]"]
            result_info["status"] = "pass"
        else:
            result_info["status"] = "pass"
            result_info["output_keys"] = [str(type(output).__name__)]

    except Exception as e:
        elapsed = time.time() - t0
        result_info["duration"] = round(elapsed, 2)
        result_info["status"] = "fail"
        result_info["error"] = f"{type(e).__name__}: {e}"
        # 保留前3行 traceback
        tb = traceback.format_exc().strip().split("\n")
        result_info["traceback"] = "\n".join(tb[-4:])
    return result_info


# 全部78个模块 slug
ALL_SLUGS = [
    "fa_02","fa_03","fa_04","fa_05","fa_06","fa_07","fa_08","fa_09","fa_10","fa_11","fa_12",
    "co_01","co_02","co_03","co_04","co_05","co_06","co_07","co_08","co_09",
    "ip_01","ip_02","ip_03","ip_04","ip_05","ip_06",
    "cm_01","cm_02","cm_03","cm_04","cm_05",
    "fo_01","fo_02","fo_03","fo_04","fo_05","fo_06",
    "it_01","it_02","it_03","it_04","it_05",
    "ta_01","ta_02","ta_03","ta_04","ta_05","ta_06",
    "sc_01","sc_02","sc_03","sc_04","sc_05",
    "es_01","es_02","es_03","es_04","es_05","es_06",
    "fi_01","fi_02","fi_03","fi_04","fi_05",
    "ia_01","ia_02","ia_03","ia_04","ia_05","ia_06","ia_07","ia_08",
    "cb_01","cb_02","cb_03","cb_04","cb_05","cb_06",
]


def main():
    global PASS, FAIL, SKIP

    print("=" * 70)
    print("全模块 Pipeline.run() 数据集测试（78模块）")
    print("原则：模块代码不动，只做数据→接口对齐")
    print("=" * 70)

    for i, slug in enumerate(ALL_SLUGS, 1):
        info = run_module(slug)
        RESULTS.append(info)

        status_icon = {"pass": "✓", "fail": "✗", "warn": "⚠", "skip": "⊘"}.get(info["status"], "?")
        if info["status"] == "pass":
            PASS += 1
        elif info["status"] == "fail":
            FAIL += 1
        else:
            SKIP += 1

        err_str = f" | {info['error']}" if info["error"] else ""
        out_str = f" → {info['output_keys']}" if info["output_keys"] else ""
        print(f"  [{i:2d}/78] {status_icon} {slug:6s} ({info['duration']:5.1f}s) in={info['input_size']:4d}{out_str}{err_str}")

    # 汇总
    print("\n" + "=" * 70)
    print(f"结果: {PASS} 通过, {FAIL} 失败, {SKIP} 警告 / 共78模块")
    print(f"总耗时: {sum(r['duration'] for r in RESULTS):.1f}s")

    if FAIL > 0:
        print("\n--- 失败模块详情 ---")
        for r in RESULTS:
            if r["status"] == "fail":
                print(f"\n✗ {r['slug']}: {r['error']}")
                if "traceback" in r:
                    print(r["traceback"])

    # 保存结果到 JSON
    report_path = Path(__file__).parent / "module_test_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告: {report_path}")
    print("=" * 70)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
