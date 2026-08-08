# [FA-03] 审计数据湖建设

> 财务报表审计 · 家族 ML / NLP · 难度 ⭐⭐⭐⭐ · 优先级 high

审计数据湖采用三区架构（原始区/标准化区/分析就绪区），基于MinIO对象存储和Apache Spark ETL引擎构建，结合Apache Atlas实现全链路元数据管理和数据血缘追踪。Delta Lake提供ACID事务和数据版本控制能力，确保数据的可追溯性和一致性。通过数据湖的建设，历史数据跨项目复用率从<20%提升至>80%，数据查询效率提升90%+，为所有AI分析方案提供统一、高效、可信的

## 快速启动

```
python -m modules.fa_03.main          # 端口 8003
curl http://127.0.0.1:8003/api/v1/health
```

## 技术栈

MinIO + Apache Spark + Apache Atlas + Delta Lake

## 依赖

- 共享平台：adl
- 协同模块：FA-01, FA-02, FA-07, FA-08, FA-09, FA-10, FA-11, FA-12

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
