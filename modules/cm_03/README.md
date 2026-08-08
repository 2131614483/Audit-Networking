# [CM-03] 持续审计方法论框架

> 持续审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、知识图谱和最佳实践的持续审计方法论框架。平台通过整合持续审计的理论知识和最佳实践，构建方法论知识图谱，支持方法论推荐、程序生成和质量检查。平台可实现持续审计方法论的标准化。

## 二、技术架构设计

## 快速启动

```
python -m modules.cm_03.main          # 端口 9103
curl http://127.0.0.1:9103/api/v1/health
```

## 技术栈

LLM + KG + 最佳实践

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
