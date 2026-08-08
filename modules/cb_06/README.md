# [CB-06] 集团审计智能协作平台

> 跨境审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于RPA、LLM和知识图谱的集团审计智能协作平台。平台通过RPA自动化审计指令分发和结果收集，LLM辅助跨语言沟通和报告生成，知识图谱实现审计知识的跨区域共享。平台可将集团审计协作效率提升75%。

## 二、技术架构设计

## 快速启动

```
python -m modules.cb_06.main          # 端口 9006
curl http://127.0.0.1:9006/api/v1/health
```

## 技术栈

RPA + LLM + KG

## 依赖

- 共享平台：lsb, rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
