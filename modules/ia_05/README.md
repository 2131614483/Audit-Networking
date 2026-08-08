# [IA-05] AI驱动的管理建议书

> 内部审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐⭐ · 优先级 high

AI驱动的管理建议书平台基于LLM+RAG技术，构建行业管理建议知识库，自动生成针对性、可操作、可量化的管理建议。系统通过RAG检索历史优秀案例和行业最佳实践，LLM生成建议初稿，ML模型自动量化建议价值，审计经理审核调整后形成最终建议书。预期建议采纳率提升30-50%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_05.main          # 端口 8105
curl http://127.0.0.1:8105/api/v1/health
```

## 技术栈

LLM + RAG + 行业对标 + 价值量化

## 依赖

- 共享平台：lsb
- 协同模块：IA-01, IA-04, IA-06, IA-07

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
