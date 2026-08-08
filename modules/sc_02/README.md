# [SC-02] 知识图谱供应链网络分析

> 供应链审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于知识图谱和图神经网络的供应链网络分析平台。通过自动构建供应商多级关联图谱，利用GNN模型进行风险传导分析和隐藏关联挖掘，实现供应链网络的全面穿透和风险传导的精准识别。平台可将审计视角从单点供应商扩展到整个供应链网络，显著提升供应链审计的深度和广度。

## 二、技术架构设计

## 快速启动

```
python -m modules.sc_02.main          # 端口 8602
curl http://127.0.0.1:8602/api/v1/health
```

## 技术栈

KG + GNN + 图分析

## 依赖

- 共享平台：akg
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
