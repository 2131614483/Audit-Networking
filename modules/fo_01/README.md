# [FO-01] 全量交易智能舞弊扫描

> 法务审计 · 家族 ML / NLP · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于机器学习+Benford定律+无监督学习的四层全量交易舞弊扫描模型，对企业的全量交易数据进行系统性扫描。第一层（统计层）采用Benford定律、异常值检测等统计方法进行初筛；第二层（无监督ML层）采用Isolation Forest、Autoencoder等无监督算法发现未知异常模式；第三层（监督ML层）基于历史舞弊案例训练分类模型，识别已知舞弊模式；第四层（知识图谱层）构建交易

## 快速启动

```
python -m modules.fo_01.main          # 端口 8401
curl http://127.0.0.1:8401/api/v1/health
```

## 技术栈

ML + Benford + 无监督学习

## 依赖

- 共享平台：adl
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[ml_nlp]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
