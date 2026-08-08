# [SC-01] 供应商风险智能评分平台

> 供应链审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习、自然语言处理和多方数据融合的供应商风险智能评分平台。平台通过自动化采集工商信息、司法数据、财务数据、ESG数据和舆情数据等五大维度数据，利用ML模型进行风险评分，实现对供应商风险的全面覆盖和实时感知，将评估周期从传统的季度/年度评估压缩至T+1天，显著提升供应链审计的覆盖面和时效性。

## 二、技术架构设计

## 快速启动

```
python -m modules.sc_01.main          # 端口 8601
curl http://127.0.0.1:8601/api/v1/health
```

## 技术栈

ML + NLP + 多源数据融合

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
