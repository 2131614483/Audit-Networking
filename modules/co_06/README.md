# [CO-06] AI可疑交易报告自动生成

> 合规审计 - 反洗钱 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐ · 优先级 medium

AI可疑交易报告自动生成平台基于LLM+NLP技术，自动整合多源数据生成结构化STR报告。系统从交易监控系统获取告警数据，从知识图谱提取客户关系和交易网络信息，NLP模型生成交易摘要和可疑模式描述，LLM按监管格式自动生成完整STR。预期STR编写效率提升90%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_06.main          # 端口 8206
curl http://127.0.0.1:8206/api/v1/health
```

## 技术栈

LLM + NLP + 知识图谱 + 监管模板

## 依赖

- 共享平台：akg, lsb
- 协同模块：CO-01, CO-04, CO-05

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
