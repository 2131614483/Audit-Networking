# [CO-04] AML智能交易监控引擎

> 合规审计 - 反洗钱 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐⭐ · 优先级 high

AML智能交易监控引擎采用三层架构：第一层规则引擎快速过滤已知洗钱模式；第二层ML异常检测发现偏离正常行为的交易；第三层GNN（图神经网络）分析交易网络中的隐蔽洗钱网络。XAI（可解释AI）技术确保每笔告警都有清晰的解释。预期将误报率从90-95%降至40-60%，真实威胁发现率提升20-35%。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_04.main          # 端口 8204
curl http://127.0.0.1:8204/api/v1/health
```

## 技术栈

GNN + ML + XAI + 规则引擎

## 依赖

- 共享平台：akg
- 协同模块：CO-05, CO-06, IA-02

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
