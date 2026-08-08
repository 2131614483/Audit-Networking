# [FA-10] 知识图谱关联方发现引擎

> 财务报表审计（IPO审计、年度审计） · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐ · 优先级 high

知识图谱关联方发现引擎通过融合工商/司法/银行/合同等多源数据，构建百万级实体+千万级关系的关联方网络，利用GNN图神经网络进行3-6跳隐藏关联发现，将关联方识别完整率从60-80%提升至95%+。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.fa_10.main          # 端口 8010
curl http://127.0.0.1:8010/api/v1/health
```

## 技术栈

知识图谱 + GNN + 多源数据融合

## 依赖

- 共享平台：akg
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
