# [FO-02] 知识图谱舞弊网络分析

> 法务审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于知识图谱（KG）+图神经网络（GNN）+图算法的舞弊网络分析平台，从关联关系的视角系统性发现隐蔽的舞弊网络。平台整合企业内外部数据构建交易网络图谱，利用GNN进行异常子图检测，结合图算法进行腐败模式匹配和隐藏关联发现，提供交互式网络探索分析能力。方案实施后，隐藏关联发现率提升300-500%，网络化舞弊模式的识别能力实现质的突破。

## 二、技术架构设计

## 快速启动

```
python -m modules.fo_02.main          # 端口 8402
curl http://127.0.0.1:8402/api/v1/health
```

## 技术栈

KG + GNN + 图算法

## 依赖

- 共享平台：akg
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
