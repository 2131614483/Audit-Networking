# [SC-03] 供应商持续风险监控平台

> 供应链审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于实时数据流、机器学习和自然语言处理的供应商持续风险监控平台。通过7×24小时自动采集舆情、司法、财务、合规等多维数据，利用ML模型实时分析风险信号，NLP引擎自动理解风险事件内容，实现供应商风险的实时感知、智能预警和自动处置。将风险感知从传统的年度/季度频率提升到实时级别，显著缩短风险发现到处置的时间窗口。

## 二、技术架构设计

## 快速启动

```
python -m modules.sc_03.main          # 端口 8603
curl http://127.0.0.1:8603/api/v1/health
```

## 技术栈

实时数据流 + ML + NLP

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
