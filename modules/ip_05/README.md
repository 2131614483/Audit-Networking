# [IP-05] IPO案例知识库与RAG系统

> IPO审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、RAG和知识图谱的IPO案例知识库系统。平台整合历史IPO反馈问题、审核案例、招股书等资料，支持自然语言检索、案例对标和智能问答，帮助审计人员快速获取相关案例参考。平台可将案例参考效率提升90%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ip_05.main          # 端口 8805
curl http://127.0.0.1:8805/api/v1/health
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
