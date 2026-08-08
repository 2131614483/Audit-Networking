# [ES-04] 知识图谱绿色漂洗检测平台

> ESG审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于知识图谱、NLP和多源交叉验证的绿色漂洗检测平台。通过构建企业ESG声明知识图谱，将企业各渠道的环境声明进行结构化表示，并与卫星数据、传感器数据、第三方数据等客观证据进行交叉验证，自动识别声明与事实的偏差。平台可将绿色漂洗发现率提升300%，为ESG审计提供系统性的绿色漂洗检测能力。

## 二、技术架构设计

## 快速启动

```
python -m modules.es_04.main          # 端口 8704
curl http://127.0.0.1:8704/api/v1/health
```

## 技术栈

KG + NLP + 多源交叉验证

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
