"""将 audit_data.json 转换为 Markdown 格式审计报告。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "audit_data.json"
_OUTPUT_PATH = Path(__file__).parent / "audit_report.md"

# 模块家族中文映射
_FAMILY_CN = {
    "财务审计": "FA", "合规审计": "CO", "IPO审计": "IP", "持续审计": "CM",
    "舞弊审计": "FO", "IT审计": "IT", "税务审计": "TA", "供应链审计": "SC",
    "ESG审计": "ES", "金融审计": "FI", "内部审计": "IA", "跨境审计": "CB",
    "通用审计": "GEN",
}


def _severity_badge(sev: str) -> str:
    """返回 Markdown 严重等级标记。"""
    if sev == "高":
        return "🔴 高"
    if sev == "中":
        return "🟡 中"
    return "🟢 低"


def generate_md(data: dict) -> str:
    """生成 Markdown 报告。"""
    lines: list[str] = []
    req = data.get("requirement", "")
    plan = data.get("plan", {})
    modules = plan.get("modules", [])
    edges = plan.get("edges", [])
    findings = data.get("findings", [])
    module_results = data.get("module_results", {})
    exec_log = data.get("execution_log", [])
    total_dur = data.get("total_duration", 0)

    # ---- 标题 ----
    lines.append("# 智能审计报告")
    lines.append("")
    lines.append(f"> **审计需求**: {req}  ")
    lines.append(f"> **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"> **执行耗时**: {total_dur}s  ")
    success = sum(1 for m in modules if m.get("status") == "done")
    lines.append(f"> **模块执行**: {success}/{len(modules)} 成功  ")
    lines.append("")

    # ---- 1. 执行摘要 ----
    lines.append("## 一、执行摘要")
    lines.append("")
    sev_count = {"高": 0, "中": 0, "低": 0}
    for f in findings:
        s = f.get("severity", "低")
        sev_count[s] = sev_count.get(s, 0) + 1

    lines.append("| 指标 | 数值 |")
    lines.append("|------|------|")
    lines.append(f"| 选中模块数 | {len(modules)} |")
    lines.append(f"| 数据流边数 | {len(edges)} |")
    lines.append(f"| 模块成功数 | {success} |")
    lines.append(f"| 模块失败数 | {len(modules) - success} |")
    lines.append(f"| 审计发现总数 | {len(findings)} |")
    lines.append(f"| 高风险发现 | {sev_count.get('高', 0)} |")
    lines.append(f"| 中风险发现 | {sev_count.get('中', 0)} |")
    lines.append(f"| 低风险发现 | {sev_count.get('低', 0)} |")
    lines.append("")

    # 风险等级总结
    if sev_count.get("高", 0) > 0:
        lines.append(f"⚠️ **风险提示**: 本次审计发现 **{sev_count['高']}** 条高风险审计发现，"
                     f"建议立即关注并采取整改措施。")
    elif sev_count.get("中", 0) > 0:
        lines.append(f"📋 **审计提示**: 本次审计发现 **{sev_count['中']}** 条中风险审计发现，"
                     f"建议在合理期限内跟进处理。")
    else:
        lines.append("✅ 本次审计未发现显著风险事项。")
    lines.append("")

    # ---- 2. LLM 规划推理 ----
    lines.append("## 二、AI 规划推理")
    lines.append("")
    lines.append("```")
    lines.append(plan.get("reasoning", "（无推理信息）"))
    lines.append("```")
    lines.append("")

    # ---- 3. 模块执行详情 ----
    lines.append("## 三、模块执行详情")
    lines.append("")
    lines.append("| 序号 | 模块 | 名称 | 家族 | 状态 | 耗时(s) |")
    lines.append("|------|------|------|------|------|---------|")
    for i, m in enumerate(modules, 1):
        slug = m["slug"]
        name = m.get("name", slug)
        family = m.get("family", "")
        status = m.get("status", "unknown")
        dur = m.get("duration", 0)
        status_str = "✅ 成功" if status == "done" else "❌ 失败"
        lines.append(f"| {i} | `{slug}` | {name} | {family} | {status_str} | {dur} |")
    lines.append("")

    # 各模块详细结果
    lines.append("### 模块输出摘要")
    lines.append("")
    for m in modules:
        slug = m["slug"]
        name = m.get("name", slug)
        family = m.get("family", "")
        status = m.get("status", "unknown")
        err = m.get("error")
        mr = module_results.get(slug, {})
        summary = mr.get("summary", {})

        lines.append(f"#### {slug} - {name}")
        lines.append(f"- **家族**: {family}")
        lines.append(f"- **状态**: {'✅ 成功' if status == 'done' else '❌ 失败'}")
        lines.append(f"- **耗时**: {m.get('duration', 0)}s")
        if err:
            lines.append(f"- **错误**: `{err}`")

        # 上游/下游
        inputs = m.get("inputs", [])
        outputs = m.get("outputs", [])
        if inputs:
            lines.append(f"- **上游依赖**: {', '.join(f'`{s}`' for s in inputs)}")
        if outputs:
            lines.append(f"- **下游输出**: {', '.join(f'`{s}`' for s in outputs)}")

        # 摘要
        if summary:
            if "stats" in summary:
                stats = summary["stats"]
                if stats:
                    stats_str = "  ".join(f"{k}: {v}" for k, v in stats.items())
                    lines.append(f"- **统计**: {stats_str}")
            elif "keys" in summary:
                lines.append(f"- **输出字段**: {', '.join(summary['keys'])}")
        lines.append("")

    # ---- 4. 数据流 DAG ----
    lines.append("## 四、数据流拓扑")
    lines.append("")
    lines.append("```mermaid")
    lines.append("graph LR")
    for m in modules:
        slug = m["slug"]
        name = m.get("name", slug)
        family_prefix = _FAMILY_CN.get(m.get("family", ""), "")
        status = m.get("status", "unknown")
        color = "#4caf50" if status == "done" else "#f44336"
        lines.append(f'    {slug}["{family_prefix} {name}"]')
    for src, dst in edges:
        lines.append(f"    {src} --> {dst}")
    lines.append("```")
    lines.append("")

    # ---- 5. 审计发现 ----
    lines.append("## 五、审计发现")
    lines.append("")
    if not findings:
        lines.append("本次审计未发现异常事项。")
    else:
        lines.append(f"共发现 **{len(findings)}** 条审计发现：")
        lines.append("")
        lines.append("| 序号 | 严重等级 | 来源模块 | 发现标题 | 详情 |")
        lines.append("|------|---------|---------|---------|------|")
        for i, f in enumerate(findings, 1):
            sev = f.get("severity", "低")
            source = f.get("source", "")
            title = f.get("title", "")
            detail = f.get("detail", "").replace("|", "\\|")
            if len(detail) > 120:
                detail = detail[:120] + "..."
            lines.append(f"| {i} | {_severity_badge(sev)} | `{source}` | {title} | {detail} |")
    lines.append("")

    # ---- 6. 执行日志 ----
    lines.append("## 六、执行日志")
    lines.append("")
    lines.append("```")
    for line in exec_log:
        lines.append(line)
    lines.append("```")
    lines.append("")

    # ---- 7. 结论与建议 ----
    lines.append("## 七、审计结论与建议")
    lines.append("")
    high_findings = [f for f in findings if f.get("severity") == "高"]
    mid_findings = [f for f in findings if f.get("severity") == "中"]

    if high_findings:
        lines.append("### 高风险事项")
        lines.append("")
        # 按来源模块分组
        by_source: dict[str, list] = {}
        for f in high_findings:
            by_source.setdefault(f.get("source", ""), []).append(f)
        for src, items in by_source.items():
            lines.append(f"**{src}** 模块发现 {len(items)} 条高风险事项：")
            for item in items[:5]:
                lines.append(f"- {item.get('title')}: {item.get('detail', '')[:100]}")
            if len(items) > 5:
                lines.append(f"- ...及其他 {len(items) - 5} 条")
            lines.append("")

    if mid_findings:
        lines.append("### 中风险事项")
        lines.append("")
        by_source_m: dict[str, list] = {}
        for f in mid_findings:
            by_source_m.setdefault(f.get("source", ""), []).append(f)
        for src, items in by_source_m.items():
            lines.append(f"**{src}** 模块发现 {len(items)} 条中风险事项。")
        lines.append("")

    lines.append("### 整改建议")
    lines.append("")
    if high_findings:
        lines.append("1. **立即整改**: 针对高风险审计发现，建议在 30 日内完成整改并提交整改报告。")
    if mid_findings:
        lines.append("2. **限期整改**: 针对中风险审计发现，建议在 90 日内完成整改。")
    lines.append("3. **持续监控**: 建议部署持续审计机制，对关联交易披露等关键领域实施动态监控。")
    lines.append("4. **制度完善**: 根据审计发现，完善关联方识别和信息披露内部控制制度。")
    lines.append("")

    lines.append("---")
    lines.append("*本报告由智能审计平台自动生成*")

    return "\n".join(lines)


def main():
    if not _DATA_PATH.exists():
        print(f"错误: 找不到数据文件 {_DATA_PATH}")
        print("请先运行: python demo/run_audit_report.py")
        return

    with open(_DATA_PATH, encoding="utf-8") as f:
        data = json.load(f)

    md = generate_md(data)
    with open(_OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Markdown 报告已生成: {_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
