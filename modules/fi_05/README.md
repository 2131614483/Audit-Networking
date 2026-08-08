# [FI-05] AI监管口径自动更新系统

> 金融专项审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于NLP、LLM和RAG的监管口径自动更新系统。平台通过自动采集监管文件，利用NLP和LLM识别口径变化，自动生成更新建议和影响分析，实现监管口径从"周级"更新提升到"<1天"。

## 二、技术架构设计

## 快速启动

```
python -m modules.fi_05.main          # 端口 8905
curl http://127.0.0.1:8905/api/v1/health
```

## 技术栈

NLP + LLM + RAG

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
