# [TA-03] 进项税额转出AI计算

> 税务审计 · 家族 LLM / RAG · 难度 ⭐⭐ · 优先级 medium

本方案构建一套基于ML+规则+LLM的进项税额转出AI计算平台，实现进项税额转出的智能化计算和合规管理。平台利用ML模型进行采购用途的智能分类，利用规则引擎自动匹配转出规则和计算方法，利用LLM提供政策解读和计算过程解释。方案实施后，进项税额转出的计算准确率提升至98%以上，计算效率提升90%以上，同时提供完整的计算依据和追溯证据。

## 二、技术架构设计

## 快速启动

```
python -m modules.ta_03.main          # 端口 8503
curl http://127.0.0.1:8503/api/v1/health
```

## 技术栈

ML + 规则 + LLM

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
