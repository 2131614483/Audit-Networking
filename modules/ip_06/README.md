# [IP-06] 整改方案AI推荐引擎

> IPO审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、ML和效果预估的整改方案AI推荐引擎。平台通过问题诊断、方案推荐、效果预估和优先级排序的全流程智能化，为审计人员提供高质量的整改方案推荐。平台可将整改方案质量提升50%，方案制定效率提升80%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ip_06.main          # 端口 8806
curl http://127.0.0.1:8806/api/v1/health
```

## 技术栈

LLM + ML + 效果预估

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
