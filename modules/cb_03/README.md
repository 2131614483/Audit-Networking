# [CB-03] 多法域合规知识库

> 跨境审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、RAG和知识图谱的多法域合规知识库。平台整合200+国家和地区的法规知识，支持自然语言问答、合规检查、法规比对等智能功能，帮助审计人员快速获取跨境合规知识。平台可实现跨境合规知识覆盖200+国家。

## 二、技术架构设计

## 快速启动

```
python -m modules.cb_03.main          # 端口 9003
curl http://127.0.0.1:9003/api/v1/health
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
