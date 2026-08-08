# [FI-01] AI信贷资产质量评估引擎

> 金融专项审计 · 家族 ML / NLP · 难度 ⭐⭐⭐⭐ · 优先级 medium

本方案构建基于机器学习、NLP和知识图谱的AI信贷资产质量评估引擎。平台通过PD/LGD/EAD模型验证、五级分类自动校验、担保智能评估等功能，实现信贷资产质量的全面、客观、高效评估。平台可将分类准确率提升15-25%，审计效率提升80%。

## 二、技术架构设计

## 快速启动

```
python -m modules.fi_01.main          # 端口 8901
curl http://127.0.0.1:8901/api/v1/health
```

## 技术栈

ML + NLP + KG

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
