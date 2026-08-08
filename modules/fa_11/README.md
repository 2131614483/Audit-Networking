# [FA-11] 关联交易定价公允性AI分析

> 财务报表审计（关联交易审计） · 家族 ML / NLP · 难度 ⭐⭐⭐⭐ · 优先级 high

关联交易定价公允性AI分析方案基于ML模型和行业数据库，采用四种互补的分析方法（内部比较法/外部比较法/转移定价调整法/时间序列异常检测），对关联交易定价进行全面、系统的公允性评估。方案自动从行业数据库获取可比交易数据，利用NLP技术解析交易合同中的定价条款，结合ML模型识别异常定价模式。分析效率提升85%，异常发现率较手工提升200-400%，有效支撑审计师对关联交易定价公允性的专业判断。

-

## 快速启动

```
python -m modules.fa_11.main          # 端口 8011
curl http://127.0.0.1:8011/api/v1/health
```

## 技术栈

ML + 行业数据库 + NLP + 时间序列分析

## 依赖

- 共享平台：adl
- 协同模块：FA-03, FA-07, FA-10, FA-12

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
