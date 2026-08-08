# [FI-03] ML贷款违约预测验证系统

> 金融专项审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习、时间序列分析和可解释AI的贷款违约预测验证系统。平台通过自动化模型回测、可解释性分析和压力测试，实现对违约预测模型的全面、高效验证。平台可将模型验证效率提升90%。

## 二、技术架构设计

## 快速启动

```
python -m modules.fi_03.main          # 端口 8903
curl http://127.0.0.1:8903/api/v1/health
```

## 技术栈

ML + 时间序列 + XAI

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
