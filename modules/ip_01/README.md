# [IP-01] IPO审计智能加速平台

> IPO审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐⭐ · 优先级 medium

本方案构建基于RPA、ML、LLM和知识图谱的IPO审计智能加速平台。平台通过全流程自动化、智能核查和多方协作功能，大幅缩短IPO审计周期。RPA机器人自动处理重复性工作，ML模型辅助财务核查，LLM支持文档智能处理，知识图谱实现关联信息快速穿透。平台可将IPO审计周期缩短50-60%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ip_01.main          # 端口 8801
curl http://127.0.0.1:8801/api/v1/health
```

## 技术栈

RPA + ML + LLM + KG

## 依赖

- 共享平台：lsb, rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
