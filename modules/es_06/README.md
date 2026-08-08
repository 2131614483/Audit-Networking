# [ES-06] AI-ESG审计方法论引擎

> ESG审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、知识图谱和模板引擎的AI-ESG审计方法论引擎。平台通过分析审计对象特征，自动生成定制化的审计程序、证据收集清单和底稿模板，实现ESG审计方法论的标准化和自动化。平台可将方法论标准化程度提升60%，审计程序编制效率提升80%。

## 二、技术架构设计

## 快速启动

```
python -m modules.es_06.main          # 端口 8706
curl http://127.0.0.1:8706/api/v1/health
```

## 技术栈

LLM + KG + 模板

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
