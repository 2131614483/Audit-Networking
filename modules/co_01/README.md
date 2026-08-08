# [CO-01] 全球法规智能监控平台

> 合规审计 · 家族 Knowledge Graph / GNN · 难度 ⭐⭐⭐⭐⭐ · 优先级 high

全球法规智能监控平台通过分布式爬虫系统实时采集200+国家和地区的法规发布信息，NLP模型进行多语言法规文本理解和分类，LLM进行法规影响自动评估，RAG知识库存储法规全文和解读。平台实现法规感知从"月"级提升至"<24小时"，覆盖200+国家和地区的监管动态，自动识别与企业相关的法规变更并推送至相关合规人员。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.co_01.main          # 端口 8201
curl http://127.0.0.1:8201/api/v1/health
```

## 技术栈

NLP + LLM + RAG + 知识图谱 + 爬虫

## 依赖

- 共享平台：akg, lsb
- 协同模块：CO-02, CO-03, CO-07, CO-08, CO-09

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[kg_gnn]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
