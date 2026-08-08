# [IA-01] 动态风险地图与智能审计计划

> 内部审计 · 家族 LLM / RAG · 难度 ⭐⭐⭐⭐⭐ · 优先级 high

动态风险地图与智能审计计划平台通过ML模型（XGBoost）对100+持续计算的指标进行实时风险评分，结合NLP技术处理内外部文本数据（新闻、监管公告、社交媒体、内部报告），实现风险从"数月感知"到"<24小时感知"的飞跃。LLM引擎将风险评分结果、资源约束、历史审计覆盖等多维信息整合，自动生成最优审计计划草案，风险识别准确率提升30-40%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_01.main          # 端口 8101
curl http://127.0.0.1:8101/api/v1/health
```

## 技术栈

ML + NLP + 实时数据流 + LLM

## 依赖

- 共享平台：lsb
- 协同模块：CO-01, IA-02, IA-03, IA-04, IA-06

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
