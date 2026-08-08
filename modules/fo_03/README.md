# [FO-03] NLP文本舞弊信号检测

> 法务审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于NLP+LLM+情感分析的文本舞弊信号检测平台，对企业内部海量非结构化文本数据进行系统性分析。平台利用NLP技术进行异常关键词发现和主题建模，利用LLM进行深度语义理解和隐含意图识别，结合情感分析检测文本中的情感不一致信号，全面捕捉文本中蕴含的舞弊线索。方案实施后，文本舞弊信号发现率提升200%，大幅提升法务审计对非结构化数据的利用能力。

## 二、技术架构设计

## 快速启动

```
python -m modules.fo_03.main          # 端口 8403
curl http://127.0.0.1:8403/api/v1/health
```

## 技术栈

NLP + LLM + 情感分析

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
