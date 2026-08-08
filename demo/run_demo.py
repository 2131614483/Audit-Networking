"""智能审计编排 demo 运行入口。

用法：
  python -m demo.run_demo                          # 交互式选择案例
  python -m demo.run_demo --case related_party     # 指定案例
  python -m demo.run_demo --requirement "审计关联交易定价公允性"  # 自定义需求
"""
from __future__ import annotations

import argparse
import json
import sys

from demo.audit_cases import ALL_CASES, list_cases
from modules.shared.orchestrator import run_audit


# ======================================================================
# 格式化输出工具
# ======================================================================

# 状态符号
SYM_OK = "✓"
SYM_FAIL = "✗"
SYM_SKIP = "⊙"

# 分隔线
LINE = "─" * 70
DOUBLE_LINE = "═" * 70


def _print_header(title: str) -> None:
    """打印标题。"""
    print(f"\n{DOUBLE_LINE}")
    print(f"  {title}")
    print(DOUBLE_LINE)


def _print_planning(plan) -> None:
    """打印 AI 规划过程。"""
    _print_header("第一步：AI 规划审计方案")

    # 推理过程
    print(f"\n{plan.reasoning}")

    # 模块列表
    print(f"\n{LINE}")
    print(f"  选中模块（{len(plan.modules)} 个）：")
    for i, slug in enumerate(plan.modules, 1):
        step = next((s for s in plan.steps if s.slug == slug), None)
        if step:
            family_tag = f"[{step.family}]"
            inputs_tag = f" ← {','.join(step.inputs)}" if step.inputs else " [入口]"
            print(f"    {i}. {slug:8s} {step.name:20s} {family_tag:10s}{inputs_tag}")

    # 契约校验
    print(f"\n{LINE}")
    if plan.contract_valid:
        print(f"  接口契约校验：{SYM_OK} 通过（{len(plan.edges)} 条数据流边全部一致）")
    else:
        print(f"  接口契约校验：{SYM_FAIL} 发现 {len(plan.contract_issues)} 个问题：")
        for issue in plan.contract_issues:
            print(f"    ⚠ {issue}")


def _print_execution(result) -> None:
    """打印执行日志。"""
    _print_header("第二步：拓扑执行审计流程")

    print()
    for line in result.execution_log:
        # 给符号着色（通过替换增强可读性）
        if "✓ 完成" in line:
            print(f"  {SYM_OK} {line}")
        elif "✗ 失败" in line:
            print(f"  {SYM_FAIL} {line}")
        elif "=== " in line:
            print(f"\n  {line}")
        else:
            print(f"  {line}")


def _print_report(result) -> None:
    """打印最终审计报告。"""
    _print_header("第三步：审计报告")

    report = result.final_report
    summary = report["plan_summary"]

    # 执行摘要
    print(f"\n  审计需求：{report['audit_requirement']}")
    print(f"  模块总数：{summary['modules']}  |  数据流边：{summary['edges']}")
    print(f"  成功：{summary['success']}  |  失败：{summary['failed']}  |  "
          f"契约一致：{'是' if summary['contract_valid'] else '否'}")
    print(f"  总耗时：{result.total_duration}s")

    # 模块执行结果
    print(f"\n{LINE}")
    print("  模块执行结果：")
    for slug, mr in report["module_results"].items():
        sym = SYM_OK if mr["status"] == "done" else SYM_FAIL
        mock_tag = " [模拟数据]" if mr["is_mock"] else ""
        error_tag = f" [{mr['error']}]" if mr["error"] else ""
        print(f"    {sym} {slug:8s} {mr['name']:20s} "
              f"({mr['duration']}s){mock_tag}{error_tag}")
        # 统计信息
        stats = mr.get("summary", {}).get("stats", {})
        if stats:
            stats_str = "  ".join(f"{k}={v}" for k, v in stats.items())
            print(f"           └─ {stats_str}")

    # 审计发现
    findings = report.get("findings", [])
    print(f"\n{LINE}")
    print(f"  审计发现（{len(findings)} 项）：")
    if not findings:
        print("    （未发现异常）")
    else:
        for i, f in enumerate(findings, 1):
            sev_sym = {"高": "🔴", "中": "🟡", "低": "🟢"}.get(f["severity"], "⚪")
            print(f"    {i}. {sev_sym} [{f['severity']}] {f['title']}")
            print(f"       来源：{f['source']} | 详情：{f['detail']}")

    print(f"\n{DOUBLE_LINE}")


def _print_case_menu() -> None:
    """打印案例选择菜单。"""
    _print_header("智能审计编排系统 Demo")
    print("\n  请选择审计案例：\n")
    for idx, (key, title) in enumerate(list_cases(), 1):
        case = ALL_CASES[key]
        req = case["requirement"]
        mods = ", ".join(case["expected_modules"])
        print(f"    {idx}. [{key}] {title}")
        print(f"       需求：{req}")
        print(f"       预期模块：{mods}")
        print()
    print(f"    0. 自定义审计需求")
    print()


# ======================================================================
# 运行逻辑
# ======================================================================


def run_case(case_key: str) -> None:
    """运行指定案例。"""
    case = ALL_CASES.get(case_key)
    if case is None:
        print(f"错误：未找到案例 '{case_key}'，可用案例：{list(ALL_CASES.keys())}")
        sys.exit(1)

    _print_header(f"运行案例：{case['title']}")
    print(f"  审计需求：{case['requirement']}")
    print(f"  预期模块：{', '.join(case['expected_modules'])}")

    result = run_audit(case["requirement"], case["input_data"])

    _print_planning(result.plan)
    _print_execution(result)
    _print_report(result)


def run_custom(requirement: str, input_data: dict | None = None) -> None:
    """运行自定义审计需求。"""
    _print_header("自定义审计需求")
    print(f"  需求：{requirement}")

    result = run_audit(requirement, input_data or {})

    _print_planning(result.plan)
    _print_execution(result)
    _print_report(result)


def interactive_select() -> None:
    """交互式选择案例。"""
    _print_case_menu()
    try:
        choice = input("  请输入选项编号：").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消。")
        return

    cases = list(ALL_CASES.keys())
    if choice == "0":
        try:
            req = input("  请输入审计需求：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  已取消。")
            return
        if not req:
            print("  需求不能为空。")
            return
        run_custom(req)
    elif choice.isdigit() and 1 <= int(choice) <= len(cases):
        run_case(cases[int(choice) - 1])
    else:
        print(f"  无效选项：{choice}")


# ======================================================================
# CLI 入口
# ======================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="智能审计编排系统 Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python -m demo.run_demo --case related_party
  python -m demo.run_demo --case aml
  python -m demo.run_demo --case ipo
  python -m demo.run_demo --requirement "审计关联交易定价公允性"
  python -m demo.run_demo --requirement "对银行交易进行反洗钱监控" --json
        """,
    )
    parser.add_argument(
        "--case", type=str, default=None,
        choices=list(ALL_CASES.keys()),
        help="指定审计案例（related_party / aml / ipo）",
    )
    parser.add_argument(
        "--requirement", type=str, default=None,
        help="自定义审计需求文本",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="以 JSON 格式输出最终报告（仅自定义需求模式）",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="列出所有可用案例",
    )

    args = parser.parse_args()

    # --list: 列出案例
    if args.list:
        _print_header("可用审计案例")
        for key, title in list_cases():
            case = ALL_CASES[key]
            print(f"\n  [{key}] {title}")
            print(f"    需求：{case['requirement']}")
            print(f"    预期模块：{', '.join(case['expected_modules'])}")
        return

    # --case: 指定案例
    if args.case:
        run_case(args.case)
        return

    # --requirement: 自定义需求
    if args.requirement:
        result = run_audit(args.requirement)
        if args.json:
            # JSON 模式：输出完整报告
            print(json.dumps(result.final_report, ensure_ascii=False, indent=2,
                             default=str))
        else:
            _print_planning(result.plan)
            _print_execution(result)
            _print_report(result)
        return

    # 无参数：交互式选择
    interactive_select()


if __name__ == "__main__":
    main()
