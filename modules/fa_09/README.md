# [FA-09] AI底稿质量复核助手

> 财务报表审计（底稿复核） · 家族 LLM / RAG · 难度 ⭐⭐⭐ · 优先级 high

AI底稿质量复核助手基于NLP、ML和LLM技术，对审计底稿进行自动化的质量复核。系统从完整性、逻辑一致性、风险评估、披露充分性四个维度对每份底稿进行评分，生成复核优先级排序和复核要点提示，辅助复核人高效聚焦高风险区域。方案将复核效率提升60-70%，风险底稿识别率>90%，同时确保复核标准的统一性和全面性。与FA-08底稿自动勾稽检查形成互补——FA-08检查"数字对不对"，FA-09检查"内容

## 快速启动

```
python -m modules.fa_09.main          # 端口 8009
curl http://127.0.0.1:8009/api/v1/health
```

## 技术栈

NLP + LLM + ML + 规则引擎

## 依赖

- 共享平台：lsb
- 协同模块：FA-03, FA-07, FA-08, FA-11, FA-12

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[llm_rag]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
