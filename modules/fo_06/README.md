# [FO-06] 证据链智能构建

> 法务审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于知识图谱（KG）+时间序列+LLM的证据链智能构建平台，实现从分散证据到完整证据链的自动化构建。平台利用知识图谱技术构建证据之间的关联网络，利用时间序列分析自动生成事件时间线，利用LLM进行证据推理和完整性检查。方案实施后，证据关联发现率提升300%，证据链构建时间大幅缩短，证据完整性得到系统性保障。

## 二、技术架构设计

## 快速启动

```
python -m modules.fo_06.main          # 端口 8406
curl http://127.0.0.1:8406/api/v1/health
```

## 技术栈

KG + 时间序列 + LLM

## 依赖

- 共享平台：lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
