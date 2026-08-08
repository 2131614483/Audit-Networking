# [CM-05] 持续审计仪表板

> 持续审计 · 家族 ML / NLP · 难度 ⭐⭐ · 优先级 medium

本方案构建基于BI、实时数据和故事化呈现的持续审计仪表板。平台通过实时数据可视化、趋势分析和自动报告功能，为管理层和审计人员提供直观、全面、及时的审计洞察。平台可将管理层认可度提升50%。

## 二、技术架构设计

## 快速启动

```
python -m modules.cm_05.main          # 端口 9105
curl http://127.0.0.1:9105/api/v1/health
```

## 技术栈

BI + 实时数据 + 故事化呈现

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
