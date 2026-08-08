# [TA-06] 知识图谱全球关联交易分析

> 税务审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于知识图谱（KG）+图神经网络（GNN）+利润分割分析的全球关联交易分析平台，实现跨国企业全球关联交易的系统性分析和转让定价风险的智能识别。平台构建全球实体网络知识图谱，利用GNN进行异常交易模式和利润转移路径的自动发现，结合利润分割模型进行功能-风险-利润的匹配分析。方案实施后，利润转移风险发现率提升200-400%，全球关联交易分析效率实现质的突破。

## 二、技术架构设计

## 快速启动

```
python -m modules.ta_06.main          # 端口 8506
curl http://127.0.0.1:8506/api/v1/health
```

## 技术栈

KG + GNN + 利润分割

## 依赖

- 共享平台：akg
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
