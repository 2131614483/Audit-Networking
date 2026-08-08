# [IA-07] 智能整改跟踪平台

> 内部审计 · 家族 RPA · 难度 ⭐⭐⭐ · 优先级 medium

智能整改跟踪平台通过RPA自动抓取整改状态数据、工作流引擎驱动整改流程自动化、ML模型预测整改风险和推荐最优整改方案，实现整改闭环管理。系统自动跟踪每项整改的进度，超时自动升级至更高管理层，整改完成后自动触发效果验证。预期整改完成率提升至90%以上。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_07.main          # 端口 8107
curl http://127.0.0.1:8107/api/v1/health
```

## 技术栈

RPA + 工作流引擎 + ML + 自动跟踪

## 依赖

- 共享平台：rop
- 协同模块：IA-02, IA-04, IA-05, IA-06, IA-08

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[rpa]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
