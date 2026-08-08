# [IP-03] 知识图谱历史沿革梳理系统

> IPO审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于知识图谱、NLP和时间轴分析的历史沿革梳理系统。通过自动抽取企业工商档案、股东会决议等文件中的关键信息，构建企业历史沿革知识图谱，自动生成股权变更时间线，并进行合规性检查。平台可将历史沿革梳理效率提升90%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ip_03.main          # 端口 8803
curl http://127.0.0.1:8803/api/v1/health
```

## 技术栈

KG + NLP + 时间轴

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
