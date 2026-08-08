# [FA-05] 区块链银行函证

> 财务报表审计（银行函证程序） · 家族 Blockchain · 难度 ⭐⭐⭐⭐ · 优先级 high

区块链银行函证方案基于Hyperledger Fabric联盟链构建，审计师通过智能合约发起函证请求，银行节点自动查询账户数据并生成数字签名回函，全程上链存证、不可篡改。方案支持与银行核心系统API直连，回函数据由银行系统自动生成并数字签名，确保函证数据的真实性和完整性。通过区块链函证，回函周期从7-15天压缩至<1天（API直连银行可达实时），函证真实性100%可验证，函证覆盖率提升至100%。

## 快速启动

```
python -m modules.fa_05.main          # 端口 8005
curl http://127.0.0.1:8005/api/v1/health
```

## 技术栈

Hyperledger Fabric + 智能合约 + 数字签名 + 银行API

## 依赖

- 共享平台：adl
- 协同模块：FA-03, FA-04, FA-06, FA-07

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[blockchain]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
