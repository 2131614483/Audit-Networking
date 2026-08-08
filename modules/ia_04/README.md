# [IA-04] 审计价值仪表板

> 内部审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

审计价值仪表板基于BI技术构建实时可视化平台，通过ML模型对审计发现进行价值量化计算，设计分层KPI树（战略层/运营层/执行层）全面展示审计贡献。平台支持从董事会到审计师的多角色视图，实时数据刷新，并提供"假设分析"场景模拟能力，帮助审计部门用数据说话，提升管理层认可度50%以上。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_04.main          # 端口 8104
curl http://127.0.0.1:8104/api/v1/health
```

## 技术栈

BI + ML + 实时数据 + KPI树

## 依赖

- 共享平台：adl
- 协同模块：IA-01, IA-05, IA-06, IA-07

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
