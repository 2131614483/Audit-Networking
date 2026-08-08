# [IA-06] 内审价值量化模型

> 内部审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

内审价值量化模型基于ML和ROI计算引擎，建立多维度的审计价值量化框架。模型从直接财务价值、风险降低价值、战略价值、合规价值和预防价值五个维度综合量化审计贡献，通过Monte Carlo模拟进行区间估算，结合归因分析模型合理分配审计贡献度。实现价值量化覆盖率>90%，为审计部门提供可信的价值证明。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_06.main          # 端口 8106
curl http://127.0.0.1:8106/api/v1/health
```

## 技术栈

ML + ROI计算引擎 + 风险量化 + 财务建模

## 依赖

- 共享平台：adl
- 协同模块：IA-01, IA-04, IA-05, IA-07

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
