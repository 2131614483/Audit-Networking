# [IA-03] 审计资源智能分配引擎

> 内部审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

审计资源智能分配引擎基于约束优化理论，结合ML人员技能预测和遗传算法求解最优分配方案。系统综合考虑项目需求（技能/行业/复杂度/地域）、人员能力（技能评分/经验/绩效）、发展需求（培训目标/轮岗计划）和约束条件（工时上限/成本预算），实现资源匹配度提升40-50%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_03.main          # 端口 8103
curl http://127.0.0.1:8103/api/v1/health
```

## 技术栈

ML + 约束优化 + 遗传算法 + 技能匹配

## 依赖

- 共享平台：adl
- 协同模块：IA-01, IA-02, IA-04, IA-06

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
