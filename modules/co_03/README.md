# [CO-03] 合规审计程序自动更新

> 合规审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐⭐ · 优先级 medium

合规审计程序自动更新平台通过LLM分析法规变更内容，自动识别受影响的审计程序，RAG知识库提供程序模板和最佳实践参考，规则引擎确保程序更新的一致性和完整性，将更新周期从"月"级缩短至"<1天"。系统实现法规变更→影响分析→程序更新的全自动化闭环。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_03.main          # 端口 8203
curl http://127.0.0.1:8203/api/v1/health
```

## 技术栈

LLM + 规则引擎 + RAG + 程序模板

## 依赖

- 共享平台：lsb
- 协同模块：CO-01, CO-02, CO-09

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
