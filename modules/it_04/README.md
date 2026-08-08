# [IT-04] IT持续审计平台

> IT审计 · 家族 ML / NLP · 难度 ⭐⭐⭐⭐ · 优先级 medium

本方案构建一套基于实时数据流+机器学习+规则引擎的IT持续审计平台，实现从"年度快照式"审计到"实时持续式"审计的范式转变。平台通过Kafka实时数据流采集IT系统的配置变更、用户行为、网络流量、安全事件等关键指标，利用ML异常检测模型实时识别异常行为，结合规则引擎进行合规判定，提供统一的可视化持续审计仪表盘。方案实施后，审计模式从年度快照转变为持续监控，异常发现时间从天/周级缩短至分钟/小时级。

## 快速启动

```
python -m modules.it_04.main          # 端口 8304
curl http://127.0.0.1:8304/api/v1/health
```

## 技术栈

实时数据流 + ML + 规则引擎

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
