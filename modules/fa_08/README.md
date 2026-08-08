# [FA-08] 底稿自动勾稽检查

> 财务报表审计（底稿复核） · 家族 Knowledge Graph / GNN · 难度 ⭐⭐ · 优先级 high

底稿自动勾稽检查方案基于200+预定义勾稽规则库（涵盖横向勾稽/纵向勾稽/计算勾稽/逻辑勾稽四大类），通过规则引擎自动执行全量勾稽验证，结合ML异常检测识别可疑勾稽差异。系统自动标记差异项、计算差异幅度、生成调整建议，检查覆盖率达100%，勾稽错误减少95%+。方案与FA-07智能底稿自动生成平台深度集成，在底稿生成的同时自动执行勾稽检查，实现"生成即检查"。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.fa_08.main          # 端口 8008
curl http://127.0.0.1:8008/api/v1/health
```

## 技术栈

规则引擎 + ML异常检测 + 知识图谱

## 依赖

- 共享平台：akg
- 协同模块：FA-02, FA-03, FA-07, FA-09

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
