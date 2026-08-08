# [IP-02] AI监管反馈智能回复系统

> IPO审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、RAG和历史案例库的AI监管反馈智能回复系统。平台通过构建历史IPO反馈问询案例库，利用RAG技术快速检索相似案例，结合LLM自动生成回复初稿，辅助审计人员高效、准确地完成问询回复。平台可将反馈回复效率提升70%，回复质量提升40%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ip_02.main          # 端口 8802
curl http://127.0.0.1:8802/api/v1/health
```

## 技术栈

LLM + RAG + 案例库

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
