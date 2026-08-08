# [TA-04] AI转让定价文档自动生成

> 税务审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于ML+NLP+LLM+KG的AI转让定价文档自动生成平台，实现转让定价文档的智能化编制。平台利用ML模型进行可比公司智能筛选，利用NLP+LLM进行行业分析和文档撰写，利用知识图谱沉淀转让定价知识，自动生成符合税务合规要求的转让定价文档。方案实施后，文档编制效率提升85%，编制周期从4-8周缩短到3-5天。

## 二、技术架构设计

## 快速启动

```
python -m modules.ta_04.main          # 端口 8504
curl http://127.0.0.1:8504/api/v1/health
```

## 技术栈

ML + NLP + LLM + KG

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
