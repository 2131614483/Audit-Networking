# [SC-05] AI采购价格基准平台

> 供应链审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习、自然语言处理和电商大数据的采购价格基准平台。通过自动采集电商平台、行业网站、政府公开数据等多源价格信息，利用ML模型进行价格预测和市场基准生成，为审计人员提供全面、实时、精准的价格参考基准。平台将价格基准覆盖率提升300%，显著增强采购价格审计的数据支撑能力。

## 二、技术架构设计

## 快速启动

```
python -m modules.sc_05.main          # 端口 8605
curl http://127.0.0.1:8605/api/v1/health
```

## 技术栈

ML + NLP + 电商数据

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
