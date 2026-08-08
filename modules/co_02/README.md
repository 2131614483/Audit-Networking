# [CO-02] AI法规影响评估引擎

> 合规审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐⭐ · 优先级 high

AI法规影响评估引擎基于LLM+RAG技术，实现法规影响评估的自动化。系统通过LLM深度理解法规语义，RAG知识库提供行业对标和历史案例参考，ML模型量化评估合规成本和风险。评估效率提升90%，评估结果结构化、标准化，整改建议针对企业具体情况定制。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_02.main          # 端口 8202
curl http://127.0.0.1:8202/api/v1/health
```

## 技术栈

LLM + RAG + ML + 语义理解

## 依赖

- 共享平台：lsb
- 协同模块：CO-01, CO-03, CO-09

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
