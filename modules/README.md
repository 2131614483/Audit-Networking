# 审计智能化预制菜模块工作区

本目录由 `tools/module-scaffold/scaffold.py generate --all` 生成，包含 78 个标准预制菜模块。

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
| Blockchain | blockchain | 3 个 |
| Computer Vision | cv | 4 个 |
| Federation Learning | federation | 1 个 |
| Knowledge Graph / GNN | kg_gnn | 18 个 |
| LLM / RAG | llm_rag | 23 个 |
| ML / NLP | ml_nlp | 23 个 |
| RPA | rpa | 5 个 |
| Streaming | streaming | 1 个 |

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
