# [FA-06] AI函证差异智能分析

> 财务报表审计（银行函证差异处理） · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 high

AI函证差异智能分析方案基于LLM大语言模型和NLP技术，自动识别函证差异类型（金额/账号/利率/冻结），结合知识图谱和规则引擎分析差异根因，自动生成未达账项调节表和差异处理建议。系统能够处理80%+的常见差异类型，差异分析效率提升90%，准确率>85%。对于复杂差异，AI提供根因分析和处理建议供审计师参考确认，大幅降低人工分析工作量。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.fa_06.main          # 端口 8006
curl http://127.0.0.1:8006/api/v1/health
```

## 技术栈

LLM + NLP + 知识图谱 + 规则引擎

## 依赖

- 共享平台：akg, lsb
- 协同模块：FA-03, FA-04, FA-05, FA-07

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
