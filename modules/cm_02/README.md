# [CM-02] 智能预警分级与自动处理系统

> 持续审计 · 家族 RPA · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于ML、工作流引擎和RPA的智能预警分级与自动处理系统。平台通过ML模型自动对预警进行红/黄/绿三级分级，工作流引擎驱动处理流程，RPA自动执行低风险预警的处理动作。平台可实现低风险预警自动处理率60-80%。

## 二、技术架构设计

## 快速启动

```
python -m modules.cm_02.main          # 端口 9102
curl http://127.0.0.1:9102/api/v1/health
```

## 技术栈

ML + 工作流引擎 + RPA

## 依赖

- 共享平台：rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[rpa]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
