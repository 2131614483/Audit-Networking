# [FA-12] 关联交易披露完整性检查

> 财务报表审计（关联交易披露复核） · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐ · 优先级 high

关联交易披露完整性检查方案基于NLP语义比对技术和规则引擎，将监管要求清单化、结构化（100+检查项），自动扫描财务报表附注中的关联交易披露内容，逐项检查披露完整性。LLM模型自动识别披露缺陷并生成补充建议。方案与FA-10关联方发现引擎和FA-11定价分析深度集成，确保发现的关联交易全部被完整披露。披露遗漏率降低90%+，检查覆盖率达100%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.fa_12.main          # 端口 8012
curl http://127.0.0.1:8012/api/v1/health
```

## 技术栈

NLP + 规则引擎 + LLM + 知识图谱

## 依赖

- 共享平台：akg, lsb
- 协同模块：FA-03, FA-09, FA-10, FA-11

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
