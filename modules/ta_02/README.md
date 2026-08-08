# [TA-02] 发票四单自动匹配引擎

> 税务审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于ML+NLP+规则的发票四单自动匹配引擎，实现采购订单（PO）、入库单（GR）、发票（Invoice）、付款单（Payment）的四维智能匹配。引擎利用ML模型进行智能匹配决策和异常处理推荐，利用NLP技术处理非结构化单据描述信息的匹配，利用规则引擎处理标准化匹配逻辑。方案实施后，匹配准确率超过98%，匹配效率提升90%以上。

## 二、技术架构设计

## 快速启动

```
python -m modules.ta_02.main          # 端口 8502
curl http://127.0.0.1:8502/api/v1/health
```

## 技术栈

ML + NLP + 规则

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
