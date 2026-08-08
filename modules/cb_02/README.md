# [CB-02] 数据脱敏网关+合规路由系统

> 跨境审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建基于NLP、ML和数据分级的智能数据脱敏网关和合规路由系统。平台通过自动识别敏感数据、智能脱敏、分级路由，实现敏感数据100%识别和脱敏，确保跨境数据传输的合规性。

## 二、技术架构设计

## 快速启动

```
python -m modules.cb_02.main          # 端口 9002
curl http://127.0.0.1:9002/api/v1/health
```

## 技术栈

NLP + ML + 数据分级

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
