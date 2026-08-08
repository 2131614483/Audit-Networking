# [CB-04] AI多准则自动转换引擎

> 跨境审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于LLM、RAG和知识图谱的多准则自动转换引擎。平台整合IFRS、US GAAP、China GAAP等准则知识，自动识别准则差异，生成差异分析和调节表，实现准则转换的全流程智能化。平台可将准则转换效率提升85%。

## 二、技术架构设计

## 快速启动

```
python -m modules.cb_04.main          # 端口 9004
curl http://127.0.0.1:9004/api/v1/health
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
