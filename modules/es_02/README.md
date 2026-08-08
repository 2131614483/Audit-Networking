# [ES-02] AI碳排放自动核算引擎

> ESG审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习、IoT数据接入和排放因子库的AI碳排放自动核算引擎。平台通过自动采集企业能耗数据、生产数据、供应链数据，结合排放因子库，利用ML模型自动计算Scope1/2/3碳排放，实现碳核算的全流程自动化。平台将碳核算效率提升85%，核算精度提升30%以上。

## 二、技术架构设计

## 快速启动

```
python -m modules.es_02.main          # 端口 8702
curl http://127.0.0.1:8702/api/v1/health
```

## 技术栈

ML + IoT + 排放因子

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
