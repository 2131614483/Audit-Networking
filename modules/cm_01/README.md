# [CM-01] 持续审计技术平台

> 持续审计 · 家族 Streaming · 难度 ⭐⭐⭐⭐ · 优先级 medium

本方案构建基于实时流处理、机器学习和规则引擎的持续审计技术平台。通过Kafka实时数据流接入、Flink流处理、ML模型实时分析和规则引擎自动检查，实现7×24小时的持续审计能力，将审计从"事后追查"转变为"实时监控"。

## 二、技术架构设计

## 快速启动

```
python -m modules.cm_01.main          # 端口 9101
curl http://127.0.0.1:9101/api/v1/health
```

## 技术栈

实时流处理 + ML + 规则引擎

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[streaming]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
