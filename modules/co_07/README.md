# [CO-07] AI数据资产自动发现与分类

> 合规审计 - 数据治理 · 家族 ML / NLP · 难度 ⭐⭐⭐⭐ · 优先级 high

AI数据资产自动发现与分类平台通过数据库扫描、文件系统遍历、网络嗅探等技术自动发现企业数据资产，ML+NLP模型自动识别敏感数据类型（PII/财务/医疗/商业秘密等），元数据管理引擎建立统一的数据资产目录。预期数据资产覆盖率从30-50%提升至95%以上。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_07.main          # 端口 8207
curl http://127.0.0.1:8207/api/v1/health
```

## 技术栈

ML + NLP + 敏感数据识别 + 元数据管理

## 依赖

- 共享平台：adl
- 协同模块：CO-01, CO-08, CO-09

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
