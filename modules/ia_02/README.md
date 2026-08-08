# [IA-02] 持续风险监控平台

> 内部审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐⭐ · 优先级 high

持续风险监控平台构建"规则引擎+ML异常检测+知识图谱关联分析"三层监控体系，对200+监控规则进行实时执行和智能优化。通过实时数据流处理企业运营数据，ML模型自动调整阈值和识别异常模式，知识图谱发现跨业务线的风险传导路径。异常事件自动分级预警，高风险事件触发即时通知和自动化处置流程，实现从"定期审计"到"持续监控"的范式转变。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_02.main          # 端口 8102
curl http://127.0.0.1:8102/api/v1/health
```

## 技术栈

规则引擎 + ML + 知识图谱 + 实时数据流

## 依赖

- 共享平台：akg
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
