"""端到端审计报告生成脚本。

流程：data_adapter 准备适配数据 → LLMPlanner 规划 → ContractValidator 校验
     → TopoExecutor 拓扑执行 → ReportGenerator 生成报告
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo.data_adapter import adapt_data_for_module
from modules.shared.orchestrator import run_audit_with_llm

REQUIREMENT = "对拟上市企业进行IPO财务规范性审计，审查关联方识别、历史沿革、财务规范性和披露完整性"

# 为所有可能被选中的模块准备适配数据（以 slug 为 key）
IPO_SLUGS = [
    "fa_02", "fa_03", "fa_06", "fa_07", "fa_08", "fa_09",
    "fa_10", "fa_11", "fa_12", "co_01", "ip_01", "ip_03", "ip_04",
]


def main():
    user_input: dict = {}
    for slug in IPO_SLUGS:
        try:
            adapted = adapt_data_for_module(slug, limit=50)
            if isinstance(adapted, dict):
                user_input[slug] = adapted
        except Exception as e:
            print(f"  跳过 {slug}: {e}")

    print(f"已准备 {len(user_input)} 个模块的适配数据: {list(user_input.keys())}")
    print()

    t0 = time.time()
    result = run_audit_with_llm(REQUIREMENT, user_input)
    elapsed = time.time() - t0

    # 打印规划
    print("=" * 70)
    print("【LLM 规划推理】")
    print(result.plan.reasoning)
    print()
    print(f"选中模块: {result.plan.modules}")
    print(f"数据流边: {result.plan.edges}")
    contract_str = "通过" if result.plan.contract_valid else "有问题"
    print(f"契约校验: {contract_str} ({len(result.plan.contract_issues)} issues)")
    print()

    # 打印执行日志
    print("=" * 70)
    print("【执行日志】")
    for line in result.execution_log:
        print(f"  {line}")
    print()

    # 打印报告摘要
    print("=" * 70)
    print("【审计报告摘要】")
    report = result.final_report
    ps = report["plan_summary"]
    print(f"模块数: {ps['modules']} | 成功: {ps['success']} | 失败: {ps['failed']}")
    print(f"总耗时: {result.total_duration}s")
    print()

    findings = report.get("findings", [])
    print(f"审计发现: {len(findings)} 条")
    for f in findings[:15]:
        print(f"  [{f['severity']}] {f['source']}: {f['title']}")
        detail = f["detail"][:100]
        print(f"       {detail}")
    print()

    print("【模块结果】")
    for slug, mr in report.get("module_results", {}).items():
        status_icon = "OK" if mr["status"] == "done" else "FAIL"
        mock_tag = " (mock)" if mr.get("is_mock") else ""
        print(f"  {status_icon} {slug:6s} {mr['name']:22s} ({mr['duration']}s){mock_tag}")
        if mr.get("error"):
            print(f"         error: {mr['error'][:100]}")
    print()
    print(f"总耗时: {elapsed:.1f}s")

    # 保存完整报告到 JSON
    report_path = Path(__file__).parent / "audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n完整报告已保存: {report_path}")

    # 保存可视化数据（含 DAG 结构 + 模块输出详情）
    viz_data = {
        "requirement": REQUIREMENT,
        "plan": {
            "modules": [
                {
                    "slug": s.slug, "name": s.name, "family": s.family,
                    "status": s.status, "duration": s.duration,
                    "error": s.error or None,
                    "inputs": s.inputs, "outputs": s.outputs,
                }
                for s in result.plan.steps
            ],
            "edges": result.plan.edges,
            "reasoning": result.plan.reasoning,
        },
        "findings": report.get("findings", []),
        "module_results": report.get("module_results", {}),
        "execution_log": result.execution_log,
        "total_duration": result.total_duration,
    }
    viz_path = Path(__file__).parent / "audit_data.json"
    with open(viz_path, "w", encoding="utf-8") as f:
        json.dump(viz_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"可视化数据已保存: {viz_path}")


if __name__ == "__main__":
    main()
