# [IT-02] AI配置合规扫描引擎

> IT审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于机器学习+规则引擎+CIS Benchmark的AI配置合规扫描引擎，实现IT系统配置合规的自动化、智能化检查。引擎内置CIS Benchmark、等保2.0、SOX等主流合规标准规则库，通过ML模型自动识别配置异常和漂移，结合规则引擎进行精确合规判定，提供统一的可视化合规仪表盘。方案实施后，配置检查效率可提升90%以上，显著降低人工工作量。

## 二、技术架构设计

## 快速启动

```
python -m modules.it_02.main          # 端口 8302
curl http://127.0.0.1:8302/api/v1/health
```

## 技术栈

ML + 规则引擎 + CIS Benchmark

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
