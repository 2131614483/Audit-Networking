# [ES-03] 卫星遥感AI环境监测平台

> ESG审计 · 家族 Computer Vision · 难度 ⭐⭐⭐⭐ · 优先级 medium

本方案构建基于卫星遥感和计算机视觉的AI环境监测平台。通过接入Sentinel-2、PlanetScope等多源卫星数据，利用CV模型进行土地利用变化检测、水体监测、植被健康评估、大气污染物监测等，为ESG审计提供独立、客观、可追溯的环境数据验证能力。平台可发现企业环境声明与实际情况的偏差，将绿色漂洗发现率提升50-70%。

## 二、技术架构设计

## 快速启动

```
python -m modules.es_03.main          # 端口 8703
curl http://127.0.0.1:8703/api/v1/health
```

## 技术栈

CV + 卫星遥感 + ML

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[cv]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
