# [IT-03] AI代码审计助手

> IT审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于大语言模型（LLM）+静态应用安全测试（SAST）+知识图谱的AI代码审计助手。利用LLM的深度代码理解能力实现安全漏洞检测和业务逻辑缺陷识别，通过SAST工具进行基础语法级扫描，结合知识图谱沉淀安全审计知识库，实现代码审计的智能化升级。方案实施后，代码审计效率提升80%，严重漏洞发现率提升50-80%，大幅缩短审计周期并提高审计质量。

## 二、技术架构设计

## 快速启动

```
python -m modules.it_03.main          # 端口 8303
curl http://127.0.0.1:8303/api/v1/health
```

## 技术栈

LLM + SAST + 知识图谱

## 依赖

- 共享平台：akg, lsb
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
