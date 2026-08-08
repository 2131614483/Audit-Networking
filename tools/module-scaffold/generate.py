"""编排：发现方案 .md → 解析 → 渲染 → 写盘。

约定：
  - 方案文档位于仓库根目录，文件名形如 {PREFIX}-{NN}-{名称}.md
  - 输出到 {repo}/modules/
  - 幂等：模块文件已存在则跳过（除非 --force）；工作区/共享文件始终刷新
"""
from __future__ import annotations

import py_compile
import re
from pathlib import Path

import renderers
from meta import FAMILY_META
from mdparser import parse_solution_doc  # 避免 stdlib parser 冲突

REPO_ROOT = Path(__file__).resolve().parents[2]   # 解决方案详细报告/
MODULES_DIR = REPO_ROOT / "modules"

_SOLUTION_RE = re.compile(r"^[A-Z]{2}-\d{2}-.+\.md$")


# ---------- 发现与解析 ----------

def discover_solution_docs(root: Path | None = None) -> list:
    root = root or REPO_ROOT
    return sorted(p for p in root.glob("*.md") if _SOLUTION_RE.match(p.name))


def parse_all(root: Path | None = None, include_fa01: bool = False) -> list:
    root = root or REPO_ROOT
    metas = []
    for p in discover_solution_docs(root):
        try:
            m = parse_solution_doc(p)
        except ValueError as e:
            print(f"  [warn] 跳过 {p.name}: {e}")
            continue
        if m.id == "FA-01" and not include_fa01:
            continue
        metas.append(m)
    return metas


def find_meta(slug_or_id: str):
    """按 slug 或 id 查找单个 ModuleMeta（含 FA-01）。"""
    key = slug_or_id.strip().upper().replace("_", "-")
    for p in discover_solution_docs(REPO_ROOT):
        try:
            m = parse_solution_doc(p)
        except ValueError:
            continue
        if m.id == key or m.slug == slug_or_id.strip().lower():
            return m
    return None


# ---------- 写盘 ----------

def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# 每模块文件清单：(相对路径, 渲染函数 meta->str)
_MODULE_FILES = [
    ("__init__.py", lambda m: renderers.render_module_init(m)),
    ("main.py", lambda m: renderers.render_module_main(m)),
    ("engine.py", lambda m: renderers.render_module_engine(m)),
    ("pipeline.py", lambda m: renderers.render_module_pipeline(m)),
    ("api.py", lambda m: renderers.render_module_api(m)),
    ("module.yaml", lambda m: renderers.render_module_yaml(m)),
    ("requirements.txt", lambda m: renderers.render_module_requirements(m)),
    ("README.md", lambda m: renderers.render_module_readme(m)),
    ("custom/__init__.py", lambda m: renderers.render_module_custom_init()),
    ("custom/custom_rules.py", lambda m: renderers.render_module_custom_rules()),
    ("custom/custom_thresholds.py", lambda m: renderers.render_module_custom_thresholds()),
    ("custom/custom_formatter.py", lambda m: renderers.render_module_custom_formatter()),
    ("config/default.yaml", lambda m: renderers.render_config_default(m)),
    ("config/custom.yaml", lambda m: renderers.render_config_custom()),
    ("config/schema.yaml", lambda m: renderers.render_config_schema(m)),
    ("tests/test_engine.py", lambda m: renderers.render_test_engine(m)),
    ("tests/test_pipeline.py", lambda m: renderers.render_test_pipeline(m)),
    ("tests/test_api.py", lambda m: renderers.render_test_api(m)),
    ("tests/fixtures/sample_input.json", lambda m: renderers.render_fixtures_input()),
    ("tests/fixtures/expected_output.json", lambda m: renderers.render_fixtures_output()),
    ("docs/ARCHITECTURE.md", lambda m: renderers.render_doc_architecture(m)),
    ("docs/API.md", lambda m: renderers.render_doc_api(m)),
    ("docs/CUSTOMIZATION.md", lambda m: renderers.render_doc_customization(m)),
    ("docs/TROUBLESHOOTING.md", lambda m: renderers.render_doc_troubleshooting()),
]

_REQUIRED_FILES = [rel for rel, _ in _MODULE_FILES]


def generate_workspace(metas: list, with_docker: bool = False) -> None:
    """生成工作区基础设施（始终刷新，保持最新）。"""
    _write(MODULES_DIR / "__init__.py", renderers.render_workspace_init())
    _write(MODULES_DIR / "README.md", renderers.render_workspace_readme(metas))

    # shared 运行时
    shared = [
        ("__init__.py", renderers.render_shared_init()),
        ("base_engine.py", renderers.render_shared_base_engine()),
        ("config_loader.py", renderers.render_shared_config_loader()),
        ("module_meta.py", renderers.render_shared_module_meta()),
        ("runtime.py", renderers.render_shared_runtime()),
    ]
    for rel, content in shared:
        _write(MODULES_DIR / "shared" / rel, content)

    # venvs：覆盖出现过的家族 + thin
    families = sorted({m.family for m in metas} | {"thin"})
    _write(MODULES_DIR / "venvs" / "setup_venvs.py", renderers.render_venv_setup_script())
    for f in families:
        _write(MODULES_DIR / "venvs" / f"{f}-requirements.txt",
               renderers.render_venv_requirements(f))

    # supervisor 示例
    _write(MODULES_DIR / "supervisor" / "audit-modules.conf.example",
           renderers.render_supervisor_conf())

    if with_docker:
        _write(MODULES_DIR / "docker" / "docker-compose.yml",
               renderers.render_docker_compose(metas))
        print("  [info] 已生成 docker/docker-compose.yml（可选容器化）")


def generate_module(meta, force: bool = False) -> bool:
    base = MODULES_DIR / meta.slug
    wrote = 0
    for rel, fn in _MODULE_FILES:
        path = base / rel
        if path.exists() and not force:
            continue
        _write(path, fn(meta))
        wrote += 1
    flag = "（覆盖）" if force and wrote else ("（已存在，跳过）" if wrote == 0 else "")
    print(f"  [ok] {meta.id:<7} {meta.name:<24} -> modules/{meta.slug}/  [{meta.family}]{flag}")
    return wrote > 0


def generate_all(include_fa01: bool = False, with_docker: bool = False,
                 force: bool = False) -> None:
    metas = parse_all(REPO_ROOT, include_fa01=include_fa01)
    if not metas:
        print("[error] 未解析到任何方案文档，请检查仓库根目录的 .md 文件")
        return
    print(f"[1/2] 生成工作区基础设施（{len(metas)} 个模块）...")
    generate_workspace(metas, with_docker=with_docker)
    print(f"[2/2] 生成模块代码包...")
    for m in metas:
        generate_module(m, force=force)
    print(f"\n[done] 共生成 {len(metas)} 个模块于 {MODULES_DIR.relative_to(REPO_ROOT)}")
    if not force:
        print("[hint] 已存在的模块未覆盖；如需重新生成，加 --force")


def generate_one(slug_or_id: str, force: bool = True) -> None:
    m = find_meta(slug_or_id)
    if m is None:
        print(f"[error] 找不到模块: {slug_or_id}")
        return
    generate_workspace([m])
    generate_module(m, force=force)


# ---------- 校验 ----------

def validate(slug_or_id: str | None = None) -> int:
    """校验模块完整性。返回错误数。"""
    if slug_or_id:
        m = find_meta(slug_or_id)
        metas = [m] if m else []
        if not metas:
            print(f"[error] 找不到模块: {slug_or_id}")
            return 1
    else:
        metas = parse_all(REPO_ROOT, include_fa01=False)
    errors = 0
    for m in metas:
        base = MODULES_DIR / m.slug
        if not base.exists():
            print(f"  [fail] {m.id}: 目录不存在 modules/{m.slug}/")
            errors += 1
            continue
        # 必选文件
        for rel in _REQUIRED_FILES:
            if not (base / rel).exists():
                print(f"  [fail] {m.id}: 缺少 {rel}")
                errors += 1
        # 语法校验
        for py in base.rglob("*.py"):
            try:
                py_compile.compile(str(py), doraise=True)
            except py_compile.PyCompileError as e:
                print(f"  [fail] {m.id}: 语法错误 {py.name}: {e}")
                errors += 1
        print(f"  [ok]   {m.id} 校验通过")
    print(f"\n[done] 校验完成，{errors} 个错误")
    return errors


# ---------- TODO 扫描 ----------

def list_todos(slug_or_id: str | None = None) -> int:
    """扫描所有生成模块的 # TODO[家族]: 标记。"""
    if slug_or_id:
        m = find_meta(slug_or_id)
        if not m:
            print(f"[error] 找不到模块: {slug_or_id}")
            return 1
        dirs = [MODULES_DIR / m.slug]
    else:
        dirs = [d for d in MODULES_DIR.iterdir() if d.is_dir() and d.name != "shared"
                and d.name not in ("venvs", "supervisor", "docker")]
    total = 0
    for d in dirs:
        for py in sorted(d.rglob("*.py")):
            try:
                lines = py.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if "# TODO[" in line:
                    rel = py.relative_to(REPO_ROOT)
                    print(f"{rel}:{i}: {line.strip()}")
                    total += 1
    print(f"\n[done] 共 {total} 个待填扩展点")
    return 0
