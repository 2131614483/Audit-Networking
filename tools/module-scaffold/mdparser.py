"""解析方案 .md 文档 → ModuleMeta。

依赖 36 份文档一致的章节结构：
  # {id} {name}
  ### 1.1 基本信息   （7 行 markdown 表格）
  ### 1.3 方案摘要
  ## 二、技术架构设计
  ## 六、与其他方案的协同   （依赖模块编号）

注：模块名用 mdparser 而非 parser，避免与 Python 3.9 仍存在的 stdlib parser 冲突。
"""
from __future__ import annotations

import re
from pathlib import Path

from meta import (
    ModuleMeta,
    classify_family,
    count_difficulty,
    infer_platforms,
    make_slug,
    map_category,
    map_priority,
    split_tech_components,
)

ID_RE = re.compile(r"([A-Z]{2}-\d{2})")
TITLE_RE = re.compile(r"^#\s+([A-Z]{2}-\d{2})\s+(.+?)\s*$", re.M)


def _strip_md_emphasis(s: str) -> str:
    """去掉 markdown 强调符号 **xxx** → xxx。"""
    return s.replace("**", "").strip()


def _parse_info_table(text: str) -> dict:
    """解析 '### 1.1 基本信息' 后的表格为 dict。"""
    # 定位 1.1 基本信息 标题
    m = re.search(r"^###\s*1\.1\s*基本信息\s*$", text, re.M)
    if not m:
        return {}
    rest = text[m.end():]
    info = {}
    for line in rest.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            # 表格结束：遇到非表格非空行就停
            if line and not line.startswith("|") and info:
                break
            continue
        # 跳过分隔行 |---|---|
        if re.match(r"^\|[\s:|-]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # 跳过表头 | 项目 | 内容 |
        if cells[0] in ("项目", "字段", "项"):
            continue
        key = _strip_md_emphasis(cells[0])
        val = _strip_md_emphasis(cells[1])
        if key:
            info[key] = val
    return info


def _extract_section(text: str, header_re: str, until_h2: bool = False) -> str:
    """提取某标题下正文，直到下一个同级或更高级标题。"""
    m = re.search(header_re, text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    # until next ## (h2) 或 ### (h3)
    stop = re.search(r"^##\s", rest, re.M) if until_h2 else re.search(r"^###\s", rest, re.M)
    body = rest[: stop.start()] if stop else rest
    return body.strip()


def _extract_dependencies(text: str, self_id: str) -> list:
    """从 '六、与其他方案的协同' 章节提取依赖模块编号。"""
    deps = set()
    # 找含 '协同' 或 '六、' 的二级标题
    sec = re.search(r"^##\s*(六[、.]|.*协同)", text, re.M)
    section_text = ""
    if sec:
        rest = text[sec.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        section_text = rest[: nxt.start()] if nxt else rest
    else:
        # 无协同章节则无依赖（避免全文误收）
        return []
    for m in ID_RE.finditer(section_text):
        mid = m.group(1)
        if mid != self_id:
            deps.add(mid)
    # 去掉显然不是模块依赖的（如出现在技术栈里的随机大写-数字，极少见）
    return sorted(deps)


def _parse_title(text, path):
    """从文件名取 ID（可靠），从首个 # 行取名称（兼容两种标题格式）。

    格式A: # FA-02 多源数据自动标准化
    格式B: # 联邦学习跨境审计平台（CB-01）
    """
    stem = Path(path).stem
    fm = re.match(r"^([A-Z]{2}-\d{2})", stem)
    module_id = fm.group(1) if fm else None
    name = module_id or ""
    for line in text.splitlines():
        if line.startswith("#"):
            line = line.lstrip("#").strip()
            if module_id:
                line = re.sub(r"[（(]\s*" + re.escape(module_id) + r"\s*[）)]", "", line)
                line = re.sub(r"^\s*" + re.escape(module_id) + r"\s*", "", line)
            name = line.strip() or name
            break
    return module_id, name


def parse_solution_doc(path):
    """解析一份方案 .md → ModuleMeta。解析失败抛 ValueError。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    module_id, module_name = _parse_title(text, path)
    if not module_id:
        raise ValueError(f"未从文件名/标题解析到模块 ID：{path.name}")

    info = _parse_info_table(text)
    if not info:
        raise ValueError(f"未找到 '### 1.1 基本信息' 表格：{path.name}")

    # 表格字段名容错：取包含关键字的键
    def pick(*keywords):
        for k, v in info.items():
            if all(kw in k for kw in keywords) or any(kw == k for kw in keywords):
                return v
        return ""

    category_zh = pick("适用业务") or pick("所属领域") or pick("领域") or pick("业务")
    tech_stack_raw = pick("技术栈") or pick("技术路线") or pick("技术")
    difficulty_raw = pick("实施难度") or pick("难度") or pick("实施周期") or pick("周期")
    roi = pick("预期ROI") or pick("ROI") or pick("预期")
    priority_raw = pick("优先级") or pick("优先")
    duration = pick("实施周期") or pick("周期")
    budget = pick("投入预算") or pick("预算")

    description = _extract_section(text, r"^###\s*1\.3\s*方案摘要\s*$") \
        or _extract_section(text, r"^###\s*1\.2\s*问题定位\s*$")
    architecture_text = _extract_section(
        text, r"^##\s*二[、.]\s*技术架构", until_h2=True
    )
    # 控制长度，避免 ARCHITECTURE.md 过大
    if len(architecture_text) > 8000:
        architecture_text = architecture_text[:8000] + "\n\n…（截断，完整内容见原方案文档）"

    dependencies = _extract_dependencies(text, module_id)

    slug = make_slug(module_id)
    return ModuleMeta(
        id=module_id,
        name=info.get("方案名称", module_name),
        name_en=slug,
        slug=slug,
        category=map_category(category_zh),
        category_zh=category_zh or "",
        tech_stack_raw=tech_stack_raw,
        tech_components=split_tech_components(tech_stack_raw),
        family=classify_family(tech_stack_raw, module_name),
        difficulty=count_difficulty(difficulty_raw),
        priority=map_priority(priority_raw),
        roi=roi,
        duration=duration,
        budget=budget,
        description=description,
        dependencies=dependencies,
        platforms=infer_platforms(tech_stack_raw),
        architecture_text=architecture_text,
        source_path=str(path),
    )
