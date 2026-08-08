# [IT-05] 区块链审计日志存证

> IT审计 · 家族 Blockchain · 难度 ⭐⭐⭐ · 优先级 medium

本方案构建一套基于区块链技术的审计日志存证平台，将审计日志的摘要哈希值上链存储，利用区块链的不可篡改性和去中心化共识机制保障审计证据的完整性和可信性。平台支持审计日志的实时摘要上链、数字签名验证、完整性校验和证据链追溯，确保审计证据从产生、存储到验证的全生命周期可信。方案实施后，审计证据完整性达到100%保证，审计证据的可信度和法律效力得到根本性提升。

## 二、技术架构设计

## 快速启动

```
python -m modules.it_05.main          # 端口 8305
curl http://127.0.0.1:8305/api/v1/health
```

## 技术栈

区块链 + 不可篡改存储

## 依赖

- 共享平台：bce
- 协同模块：无

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[blockchain]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
