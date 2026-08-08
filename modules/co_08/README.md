# [CO-08] 知识图谱数据流分析

> 合规审计 - 数据治理 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐ · 优先级 medium

知识图谱数据流分析平台通过自动构建数据血缘图谱，可视化展示数据从采集、存储、处理、传输到销毁的全生命周期。系统自动识别跨境数据传输路径，评估数据流转过程中的合规风险，为数据合规审计提供全景式视图。实现跨境数据流的自动可视化。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_08.main          # 端口 8208
curl http://127.0.0.1:8208/api/v1/health
```

## 技术栈

知识图谱 + 数据血缘 + 图算法 + 可视化

## 依赖

- 共享平台：akg
- 协同模块：CO-01, CO-07, CO-09

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
