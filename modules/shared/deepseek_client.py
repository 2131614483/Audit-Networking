"""DeepSeek LLM 客户端封装。

复用 orchestrator.py 的配置（deepseek-v4-flash + API Key + BASE URL），
对外提供统一的 `call_ai_audit_summary()` 接口，用于生成单条审计发现的AI分析总结。

设计原则：
- 异常隔离：API 调用失败时返回友好兜底文本，绝不抛出
- 结果缓存：同一 (slug+finding_id) 5 分钟内缓存，避免重复扣费
- 异步支持：FastAPI 路由可直接 await
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

# ===== 配置（与 orchestrator.py 保持一致） =====
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# 缓存：key -> (expire_ts, summary)
_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL_SEC = 300  # 5分钟

# Fallback兜底提示词（离线/API失败时使用）
_FALLBACK_SUMMARY_TEMPLATE = (
    "⚠️ AI 分析暂不可用（API 未响应）。以下为基于规则的初步判断：\n\n"
    "【数据异常点】发现中涉及的关键字段可能存在异常，建议人工核对原始数据。\n"
    "【潜在风险】{risk_hint}\n"
    "【建议措施】建议进一步查阅相关数据集（{datasets}），重点核查第 {rows} 行记录。"
)


def _cache_key(slug: str, finding_id: str) -> str:
    return f"{slug}::{finding_id}"


def _get_cached(key: str) -> str | None:
    if key not in _CACHE:
        return None
    expire_ts, val = _CACHE[key]
    if time.time() > expire_ts:
        del _CACHE[key]
        return None
    return val


def _set_cached(key: str, val: str) -> None:
    _CACHE[key] = (time.time() + _CACHE_TTL_SEC, val)


# ===== Prompt 模板 =====
AUDIT_SUMMARY_SYSTEM_PROMPT = """你是一名经验丰富的资深审计专家（CPA/CIA资格），擅长根据审计发现条目和对应的原始数据记录，给出专业、可执行的分析结论。

输出要求：
1. 语言：简洁中文，不啰嗦
2. 结构：严格分为【数据异常点】【潜在风险】【建议措施】三个小节，每小节2-4个要点
3. 每个要点用 · 开头，控制在40字以内
4. 基于提供的原始数据字段做分析，不要无中生有
5. 如果原始数据有金额字段，要换算成万元/亿元单位并提及
6. 不要Markdown标题前缀（#、## 等），直接输出三段文字

长度控制：总字数 120-200 字。"""


AUDIT_SUMMARY_USER_TEMPLATE = """
【审计发现摘要】
来源模块：{slug}
严重等级：{severity}
发现标题：{title}
详细说明：{detail}

【对应原始数据记录】（共 {rec_count} 条）
{records_json}

请按要求输出三段式审计分析结论。"""


def _build_prompt(slug: str, finding: dict, source_records: dict[str, list[dict]]) -> tuple[str, str]:
    """构造 system + user prompt。"""
    records_flat: list[dict] = []
    for fname, recs in source_records.items():
        for r in recs:
            # 去掉内部_ref仅展示数据字段
            clean = {k: v for k, v in r.items() if k != "_ref"}
            clean["_source"] = fname
            ref = r.get("_ref", {})
            if isinstance(ref, dict):
                clean["_row"] = ref.get("row", "?")
            records_flat.append(clean)

    records_json = json.dumps(records_flat[:5], ensure_ascii=False, indent=2)

    user_prompt = AUDIT_SUMMARY_USER_TEMPLATE.format(
        slug=slug,
        severity=finding.get("severity", "中"),
        title=finding.get("title", ""),
        detail=finding.get("detail", ""),
        rec_count=len(records_flat),
        records_json=records_json,
    )
    return AUDIT_SUMMARY_SYSTEM_PROMPT, user_prompt


def _fallback_summary(finding: dict, source_records: dict[str, list[dict]]) -> str:
    """API失败时的兜底规则总结。"""
    sev = finding.get("severity", "中")
    risk_hint_map = {
        "高": "该发现为高风险，可能涉及合规披露缺陷或财务错报，建议优先处理。",
        "中": "该发现为中风险，需结合业务背景进一步核实影响范围。",
        "低": "该发现为低风险，可作为后续审计关注项定期跟踪。",
    }
    risk_hint = risk_hint_map.get(sev, "建议结合具体情况人工评估风险等级。")

    datasets = "、".join(source_records.keys()) if source_records else "未匹配"
    rows_list: list[str] = []
    for recs in source_records.values():
        for r in recs:
            ref = r.get("_ref", {})
            if isinstance(ref, dict):
                row = ref.get("row", "?")
                if row != "?":
                    rows_list.append(str(row + 1))
    rows = "、".join(rows_list[:5]) if rows_list else "N/A"

    return _FALLBACK_SUMMARY_TEMPLATE.format(
        risk_hint=risk_hint,
        datasets=datasets,
        rows=rows,
    )


def _call_deepseek_sync(system_prompt: str, user_prompt: str, timeout_sec: int = 15) -> str:
    """同步调用 DeepSeek API。失败抛出异常（上层捕获后走兜底）。"""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai 包未安装，请 pip install openai")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=timeout_sec)
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=600,
    )
    content = resp.choices[0].message.content or ""
    return content.strip()


# ===== 对外主接口 =====

def call_ai_audit_summary_sync(
    slug: str,
    finding: dict,
    source_records: dict[str, list[dict]] | None = None,
    use_cache: bool = True,
) -> str:
    """同步：获取单条审计发现的AI分析总结。失败返回兜底文本。

    Args:
        slug: 模块ID，如 fa_12
        finding: 发现条目 dict（含 severity/title/detail 等）
        source_records: 结构 {文件名: [记录dict, ...]}，记录可含 _ref
        use_cache: 是否使用内存缓存

    Returns:
        分析文本，永不为 None
    """
    if not isinstance(finding, dict):
        finding = {}
    source_records = source_records or finding.get("source_records", {}) or {}

    # 缓存键：用 finding 的 title+detail 做hash避免依赖finding_id字段
    raw_id = f"{finding.get('title', '')}|{finding.get('detail', '')}"
    import hashlib
    finding_id = hashlib.md5(raw_id.encode("utf-8")).hexdigest()[:12]
    key = _cache_key(slug, finding_id)

    if use_cache:
        cached = _get_cached(key)
        if cached is not None:
            return cached

    system_prompt, user_prompt = _build_prompt(slug, finding, source_records)
    try:
        summary = _call_deepseek_sync(system_prompt, user_prompt)
        if not summary:
            raise ValueError("empty response")
    except Exception:
        summary = _fallback_summary(finding, source_records)

    if use_cache:
        _set_cached(key, summary)
    return summary


async def call_ai_audit_summary(
    slug: str,
    finding: dict,
    source_records: dict[str, list[dict]] | None = None,
    use_cache: bool = True,
) -> str:
    """异步：同步调用包装成 async，FastAPI 路由可用。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        call_ai_audit_summary_sync,
        slug, finding, source_records, use_cache,
    )
