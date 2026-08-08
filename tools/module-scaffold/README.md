# 预制菜模块脚手架生成器

把仓库根目录的 36 份审计方案 `.md` 设计文档，按
[AI组网与预制菜模块设计方案.md](../../AI组网与预制菜模块设计方案.md) 规范，
**确定性**地批量生成"等级1 骨架"代码包到 `modules/`。

**零第三方依赖**（纯 Python 标准库）；**0 LLM token**——所有样板代码由元数据 + 家族模板
确定性地渲染，`engine.py` 仅留结构化 `TODO` 扩展点，后续填算法时才消耗少量 token。

## 为什么这样设计（省 token）

- 35 份方案文档结构高度一致（都有 `### 1.1 基本信息` 表格），可正则解析。
- 样板代码（目录结构 / module.yaml / config / Dockerfile / README / 扩展点骨架 / 测试）100%
  确定性生成，不调 LLM。
- `engine.py` 按技术栈家族（ml_nlp / llm_rag / kg_gnn / rpa / cv / streaming / blockchain /
  federation）模板化，仅核心算法留 `# TODO[家族]:` 待填。
- 打包模型：**代码包 + 家族 venv + 进程托管**，不默认 Docker（详见
  [预制菜模块脚手架生成器设计.md](../../.trae/documents/预制菜模块脚手架生成器设计.md)）。

## 文件构成

```
tools/module-scaffold/
├── scaffold.py          # CLI 入口
├── parser.py            # .md → ModuleMeta
├── meta.py              # ModuleMeta + 家族分类 + slug/平台/依赖推断
├── engine_families.py   # 8 家族 engine.py 渲染（继承 AbstractEngine）
├── renderers.py         # 其余文件渲染（shared/ + workspace + 每模块文件）
└── generate.py          # 编排：发现 → 解析 → 渲染 → 写盘 → 校验 → TODO 扫描
```

## 使用

在**仓库根目录** `c:\Pythonproject\解决方案详细报告` 下执行：

```bash
# 1. 预览：看 36 份文档解析结果与家族分类
python tools/module-scaffold/scaffold.py list

# 2. 生成全部 35 个模块（不含 FA-01）到 modules/
python tools/module-scaffold/scaffold.py generate --all

# 3. 校验：必选文件齐全 + 所有 .py 经 py_compile 语法通过
python tools/module-scaffold/scaffold.py validate --all

# 4. 查看待填扩展点清单（后续填算法用）
python tools/module-scaffold/scaffold.py todos
```

### 单个模块

```bash
python tools/module-scaffold/scaffold.py generate --module FA-02   # 生成单个（含 shared 运行时）
python tools/module-scaffold/scaffold.py validate --module FA-02
python tools/module-scaffold/scaffold.py todos --module FA-02
```

### 选项

| 选项 | 作用 |
|------|------|
| `--include-fa01` | 生成时包含 FA-01（默认跳过，因其文档标记为已完成） |
| `--with-docker` | 额外生成 `modules/docker/docker-compose.yml`（顶层单容器，非默认） |
| `--force` | 覆盖已存在的模块文件（默认幂等跳过，保护你的修改） |

## 生成产物结构

见 [预制菜模块脚手架生成器设计.md](../../.trae/documents/预制菜模块脚手架生成器设计.md)
的"工作区结构"。每个模块是一个可导入的 Python 包：

```bash
python -m modules.fa_02.main                          # 启动，端口见 module.yaml
curl http://127.0.0.1:8002/api/v1/health             # 健康检查
python -m pytest modules/fa_02/tests/                # 单测
```

## 运行环境

- Python ≥ 3.11
- 生成器本体：无依赖
- 生成的模块：fastapi / uvicorn / pyyaml / httpx（thin venv）；按家族另需 torch / neo4j 等
  （见 `modules/venvs/{family}-requirements.txt`，用 `modules/venvs/setup_venvs.py` 一键建）

## 幂等性

- 工作区基础设施（`modules/__init__.py`、`shared/`、`venvs/`、`supervisor/`、README）**始终刷新**。
- 各模块文件**已存在则跳过**（保护你的 `engine.py` / `custom/` 修改），需更新加 `--force`。
