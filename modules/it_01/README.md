# [IT-01] IT审计自动化平台

> IT审计 · 家族 RPA · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套以RPA（机器人流程自动化）为操作执行层、API（应用程序接口）为数据采集层、ML（机器学习）为智能分析层的三位一体IT审计自动化平台。通过自动资产发现引擎全面识别企业IT资产清单，利用100+技术栈连接器实现跨平台配置数据自动采集，结合ML驱动的配置合规检查模型实现自动化审计判定，最终将审计覆盖率从20-30%提升至95%以上，单系统审计时间从2-5天压缩至1-2小时。

## 二

## 快速启动

```
python -m modules.it_01.main          # 端口 8301
curl http://127.0.0.1:8301/api/v1/health
```

## 技术栈

RPA + API + ML

## 依赖

- 共享平台：rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[rpa]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
