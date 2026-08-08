# [ES-05] ESG审计知识库与AI助手

> ESG审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、RAG和知识图谱的ESG审计知识库与AI助手。平台整合ISSB、CSRD、GRI等主流ESG标准知识，支持自然语言问答、标准比对、方法论推荐等智能功能，帮助审计人员快速获取所需知识。平台可实现ESG审计标准知识覆盖95%以上，知识检索效率提升80%。

## 二、技术架构设计

## 快速启动

```
python -m modules.es_05.main          # 端口 8705
curl http://127.0.0.1:8705/api/v1/health
```

## 技术栈

LLM + RAG + KG

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
