# [FA-02] 多源数据自动标准化

> 财务报表审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 high

多源数据自动标准化方案基于BERT-based字段名理解模型和XGBoost字段映射分类器，实现从源系统字段到标准审计数据模型的自动Schema映射。系统支持100+类字段名的自动识别与映射，科目代码通过NLP语义理解自动对齐至统一科目表。增量学习机制确保每次人工确认的映射关系自动纳入训练集，模型准确率持续提升（首月85% → 12个月后98%+）。方案与FA-01智能数据接入平台深度协同，形成"

## 快速启动

```
python -m modules.fa_02.main          # 端口 8002
curl http://127.0.0.1:8002/api/v1/health
```

## 技术栈

BERT + XGBoost + NLP + 增量学习

## 依赖

- 共享平台：adl
- 协同模块：FA-01, FA-03, FA-07, FA-08

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
