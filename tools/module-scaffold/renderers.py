"""所有生成文件的渲染器。

分三类：
  - 共享运行时 (modules/shared/*)
  - 工作区 (modules/__init__.py, README, venvs/, supervisor/, docker/)
  - 每模块文件 (modules/{slug}/*)

代码模板用 <<PLACEHOLDER>> + _sub() 占位，避开 f-string 花括号冲突。
"""
from __future__ import annotations

from meta import ModuleMeta, FAMILY_META
from engine_families import render_engine


def _sub(tpl: str, **kw) -> str:
    for k, v in kw.items():
        tpl = tpl.replace(f"<<{k}>>", str(v))
    return tpl


# ---------- 端口派生（按业务域前缀分段，避免冲突） ----------
_PORT_BASE = {
    "FA": 8000, "IA": 8100, "CO": 8200, "IT": 8300, "FO": 8400,
    "TA": 8500, "SC": 8600, "ES": 8700, "IP": 8800, "FI": 8900,
    "CB": 9000, "CM": 9100,
}


def _port(meta: ModuleMeta) -> int:
    prefix = meta.id[:2]
    try:
        num = int(meta.id.split("-")[1])
    except Exception:
        num = 0
    return _PORT_BASE.get(prefix, 8000) + num


# ============================================================
# 共享运行时 (modules/shared/)
# ============================================================

def render_shared_init() -> str:
    return '"""共享运行时：引擎基类、配置加载、模块元数据、进程入口。"""\n'


def render_shared_base_engine() -> str:
    return '''"""AbstractEngine —— 预制菜模块核心引擎基类（模板方法模式）。

所有家族引擎继承此类，实现 _load_model / _preprocess / _infer / _postprocess。
execute() 为不可修改的模板方法：预处理 → 推理 → 后处理。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AbstractEngine(ABC):
    """模块核心引擎基类。"""

    def __init__(self, config: dict | None = None):
        self.config: dict = config or {}
        self.model: Any = None

    def setup(self) -> "AbstractEngine":
        """显式触发模型/连接加载（可选）。"""
        self._load_model()
        return self

    def execute(self, input_data: Any) -> Any:
        """模板方法：预处理 → 推理 → 后处理。子类不要覆盖本方法。"""
        prepared = self._preprocess(input_data)
        result = self._infer(prepared)
        return self._postprocess(result)

    @abstractmethod
    def _load_model(self) -> None:
        """加载模型 / 连接共享平台。"""

    @abstractmethod
    def _preprocess(self, input_data: Any) -> Any:
        """数据预处理 / 特征工程。"""

    @abstractmethod
    def _infer(self, prepared: Any) -> Any:
        """核心推理 / 计算。"""

    @abstractmethod
    def _postprocess(self, result: Any) -> Any:
        """结果后处理 / 格式化。"""
'''


def render_shared_config_loader() -> str:
    return '''"""三级配置加载：default.yaml ← custom.yaml ← 运行时覆盖。

加载顺序（后者覆盖前者）：
  1. config/default.yaml   出厂默认
  2. config/custom.yaml    用户定制
  3. overrides 参数         运行时覆盖
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(module_dir: str | Path, overrides: dict | None = None) -> dict:
    """加载模块配置。module_dir 指向模块根目录（含 config/ 子目录）。"""
    cfg_dir = Path(module_dir) / "config"
    default = _read_yaml(cfg_dir / "default.yaml")
    custom = _read_yaml(cfg_dir / "custom.yaml")
    merged = _deep_merge(default, custom)
    if overrides:
        merged = _deep_merge(merged, overrides)
    return merged
'''


def render_shared_module_meta() -> str:
    return '''"""读取模块根目录的 module.yaml 元数据。"""
from __future__ import annotations

from pathlib import Path

import yaml


def load_module_yaml(module_dir: str | Path) -> dict:
    """返回 module.yaml 解析后的 dict。"""
    p = Path(module_dir) / "module.yaml"
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
'''


def render_shared_runtime() -> str:
    return '''"""统一运行时入口。

用法（在仓库根目录执行）：
  python -m modules.shared.runtime fa_02        # 启动 fa_02 模块
  python -m modules.shared.runtime fa_02 fa_07  # 启动多个（顺序）
"""
from __future__ import annotations

import importlib
import logging
import sys

logger = logging.getLogger("modules.runtime")


def start(slug: str) -> None:
    try:
        mod = importlib.import_module(f"modules.{slug}.main")
    except ModuleNotFoundError as e:
        logger.error("找不到模块 modules.%s.main：%s", slug, e)
        sys.exit(1)
    import uvicorn
    port = getattr(mod, "PORT", 8000)
    logger.info("启动模块 %s 于 0.0.0.0:%d", slug, port)
    uvicorn.run(mod.app, host="0.0.0.0", port=port)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("用法: python -m modules.shared.runtime <slug> [<slug> ...]  例如 fa_02")
        sys.exit(1)
    for slug in sys.argv[1:]:
        start(slug)


if __name__ == "__main__":
    main()
'''


# ============================================================
# 工作区 (modules/)
# ============================================================

def render_workspace_init() -> str:
    return '"""审计智能化预制菜模块工作区。"""\n'


def render_workspace_readme(metas: list) -> str:
    families = {}
    for m in metas:
        families.setdefault(m.family, 0)
        families[m.family] += 1
    fam_lines = "\n".join(
        f"| {FAMILY_META.get(f, {}).get('display', f)} | {f} | {c} 个 |"
        for f, c in sorted(families.items())
    )
    total = len(metas)
    return f'''# 审计智能化预制菜模块工作区

本目录由 `tools/module-scaffold/scaffold.py generate --all` 生成，包含 {total} 个标准预制菜模块。

## 目录结构

```
modules/
├── shared/      共享运行时（引擎基类、配置加载、进程入口）
├── venvs/       家族虚拟环境清单 + 建环境脚本
├── supervisor/  可选进程托管配置
├── fa_02/       每个模块 = 一个可导入的 Python 包
└── ...
```

## 快速开始

1. **建家族 venv**（按需，先建 thin 即可跑多数模块）：
   ```
   python modules/venvs/setup_venvs.py ml        # 建 .venvs/ml/
   ```

2. **运行模块**（在仓库根目录执行）：
   ```
   python -m modules.fa_02.main                  # 启动 FA-02，访问 http://127.0.0.1:8002/api/v1/health
   python -m modules.shared.runtime fa_02 fa_07  # 统一入口启动多个
   ```

3. **测试**：
   ```
   python -m pytest modules/fa_02/tests/         # 模块单测
   ```

## 模块家族分布

| 家族 | venv | 数量 |
|------|------|------|
{fam_lines}

## 定制开发

- 业务逻辑：编辑模块 `engine.py`，填充 `# TODO[家族]: ...` 标记的方法。
- 规则/阈值/格式：编辑模块 `custom/` 下三个文件（无需动 engine）。
- 配置：编辑 `config/custom.yaml`（覆盖 `default.yaml`，不改正文）。
- 扫描所有待填点：`python tools/module-scaffold/scaffold.py todos`

## 打包模型

- 模块 = Python 代码包（不默认 Docker）。
- 依赖隔离用家族 venv；运行隔离用 OS 进程。
- 如需容器化：`python tools/module-scaffold/scaffold.py generate --all --with-docker`
  会生成 `modules/docker/docker-compose.yml`（顶层单容器跑选定模块）。
'''


_BASE_REQS = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

_VENV_EXTRA = {
    "ml": ["numpy>=1.26", "pandas>=2.1", "scikit-learn>=1.4",
           "xgboost>=2.0", "joblib>=1.3"],
    "kg": ["neo4j>=5.17", "torch>=2.2", "torch-geometric>=2.5"],
    "llm": ["jinja2>=3.1"],
    "cv": ["torch>=2.2", "paddleocr>=2.7", "opencv-python>=4.9"],
    "streaming": ["kafka-python>=2.0"],
    "rpa": [],
    "blockchain": ["cryptography>=42.0"],
    "federation": ["torch>=2.2"],
    "thin": [],
}


def family_requirements(family: str) -> list:
    return _BASE_REQS + _VENV_EXTRA.get(family, [])


def render_venv_requirements(family: str) -> str:
    lines = ["# 家族虚拟环境依赖", "# 安装: python modules/venvs/setup_venvs.py " + family, ""]
    lines += family_requirements(family)
    return "\n".join(lines) + "\n"


def render_venv_setup_script() -> str:
    return '''"""一键创建家族虚拟环境。

用法：
  python modules/venvs/setup_venvs.py ml          # 只建 ml
  python modules/venvs/setup_venvs.py all         # 建全部家族
  python modules/venvs/setup_venvs.py thin ml kg  # 建指定若干
"""
from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # 仓库根
VENV_DIR = ROOT / ".venvs"
REQ_DIR = Path(__file__).resolve().parent

ALL_FAMILIES = ["thin", "ml", "kg", "llm", "cv", "streaming", "rpa", "blockchain", "federation"]


def create(family: str) -> None:
    target = VENV_DIR / family
    if target.exists():
        print(f"[skip] {target} 已存在")
        return
    print(f"[create] {target}")
    venv.create(target, with_pip=True, clear=False)
    pip = str(target / "Scripts" / "pip.exe") if sys.platform == "win32" else str(target / "bin" / "pip")
    req = REQ_DIR / f"{family}-requirements.txt"
    if req.exists():
        print(f"[install] {req.name}")
        subprocess.check_call([pip, "install", "-r", str(req)])
    print(f"[done] 激活: {target}/Scripts/activate  或  source {target}/bin/activate")


def main() -> None:
    args = sys.argv[1:] or ["thin"]
    fams = ALL_FAMILIES if args[0] == "all" else args
    for f in fams:
        if f not in ALL_FAMILIES:
            print(f"[warn] 未知家族 {f}，跳过")
            continue
        create(f)


if __name__ == "__main__":
    main()
'''


def render_supervisor_conf() -> str:
    return '''; supervisord 配置示例：把选定模块作为独立进程托管。
; 用法: supervisord -c modules/supervisor/audit-modules.conf
; 每个模块用对应家族 venv 的 python 启动。

[program:fa_02]
command=%(here)s/../../.venvs/ml/Scripts/python.exe -m modules.fa_02.main
directory=%(here)s/../..
autorestart=true
stdout_logfile=%(here)s/logs/fa_02.log
stderr_logfile=%(here)s/logs/fa_02.err

; [program:fa_07]
; command=%(here)s/../../.venvs/llm/Scripts/python.exe -m modules.fa_07.main
; directory=%(here)s/../..
; autorestart=true
'''


def render_docker_compose(metas: list) -> str:
    services = []
    for m in metas[:8]:  # 示例取前 8 个
        services.append(
            f"  {m.slug}:\n"
            f"    build: {{ context: .., dockerfile: docker/Dockerfile.{m.family} }}\n"
            f"    command: python -m modules.{m.slug}.main\n"
            f"    ports: [\"{_port(m)}:{_port(m)}\"]\n"
            f"    environment:\n"
            f"      - PYTHONPATH=/app\n"
            f"    working_dir: /app"
        )
    return (
        "# 顶层单容器化部署示例（--with-docker 生成）。\n"
        "# 非默认：本工作区默认用家族 venv + 进程托管，不强制 Docker。\n"
        "version: \"3.9\"\n"
        "services:\n" + "\n\n".join(services) + "\n"
    )


# ============================================================
# 每模块文件 (modules/{slug}/)
# ============================================================

def render_module_init(meta: ModuleMeta) -> str:
    return f'"""[{meta.id}] {meta.name} —— 预制菜模块。"""\n\n__version__ = "1.0.0"\n'


def render_module_main(meta: ModuleMeta) -> str:
    port = _port(meta)
    return _sub(
        '''"""[<<ID>>] <<NAME>> —— 模块入口。

启动：python -m modules.<<SLUG>>.main
健康：GET /api/v1/health
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from .api import router

logger = logging.getLogger("modules.<<SLUG>>")

PORT = <<PORT>>

app = FastAPI(title="[<<ID>>] <<NAME>>", version="1.0.0")
app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {
        "module": "<<ID>>",
        "name": "<<NAME>>",
        "family": "<<FAMILY>>",
        "status": "ok",
    }


def register_to_bus():
    """注册到组网总线（本次未实现总线，留桩；模块可独立运行）。"""
    logger.info("register_to_bus: 组网总线未启用，跳过")
    return False


@app.on_event("startup")
def _on_startup():
    register_to_bus()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("modules.<<SLUG>>.main:app", host="0.0.0.0", port=PORT, reload=True)
''',
        ID=meta.id, NAME=meta.name, SLUG=meta.slug, FAMILY=meta.family, PORT=port,
    )


def render_module_engine(meta: ModuleMeta) -> str:
    return render_engine(meta)


def render_module_pipeline(meta: ModuleMeta) -> str:
    return _sub(
        '''"""[<<ID>>] 执行管道 —— 采集 → 处理 → 输出三阶段骨架。

可在此编排 engine 与 custom_* 的调用顺序。默认串联 engine.execute。
"""
from __future__ import annotations

from typing import Any

from .engine import <<ENGINE_CLASS>>
from .custom.custom_rules import apply_custom_rules
from .custom.custom_thresholds import apply_thresholds
from .custom.custom_formatter import format_output


class Pipeline:
    """模块执行管道。"""

    def __init__(self, config: dict | None = None):
        self.engine = <<ENGINE_CLASS>>(config)

    def run(self, input_data: Any) -> Any:
        # TODO[pipeline]: 按需调整阶段顺序
        collected = self._collect(input_data)
        result = self.engine.execute(collected)
        result = apply_thresholds(result, self.engine.config)
        result = apply_custom_rules(result, self.engine.config)
        return self._output(result)

    def _collect(self, input_data: Any) -> Any:
        # TODO[pipeline]: 数据采集 / 接入共享平台 ADL
        return input_data

    def _output(self, result: Any) -> Any:
        # TODO[pipeline]: 结果输出 / 回写 ADL
        return format_output(result)
''',
        ID=meta.id, ENGINE_CLASS=meta.engine_class,
    )


def render_module_api(meta: ModuleMeta) -> str:
    return _sub(
        '''"""[<<ID>>] REST API 骨架。"""
from __future__ import annotations

from fastapi import APIRouter

from .pipeline import Pipeline

router = APIRouter()


@router.get("/info")
def info():
    return {"module": "<<ID>>", "name": "<<NAME>>"}


@router.post("/execute")
def execute(payload: dict):
    """触发模块执行。核心算法未填充时返回 501 提示。"""
    pipe = Pipeline()
    try:
        return {"status": "ok", "result": pipe.run(payload)}
    except NotImplementedError as e:
        return {"status": "not_implemented", "todo": str(e)}
''',
        ID=meta.id, NAME=meta.name,
    )


def render_module_custom_init() -> str:
    return '"""用户定制扩展点：规则、阈值、格式。改这里无需动 engine。"""\n'


def render_module_custom_rules() -> str:
    return '''"""自定义业务规则。在 engine 之后执行，可覆盖/补充结果。"""
from __future__ import annotations

from typing import Any


def apply_custom_rules(result: Any, config: dict) -> Any:
    # TODO[custom]: 在此补充业务规则（如剔除、重分类、标记）
    return result
'''


def render_module_custom_thresholds() -> str:
    return '''"""自定义阈值。从 config 读取，便于不改代码调参。"""
from __future__ import annotations

from typing import Any


def apply_thresholds(result: Any, config: dict) -> Any:
    # TODO[custom]: 应用 config 中的阈值（如置信度门槛、告警分级）
    # threshold = config.get("threshold", {})
    return result
'''


def render_module_custom_formatter() -> str:
    return '''"""自定义输出格式化。"""
from __future__ import annotations

from typing import Any


def format_output(result: Any) -> Any:
    # TODO[custom]: 把内部结果转为对外输出结构
    return result
'''


def render_module_yaml(meta: ModuleMeta) -> str:
    deps_yaml = "\n".join(f"      - {d}" for d in meta.dependencies) or "      []"
    platforms_yaml = "\n".join(f"    - {p}" for p in meta.platforms) or "  []"
    return f'''# 模块元数据（预制菜规范 §3.2）
module:
  id: {meta.id}
  name: {meta.name}
  name_en: {meta.slug}
  version: 1.0.0
  category: {meta.category}
  family: {meta.family}
  family_display: {meta.family_display}
  difficulty: {meta.difficulty}
  priority: {meta.priority}
  roi: "{meta.roi}"
  duration: "{meta.duration}"
  budget: "{meta.budget}"
  description: >
    {meta.description.replace(chr(10), " ")[:300]}

runtime:
  language: python
  language_version: "3.11"
  framework: fastapi
  package: modules.{meta.slug}
  port: {_port(meta)}
  health_check: /api/v1/health

dependencies:
  platforms:
{platforms_yaml}
  modules:
{deps_yaml}

interfaces:
  consumes: []
  produces: []
  rest_apis:
    - path: /api/v1/execute
      method: POST
      desc: 触发模块执行

resources:
  cpu: "1"
  memory: "1Gi"

configurable:
  threshold:
    confidence: 0.85
  model:
    path: models/model.pkl

extension_points:
  - src/custom/custom_rules.py
  - src/custom/custom_thresholds.py
  - src/custom/custom_formatter.py
'''


def render_config_default(meta: ModuleMeta) -> str:
    family = meta.family
    if family == "llm_rag":
        extra = '''  lsb:
    base_url: http://localhost:8080   # LLM 服务总线
  llm:
    prompt_template: templates/prompt.txt
    temperature: 0.2
'''
    elif family == "kg_gnn":
        extra = '''  kg:
    uri: bolt://localhost:7687
    user: neo4j
  gnn:
    model_path: models/gnn.pt
'''
    elif family in ("ml_nlp",):
        extra = '''  model:
    path: models/model.pkl
  threshold:
    confidence: 0.85
'''
    elif family == "cv":
        extra = '''  ocr:
    lang: ch
    use_angle_cls: true
'''
    elif family == "streaming":
        extra = '''  kafka:
    brokers: localhost:9092
    topic: audit.events
'''
    elif family == "rpa":
        extra = '''  rop:
    base_url: http://localhost:8090   # RPA 编排平台
  rpa:
    flow_id: ""
'''
    elif family == "blockchain":
        extra = '''  chain:
    profile: default
    contract: audit-evidence
'''
    elif family == "federation":
        extra = '''  fed:
    server: http://localhost:8100
    rounds: 10
    dp_epsilon: 8.0
'''
    else:
        extra = ""
    return f'''# 出厂默认配置（请勿直接改，用 custom.yaml 覆盖）
module:
  id: {meta.id}
  name: {meta.name}
{extra}'''


def render_config_custom() -> str:
    return '''# 用户定制配置（覆盖 default.yaml，仅写需要覆盖的项）
# 示例：
# threshold:
#   confidence: 0.90
'''


def render_config_schema(meta: ModuleMeta) -> str:
    return f'''# 配置项 JSON Schema（用于校验 default/custom.yaml）
$schema: "http://json-schema.org/draft-07/schema#"
title: {meta.id} 配置
type: object
properties:
  module:
    type: object
    properties:
      id: {{type: string}}
      name: {{type: string}}
  threshold:
    type: object
    properties:
      confidence: {{type: number, minimum: 0, maximum: 1}}
'''


def render_test_engine(meta: ModuleMeta) -> str:
    return _sub(
        '''"""[<<ID>>] engine 单测骨架。"""
import pytest

from modules.<<SLUG>>.engine import <<ENGINE_CLASS>>


def test_engine_not_implemented():
    """骨架阶段：execute 应抛 NotImplementedError（算法未填充）。"""
    eng = <<ENGINE_CLASS>>(config={"threshold": {"confidence": 0.9}})
    with pytest.raises(NotImplementedError):
        eng.execute({"sample": 1})
''',
        ID=meta.id, SLUG=meta.slug, ENGINE_CLASS=meta.engine_class,
    )


def render_test_pipeline(meta: ModuleMeta) -> str:
    return _sub(
        '''"""[<<ID>>] pipeline 单测骨架。"""
import pytest

from modules.<<SLUG>>.pipeline import Pipeline


def test_pipeline_not_implemented():
    pipe = Pipeline()
    with pytest.raises(NotImplementedError):
        pipe.run({"sample": 1})
''',
        ID=meta.id, SLUG=meta.slug,
    )


def render_test_api(meta: ModuleMeta) -> str:
    return _sub(
        '''"""[<<ID>>] API 单测骨架。"""
from fastapi.testclient import TestClient

from modules.<<SLUG>>.main import app

client = TestClient(app)


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["module"] == "<<ID>>"
    assert body["status"] == "ok"


def test_info():
    r = client.get("/api/v1/info")
    assert r.status_code == 200
''',
        ID=meta.id, SLUG=meta.slug,
    )


def render_fixtures_input() -> str:
    return '{\n  "sample": "replace with real input shape"\n}\n'


def render_fixtures_output() -> str:
    return '{\n  "status": "ok",\n  "result": null\n}\n'


def render_doc_architecture(meta: ModuleMeta) -> str:
    arch = meta.architecture_text or "（未从原方案文档提取到架构章节，请补充。）"
    return f'''# [{meta.id}] {meta.name} —— 架构说明

> 家族：{meta.family_display}　|　技术栈：{meta.tech_stack_raw}

以下内容自动提取自原方案文档 `二、技术架构设计` 章节：

---

{arch}
'''


def render_doc_api(meta: ModuleMeta) -> str:
    return f'''# [{meta.id}] API 说明

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/v1/health | 健康检查 |
| GET | /api/v1/info | 模块信息 |
| POST | /api/v1/execute | 触发执行（算法未填充时返回 not_implemented） |

启动：`python -m modules.{meta.slug}.main`（端口 {_port(meta)}）
'''


def render_doc_customization(meta: ModuleMeta) -> str:
    return f'''# [{meta.id}] 定制指南

填充顺序（L0→L4，参见预制菜规范 §5.2）：

1. **L1 配置**：改 `config/custom.yaml`（阈值、连接地址），不改代码。
2. **L2 规则/阈值/格式**：改 `src/custom/custom_{{rules,thresholds,formatter}}.py`，无需动 engine。
3. **L3 核心算法**：改 `src/engine.py`，填充 `# TODO[{meta.family}]: ...` 标记的方法。
4. **L4 接口/管道**：改 `src/api.py` / `src/pipeline.py`，调整端点与流程编排。

扩展点清单：
- `src/custom/custom_rules.py` → `apply_custom_rules(result, config)`
- `src/custom/custom_thresholds.py` → `apply_thresholds(result, config)`
- `src/custom/custom_formatter.py` → `format_output(result)`
- `src/engine.py` → `_load_model / _preprocess / _infer / _postprocess`
'''


def render_doc_troubleshooting() -> str:
    return '''# 故障排查

| 现象 | 排查 |
|------|------|
| `ModuleNotFoundError: modules.shared` | 在仓库根目录运行，确保 cwd 在 path |
| `ModuleNotFoundError: fastapi` | 未建家族 venv，运行 `python modules/venvs/setup_venvs.py thin` |
| 端口冲突 | 见 module.yaml `runtime.port`，按业务域前缀分段 |
| `/execute` 返回 not_implemented | 正常，engine.py 算法未填充（TODO） |
| NotImplementedError | 填充对应 `# TODO[家族]:` 方法 |
'''


def render_module_requirements(meta: ModuleMeta) -> str:
    return render_venv_requirements(meta.family)


def render_module_readme(meta: ModuleMeta) -> str:
    deps = ", ".join(meta.dependencies) if meta.dependencies else "无"
    return f'''# [{meta.id}] {meta.name}

> {meta.category_zh} · 家族 {meta.family_display} · 难度 {"⭐"*meta.difficulty} · 优先级 {meta.priority}

{meta.description[:200]}

## 快速启动

```
python -m modules.{meta.slug}.main          # 端口 {_port(meta)}
curl http://127.0.0.1:{_port(meta)}/api/v1/health
```

## 技术栈

{meta.tech_stack_raw}

## 依赖

- 共享平台：{", ".join(meta.platforms)}
- 协同模块：{deps}

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[{meta.family}]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
'''
