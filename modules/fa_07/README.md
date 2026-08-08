# [FA-07] 智能底稿自动生成平台

> 财务报表审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 high

智能底稿自动生成平台通过200+标准化模板库、LLM智能分析和结论生成、RPA自动数据填入和交叉引用，将底稿编制时间从占总工时25-35%压缩至5-8%，底稿错误率降低95%+。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.fa_07.main          # 端口 8007
curl http://127.0.0.1:8007/api/v1/health
```

## 技术栈

LLM + 模板引擎 + RPA + 知识图谱

## 依赖

- 共享平台：akg, lsb, rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
