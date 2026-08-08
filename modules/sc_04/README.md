# [SC-04] ML采购价格异常检测平台

> 供应链审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习和多维数据分析的采购价格异常检测平台。通过融合内部采购历史数据、行业价格基准、市场趋势指数等多维数据，利用多种ML算法（孤立森林、自编码器、XGBoost等）进行异常检测，实现采购价格异常的高效、精准识别。平台将价格异常发现率提升200-400%，将审计覆盖率从抽样提升到全量覆盖。

## 二、技术架构设计

## 快速启动

```
python -m modules.sc_04.main          # 端口 8604
curl http://127.0.0.1:8604/api/v1/health
```

## 技术栈

ML + 统计 + 市场数据

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
