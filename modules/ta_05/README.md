# [TA-05] ML可比公司智能筛选

> 税务审计 · 家族 ML / NLP · 难度 ⭐⭐ · 优先级 medium

本方案构建一套基于机器学习的可比公司智能筛选引擎，实现可比公司筛选的标准化、自动化和智能化。引擎利用ML模型进行多维度相似度计算，自动完成行业分类匹配、财务指标匹配和功能风险评估，提供量化的可比性评分和推荐排名。方案实施后，可比公司筛选准确率提升30-50%，筛选时间从2-3周缩短到1-2天。

## 二、技术架构设计

## 快速启动

```
python -m modules.ta_05.main          # 端口 8505
curl http://127.0.0.1:8505/api/v1/health
```

## 技术栈

ML + 财务数据库

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
