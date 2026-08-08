# [IA-08] 整改效果自动验证

> 内部审计 · 家族 RPA · 难度 ⭐⭐⭐ · 优先级 low

整改效果自动验证平台通过RPA自动执行验证流程、规则引擎进行客观判定、ML模型进行效果评估和趋势预测，将验证周期从"数月"缩短至"实时"。系统自动登录业务系统抓取数据，执行预定义的验证规则（控制测试/数据比对/权限检查），生成验证报告。对已验证通过的整改，系统持续监控，确保控制效果不退化。

---

## 二、技术架构设计

## 快速启动

```
python -m modules.ia_08.main          # 端口 8108
curl http://127.0.0.1:8108/api/v1/health
```

## 技术栈

RPA + ML + 规则引擎 + 数据比对

## 依赖

- 共享平台：rop
- 协同模块：IA-02, IA-06, IA-07

## 定制

见 [docs/CUSTOMIZATION.md](docs/CUSTOMIZATION.md)。核心待填点在 `src/engine.py` 的 `# TODO[rpa]:` 标记。

## 架构

见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)（提取自原方案文档）。
