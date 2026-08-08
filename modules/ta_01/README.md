# [TA-01] AI发票智能审计平台

> 税务审计 · 家族 Computer Vision · 难度 ⭐⭐⭐⭐ · 优先级 medium

本方案构建一套基于CV（计算机视觉）+ML+RPA+KG的AI发票智能审计平台，实现发票的全流程智能化处理。平台利用PaddleOCR微调模型和LayoutLMv3进行发票信息的高精度识别，通过ML模型进行发票分类和异常检测，利用RPA实现跨系统的四单自动匹配，通过知识图谱沉淀发票审计知识。方案实施后，发票审计效率提升90%以上，识别准确率超过99%。

## 二、技术架构设计

## 快速启动

```
python -m modules.ta_01.main          # 端口 8501
curl http://127.0.0.1:8501/api/v1/health
```

## 技术栈

CV + ML + RPA + KG

## 依赖

- 共享平台：rop
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[cv]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
