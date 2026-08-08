# [CO-05] 知识图谱洗钱网络发现

> 合规审计 - 反洗钱 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐⭐ · 优先级 high

知识图谱洗钱网络发现平台构建包含客户、账户、交易、设备、外部实体等多维实体的知识图谱，通过GNN模型和子图模式匹配算法自动发现隐蔽洗钱网络。系统支持资金流可视化追踪、新型洗钱模式自动发现、洗钱网络全景展示，预期新型洗钱模式发现率提升300%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_05.main          # 端口 8205
curl http://127.0.0.1:8205/api/v1/health
```

## 技术栈

知识图谱 + GNN + 图算法 + 资金流追踪

## 依赖

- 共享平台：akg
- 协同模块：CO-04, CO-06, IA-02

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
