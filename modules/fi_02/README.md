# [FI-02] 知识图谱担保链风险分析系统

> 金融专项审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于知识图谱、图神经网络和压力测试的担保链风险分析系统。通过构建企业担保网络知识图谱，利用GNN模型进行风险传导分析和互保圈识别，结合压力测试模拟极端情况下的风险传导。平台可将担保风险发现率提升300%。

## 二、技术架构设计

## 快速启动

```
python -m modules.fi_02.main          # 端口 8902
curl http://127.0.0.1:8902/api/v1/health
```

## 技术栈

KG + GNN + 压力测试

## 依赖

- 共享平台：akg
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
