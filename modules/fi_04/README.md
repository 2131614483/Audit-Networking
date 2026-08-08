# [FI-04] 监管报表智能核对平台

> 金融专项审计 · 家族 RPA · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于RPA、规则引擎和机器学习的监管报表智能核对平台。平台通过RPA自动获取报表数据，规则引擎执行勾稽关系检查，ML模型识别异常模式，实现100+报表的全自动核对和差异追踪。平台可将核对效率提升90%以上。

## 二、技术架构设计

## 快速启动

```
python -m modules.fi_04.main          # 端口 8904
curl http://127.0.0.1:8904/api/v1/health
```

## 技术栈

RPA + 规则引擎 + ML

## 依赖

- 共享平台：rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[rpa]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
