# [CO-09] 隐私合规自动审计引擎

> 合规审计 - 隐私合规 · 家族 LLM / RAG · 难度 ⭐⭐⭐⭐ · 优先级 high

隐私合规自动审计引擎通过NLP自动分析隐私政策合规性，RPA自动化DSAR处理流程，LLM进行供应商合规文档审查，规则引擎执行标准化的隐私合规检查。系统覆盖隐私审计的主要模块，预期隐私审计效率提升80%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_09.main          # 端口 8209
curl http://127.0.0.1:8209/api/v1/health
```

## 技术栈

NLP + RPA + LLM + 规则引擎

## 依赖

- 共享平台：lsb, rop
- 协同模块：CO-01, CO-03, CO-07, CO-08

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
