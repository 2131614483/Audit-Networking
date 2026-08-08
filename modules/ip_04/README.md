# [IP-04] AI财务规范性智能诊断系统

> IPO审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习、NLP和行业对标的AI财务规范性智能诊断系统。平台通过学习历史IPO审核中的财务问题模式，结合行业对标数据，自动识别和诊断企业财务规范性问题，并按风险程度排序。平台可将财务问题发现率提升50-80%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ip_04.main          # 端口 8804
curl http://127.0.0.1:8804/api/v1/health
```

## 技术栈

ML + NLP + 行业对标

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
