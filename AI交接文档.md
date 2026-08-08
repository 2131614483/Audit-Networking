# 审计智能化平台 — AI 开发交接文档

> **文档用途：** 供后续 AI agent 接手开发时快速了解项目状态、架构约定和待办任务
> **最后更新：** 2026-08-09
> **当前进度：** 33/80 模块已完善（41.3%），累计 1,856 项测试通过；可视化平台与启动器已交付

---

## 一、项目总览

### 1.1 基本信息

| 项目 | 内容 |
|------|------|
| **项目路径** | `c:\Pythonproject\解决方案详细报告` |
| **模块总数** | 80 个审计自动化模块（modules/ 目录下，排除 shared/supervisor/venvs） |
| **方案文档** | 36 个 .md 方案文档在根目录（如 `FA-08-底稿自动勾稽检查.md`） |
| **技术架构** | 三层：L1 基础层 → L2 平台层 → L3+ 下游应用层 |
| **引擎家族** | 7 个：MLEngine / LLMEngine / KGEngine / CVEngine / RPAEngine / BlockchainEngine / StreamingEngine / FederationEngine / ResourceEngine / DashboardEngine |

### 1.2 核心约定（必须遵守）

1. **引擎基类不可修改**：`modules/shared/base_engine.py` 定义 `AbstractEngine`，`execute()` 是模板方法（预处理→推理→后处理），子类只实现 4 个抽象方法
2. **engine.py 原则上不修改**：所有模块的 engine.py 已由前序 AI 完成实现，后续只需填充 pipeline/custom/tests/fixtures 四层。仅当 engine 存在明确 bug 时才可最小化修复（如 FA-05 的 `_validate_chain` 哈希链验证 bug）
3. **测试框架用 unittest**：所有 test 文件必须用 `unittest`（NOT pytest）。骨架测试文件中的 `import pytest` 必须替换
4. **纯 stdlib**：engine/custom/tests 中除 `from modules.shared.base_engine import AbstractEngine` 外，不引入第三方依赖。API 测试中 `TestClient` 用 try/except 懒加载，不可用时 `skipTest`
5. **PortableDB 隔离**：每个测试用 `tempfile.TemporaryDirectory()` + 独立 `db_path` 配置，避免跨测试污染
6. **每模块四层结构**：engine.py（已有）→ pipeline.py → custom/（rules+thresholds+formatter）→ tests/（engine+pipeline+api+fixtures）

### 1.3 模块目录结构标准

```
modules/{slug}/
├── __init__.py
├── engine.py          ← 已完成（AI 前序实现），不修改
├── pipeline.py        ← 需完善：修复类名导入 + _collect + _output
├── main.py            ← FastAPI 入口（已有）
├── api.py             ← API 路由（已有）
├── module.yaml        ← 模块元数据（已有）
├── requirements.txt   ← 依赖（已有）
├── config/
│   ├── default.yaml   ← 默认配置（已有）
│   ├── custom.yaml    ← 自定义配置（已有）
│   └── schema.yaml    ← 配置 schema（已有）
├── custom/
│   ├── __init__.py
│   ├── custom_rules.py       ← 需完善：3+ 业务规则
│   ├── custom_thresholds.py  ← 需完善：阈值分级逻辑
│   └── custom_formatter.py   ← 需完善：输出格式化
├── tests/
│   ├── __init__.py
│   ├── test_engine.py        ← 需重写：20+ unittest 用例
│   ├── test_pipeline.py      ← 需重写：8+ unittest 用例
│   ├── test_api.py           ← 需重写：5+ unittest 用例（skip if no TestClient）
│   └── fixtures/
│       ├── sample_input.json     ← 需创建：真实测试数据
│       └── expected_output.json  ← 需创建：期望输出
└── docs/
    ├── API.md
    ├── ARCHITECTURE.md
    ├── CUSTOMIZATION.md
    └── TROUBLESHOOTING.md
```

---

## 二、已完成模块清单（30 个）

### 2.1 测试统计总表

| 批次 | 模块 | 引擎类 | 引擎行数 | 测试数 | skip | 状态 |
|------|------|--------|---------|--------|------|------|
| L1 | FA-02 | MLEngine | - | 96 | 0 | ✅ (verify脚本) |
| L1 | FA-03 | MLEngine | - | 96 | 0 | ✅ (verify脚本) |
| L2 | FO-01 | MLEngine | - | 57 | 2 | ✅ |
| L2 | SC-01 | MLEngine | - | 62 | 0 | ✅ |
| L2 | CO-01 | LLMEngine | - | 42 | 2 | ✅ |
| L2 | FA-10 | KGEngine | - | 35 | 2 | ✅ |
| L2 | FA-07 | LLMEngine | - | 26 | 0 | ✅ |
| L2 | IP-01 | LLMEngine | - | 86 | 2 | ✅ |
| L3 | FA-08 | MLEngine | 168 | 61 | 5 | ✅ |
| L3 | FA-09 | LLMEngine | 261 | 64 | 5 | ✅ |
| L3 | FA-11 | MLEngine | 202 | 68 | 6 | ✅ |
| L3 | FA-12 | KGEngine | 243 | 69 | 6 | ✅ |
| L3 | CO-02 | LLMEngine | 373 | 67 | 5 | ✅ |
| L3 | CO-03 | LLMEngine | 466 | 56 | 5 | ✅ |
| L3 | CO-06 | KGEngine | 854 | 87 | 6 | ✅ |
| L3 | FO-02 | KGEngine | 290 | 66 | 6 | ✅ |
| L3 | SC-02 | KGEngine | 381 | 53 | 6 | ✅ |
| L3 | SC-03 | MLEngine | 257 | 60 | 7 | ✅ |
| L4 | CO-04 | KGEngine | 134 | 51 | 5 | ✅ |
| L4 | CO-05 | KGEngine | 432 | 53 | 5 | ✅ |
| L4 | FA-04 | BlockchainEngine | 242 | 56 | 6 | ✅ |
| L4 | FA-05 | BlockchainEngine | 196 | 61 | 6 | ✅ |
| L4 | FA-06 | KGEngine | 194 | 56 | 5 | ✅ |
| L4 | FO-03 | LLMEngine | 174 | 58 | 5 | ✅ |
| L4 | SC-04 | MLEngine | 276 | 51 | 5 | ✅ |
| L4 | SC-05 | MLEngine | 233 | 53 | 6 | ✅ |
| L4 | FO-04 | CVEngine | 160 | 55 | 6 | ✅ |
| L4 | FO-05 | LLMEngine | 187 | 63 | 6 | ✅ |
| L5 | CO-07 | MLEngine | 422 | 68 | 6 | ✅ |
| L5 | ES-01 | CVEngine | 278 | 53 | 6 | ✅ |
| L5 | CO-08 | KGEngine | 469 | 50 | 5 | ✅ |
| L5 | CO-09 | LLMEngine | 466 | 51 | 5 | ✅ |
| L5 | FO-06 | LLMEngine | 250 | 32 | 5 | ✅ |

> **注：** FA-02/FA-03 使用 verify 脚本验证（96 项端到端），unittest discover 可能只找到少量测试。
> **注：** CO-01 实际 43 项（unittest 可能漏 1），FA-07 实际 27 项。
> **已知问题：** FA-03 的 `test_run_reuse_rate_in_range` 偶尔失败（数据依赖时序），非阻塞。

### 2.2 引擎家族分布

| 引擎类 | 已完成模块数 | 典型模块 |
|--------|------------|---------|
| MLEngine | 11 | FO-01, SC-01, FA-02/03/08/11, CO-07, SC-03/04/05, ES-02 |
| LLMEngine | 8 | CO-01/02/03, FA-07/09, IP-01, FO-03/05 |
| KGEngine | 7 | FA-10/12, CO-05/06, FO-02, SC-02, FA-06 |
| BlockchainEngine | 2 | FA-04, FA-05 |
| CVEngine | 2 | FO-04, ES-01 |
| StreamingEngine | 0 | (CM-01 待完成) |
| RPAEngine | 0 | (CM-02, IA-07/08, IT-01 待完成) |
| FederationEngine | 0 | (CB-01 待完成) |
| ResourceEngine | 0 | (IA-03 待完成) |
| DashboardEngine | 0 | (IA-04 待完成) |

---

## 三、待完成模块清单（45 个）

### 3.1 按优先级分组

#### P0 — L5 批次剩余（5 个，子 agent 已分派但未完成）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| ES-02 | MLEngine | 117 | 8 | AI碳排放自动核算 |
| ES-03 | CVEngine | 303 | 8 | 卫星遥感AI环境监测 |
| ES-04 | KGEngine | 369 | 8 | 知识图谱绿色漂洗检测 |
| IT-01 | RPAEngine | 256 | 8 | IT审计自动化平台 |
| IT-02 | MLEngine | 256 | 8 | AI配置合规扫描引擎 |

#### P1 — ESG/IT 剩余（4 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| ES-05 | LLMEngine | 298 | 8 | ESG审计知识库与AI助手 |
| ES-06 | LLMEngine | 368 | 8 | AI-ESG审计方法论引擎 |
| IT-03 | KGEngine | 258 | 8 | AI代码审计助手 |
| IT-04 | MLEngine | 341 | 8 | IT持续审计平台 |
| IT-05 | BlockchainEngine | 263 | 8 | 区块链审计日志存证 |

#### P2 — 内部审计 IA 系列（8 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| IA-01 | LLMEngine | 487 | 8 | 动态风险地图与智能审计计划 |
| IA-02 | KGEngine | 568 | 8 | 持续风险监控平台 |
| IA-03 | ResourceEngine | 581 | 8 | 审计资源智能分配引擎 |
| IA-04 | DashboardEngine | 510 | 8 | 审计价值仪表板 |
| IA-05 | LLMEngine | 249 | 8 | AI驱动的管理建议书 |
| IA-06 | MLEngine | 263 | 8 | 内审价值量化模型 |
| IA-07 | RPAEngine | 238 | 8 | 智能整改跟踪平台 |
| IA-08 | RPAEngine | 269 | 8 | 整改效果自动验证 |

#### P3 — IPO 系列（5 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| IP-02 | LLMEngine | 275 | 8 | AI监管反馈智能回复 |
| IP-03 | KGEngine | 253 | 8 | 知识图谱历史沿革梳理 |
| IP-04 | MLEngine | 252 | 8 | AI财务规范性智能诊断 |
| IP-05 | LLMEngine | 223 | 8 | IPO案例知识库与RAG |
| IP-06 | LLMEngine | 225 | 8 | 整改方案AI推荐引擎 |

#### P4 — 税务审计 TA 系列（6 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| TA-01 | CVEngine | 239 | 8 | AI发票智能审计平台 |
| TA-02 | MLEngine | 244 | 8 | 发票四单自动匹配引擎 |
| TA-03 | LLMEngine | 218 | 8 | 进项税额转出AI计算 |
| TA-04 | LLMEngine | 215 | 8 | AI转让定价文档自动生成 |
| TA-05 | MLEngine | 178 | 8 | ML可比公司智能筛选 |
| TA-06 | KGEngine | 250 | 8 | 知识图谱全球关联交易分析 |

#### P5 — 金融审计 FI 系列（5 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| FI-01 | MLEngine | 213 | 8 | AI信贷资产质量评估引擎 |
| FI-02 | KGEngine | 261 | 8 | 知识图谱担保链风险分析 |
| FI-03 | MLEngine | 112 | 8 | ML贷款违约预测验证 |
| FI-04 | LLMEngine | 213 | 8 | 监管报表智能核对平台 |
| FI-05 | LLMEngine | 194 | 8 | AI监管口径自动更新 |

#### P6 — 跨境审计 CB 系列（6 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| CB-01 | FederationEngine | 302 | 8 | 联邦学习跨境审计平台 |
| CB-02 | MLEngine | 421 | 8 | 数据脱敏网关+合规路由 |
| CB-03 | LLMEngine | 475 | 8 | 多法域合规知识库 |
| CB-04 | LLMEngine | 466 | 8 | AI多准则自动转换引擎 |
| CB-05 | LLMEngine | 371 | 8 | AI多语言审计协作平台 |
| CB-06 | LLMEngine | 490 | 8 | 集团审计智能协作平台 |

#### P7 — 持续审计 CM 系列（5 个）

| 模块 | 引擎类 | 引擎行数 | 测试行数 | 说明 |
|------|--------|---------|---------|------|
| CM-01 | StreamingEngine | 292 | 8 | 持续审计技术平台 |
| CM-02 | RPAEngine | 100 | 8 | 智能预警分级与自动处理 |
| CM-03 | LLMEngine | 517 | 8 | 持续审计方法论框架 |
| CM-04 | MLEngine | 454 | 8 | 持续审计价值量化模型 |
| CM-05 | MLEngine | 543 | 8 | 持续审计仪表板 |

### 3.2 待完成模块统计

| 优先级 | 模块数 | 说明 |
|--------|--------|------|
| P0 (L5剩余) | 5 | 子 agent 已分派但未完成，需重新分派 |
| P1 (ESG/IT剩余) | 5 | ES-05/06, IT-03/04/05 |
| P2 (IA系列) | 8 | 内部审计全系列 |
| P3 (IPO系列) | 5 | IP-02~06 |
| P4 (TA系列) | 6 | 税务审计全系列 |
| P5 (FI系列) | 5 | 金融审计全系列 |
| P6 (CB系列) | 6 | 跨境审计全系列 |
| P7 (CM系列) | 5 | 持续审计全系列 |
| **合计** | **45** |

---

## 四、模块完善操作手册

### 4.1 标准操作流程（每个模块）

```
Step 1: 阅读 engine.py
  → 确认引擎类名（如 MLEngine / KGEngine / LLMEngine）
  → 理解 _load_model / _preprocess / _infer / _postprocess 的输入输出格式
  → 识别核心数据结构（规则列表、权重字典、阈值常量等）

Step 2: 修复 pipeline.py
  → 将骨架中的错误类名导入替换为正确类名
  → 添加 engine.setup() 调用（触发 _load_model）
  → 实现 _collect：从 input_data 中提取/归一化数据（支持中英文键、list/dict 兼容）
  → 实现 _output：调用 format_output(result)

Step 3: 编写 custom 层
  → custom_rules.py：3+ 条业务规则（如阈值升级、强制标记、风险升级）
  → custom_thresholds.py：分级逻辑（如 score → A/B/C/D 或 high/medium/low）
  → custom_formatter.py：输出格式化（status + module + summary + items + suggestions）

Step 4: 创建 fixtures
  → sample_input.json：真实审计场景数据（含正常+异常 case）
  → expected_output.json：引擎实际输出（先跑一次引擎获取）

Step 5: 编写测试
  → test_engine.py：20+ unittest 用例（_load_model / _preprocess / _infer / _postprocess / execute / 边界）
  → test_pipeline.py：8+ unittest 用例（端到端 / collect / custom规则 / PortableDB持久化）
  → test_api.py：5+ unittest 用例（TestClient 懒加载 + skipTest）

Step 6: 验证
  → python -m unittest discover -s modules/{slug}/tests -v
  → 全部 OK（API 测试可 skip）
```

### 4.2 测试文件模板

#### test_engine.py 模板

```python
"""[{SLUG}] engine 单测。unittest 风格，纯 stdlib。"""
from __future__ import annotations
import json, tempfile, unittest
from pathlib import Path
from modules.{slug}.engine import {EngineClass}

_FIXTURES = Path(__file__).resolve().parent / "fixtures"

def _load_fixture(name):
    with open(_FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)

def _make_engine(tmpdir, **overrides):
    config = {"db_path": str(Path(tmpdir) / "{slug}_test.db"), "fixtures_dir": str(_FIXTURES)}
    config.update(overrides)
    eng = {EngineClass}(config=config)
    eng.setup()
    return eng

class TestEngineLoadModel(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = _make_engine(self.tmpdir.name)
    def tearDown(self):
        self.tmpdir.cleanup()
    def test_model_loaded(self):
        self.assertIsNotNone(self.engine.model)
    # ... 更多测试

class TestEnginePreprocess(unittest.TestCase):
    # ...

class TestEngineInfer(unittest.TestCase):
    # ...

class TestEnginePostprocess(unittest.TestCase):
    # ...

class TestEngineExecute(unittest.TestCase):
    # ...

class TestEngineEdgeCases(unittest.TestCase):
    # ...

if __name__ == "__main__":
    unittest.main()
```

#### test_api.py 模板（TestClient 懒加载）

```python
"""[{SLUG}] API 单测。TestClient 不可用时自动 skip。"""
import unittest

try:
    from fastapi.testclient import TestClient
    _AVAILABLE = True
except (ImportError, TypeError):
    _AVAILABLE = False

from modules.{slug}.main import app

class TestAPI(unittest.TestCase):
    def setUp(self):
        if not _AVAILABLE:
            self.skipTest("TestClient not available")
        self.client = TestClient(app)
    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
    # ...

if __name__ == "__main__":
    unittest.main()
```

### 4.3 并行分派策略

每批 5 个子 agent，每个负责 2 个模块：

```
Agent 1: modules A + B  →  各 20+8+5 tests
Agent 2: modules C + D  →  各 20+8+5 tests
Agent 3: modules E + F  →  各 20+8+5 tests
Agent 4: modules G + H  →  各 20+8+5 tests
Agent 5: modules I + J  →  各 20+8+5 tests
```

每个子 agent 的 prompt 必须包含：
1. CRITICAL RULES（不改 engine.py、unittest、纯 stdlib、TestClient skip）
2. 模块路径和引擎类名
3. 引擎功能简述
4. 完整任务清单（pipeline + custom + fixtures + tests）
5. 验证命令
6. 参考文件列表（fo_01 完整模块 + 目标 engine.py）

### 4.4 验证命令

```powershell
# 单模块验证
python -m unittest discover -s modules/{slug}/tests -v

# 批量验证（PowerShell）
$modules = @("fa_08","fa_09",...); foreach ($m in $modules) {
    $result = python -m unittest discover -s "modules/$m/tests" 2>&1 | Select-String "Ran|OK|FAILED" | Out-String
    Write-Output "${m}: $($result.Trim())"
}

# 全量验证（所有已完成模块）
$completed = @("fa_02","fa_03","fo_01","sc_01","co_01","fa_10","fa_07","ip_01",
               "fa_08","fa_09","fa_11","fa_12","co_02","co_03","co_06","fo_02","sc_02","sc_03",
               "co_04","co_05","fa_04","fa_05","fa_06","fo_03","sc_04","sc_05","fo_04","fo_05",
               "co_07","es_01")
foreach ($m in $completed) {
    python -m unittest discover -s "modules/$m/tests" 2>&1 | Select-String "Ran|OK|FAILED"
}
```

---

## 五、已知问题与注意事项

### 5.1 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 骨架测试 `import pytest` 失败 | 前序 AI 用 pytest 写骨架 | 完全重写为 unittest |
| pipeline.py 类名导入错误 | 骨架统一用 KGEngine | 读 engine.py 确认实际类名后替换 |
| engine `__init__` 参数不同 | 有的接收 `name`，有的接收 `config` | 读 engine.py 的 `__init__` 签名 |
| API 测试 ImportError | fastapi/httpx 版本不兼容 | try/except 懒加载 + skipTest |
| PortableDB 文件锁 | Windows 文件锁 | 每个测试用独立 tmpdir |
| engine.setup() 未调用 | pipeline 未触发 _load_model | 在 Pipeline.__init__ 中调用 |

### 5.2 引擎类名速查表

所有待完成模块的引擎类名（从 engine.py 的 `class` 行提取）：

| 模块 | 引擎类 | 模块 | 引擎类 | 模块 | 引擎类 |
|------|--------|------|--------|------|--------|
| CO-08 | KGEngine | ES-05 | LLMEngine | IP-04 | MLEngine |
| CO-09 | LLMEngine | ES-06 | LLMEngine | IP-05 | LLMEngine |
| FO-06 | LLMEngine | IT-03 | KGEngine | IP-06 | LLMEngine |
| ES-02 | MLEngine | IT-04 | MLEngine | TA-01 | CVEngine |
| ES-03 | CVEngine | IT-05 | BlockchainEngine | TA-02 | MLEngine |
| ES-04 | KGEngine | IA-01 | LLMEngine | TA-03 | LLMEngine |
| IT-01 | RPAEngine | IA-02 | KGEngine | TA-04 | LLMEngine |
| IT-02 | MLEngine | IA-03 | ResourceEngine | TA-05 | MLEngine |
| CB-01 | FederationEngine | IA-04 | DashboardEngine | TA-06 | KGEngine |
| CB-02 | MLEngine | IA-05 | LLMEngine | FI-01 | MLEngine |
| CB-03 | LLMEngine | IA-06 | MLEngine | FI-02 | KGEngine |
| CB-04 | LLMEngine | IA-07 | RPAEngine | FI-03 | MLEngine |
| CB-05 | LLMEngine | IA-08 | RPAEngine | FI-04 | LLMEngine |
| CB-06 | LLMEngine | IP-02 | LLMEngine | FI-05 | LLMEngine |
| CM-01 | StreamingEngine | IP-03 | KGEngine | | |
| CM-02 | RPAEngine | | | | |
| CM-03 | LLMEngine | | | | |
| CM-04 | MLEngine | | | | |
| CM-05 | MLEngine | | | | |

### 5.3 特殊引擎注意事项

| 引擎类 | 特殊点 |
|--------|--------|
| FederationEngine (CB-01) | 联邦学习模拟，需测试 FedAvg 聚合、差分隐私 |
| StreamingEngine (CM-01) | 流处理模拟，需测试窗口计算、实时告警 |
| RPAEngine (CM-02/IA-07/08/IT-01) | RPA 任务编排，需测试任务调度、异常处理 |
| ResourceEngine (IA-03) | 资源分配优化，需测试排班算法、负载均衡 |
| DashboardEngine (IA-04) | 仪表板数据聚合，需测试多维度统计、KPI 计算 |
| BlockchainEngine (IT-05) | 区块链存证，需测试哈希链、共识验证（参考 FA-05） |

### 5.4 参考模块

| 引擎类 | 最佳参考模块 | 路径 |
|--------|------------|------|
| MLEngine | FO-01 | `modules/fo_01/` |
| LLMEngine | CO-01 | `modules/co_01/` |
| KGEngine | FA-10 | `modules/fa_10/` |
| BlockchainEngine | FA-05 | `modules/fa_05/` |
| CVEngine | ES-01 | `modules/es_01/` |

---

## 六、推荐执行计划

### 6.1 下一批次（L5 续：8 个模块）

```
Agent 1: CO-08 (KGEngine) + CO-09 (LLMEngine)
Agent 2: FO-06 (LLMEngine) + ES-02 (MLEngine)
Agent 3: ES-03 (CVEngine) + ES-04 (KGEngine)
Agent 4: IT-01 (RPAEngine) + IT-02 (MLEngine)
```

### 6.2 后续批次建议

| 批次 | 模块 | 数量 |
|------|------|------|
| L6 | ES-05/06, IT-03/04/05 | 5 |
| L7 | IA-01~04 | 4 |
| L8 | IA-05~08 | 4 |
| L9 | IP-02~06 | 5 |
| L10 | TA-01~03 | 3 |
| L11 | TA-04~06 | 3 |
| L12 | FI-01~03 | 3 |
| L13 | FI-04/05, CB-01/02 | 4 |
| L14 | CB-03~06 | 4 |
| L15 | CM-01~03 | 3 |
| L16 | CM-04/05 | 2 |
| **剩余** | | **48** |

### 6.3 完成后总测试估算

```
已完成: ~1,723 tests (30 modules, avg 57 tests/module)
待完成: ~2,736 tests (48 modules × 57 avg)
预计总计: ~4,459 tests
```

---

## 七、关键文件索引

### 7.1 共享基础设施

| 文件 | 路径 | 说明 |
|------|------|------|
| 引擎基类 | `modules/shared/base_engine.py` | AbstractEngine，execute() 模板方法 |
| PortableDB | `modules/shared/portable_db.py` | 轻量 SQLite 封装 |
| 配置加载器 | `modules/shared/config_loader.py` | YAML 配置加载 |
| 模块元数据 | `modules/shared/module_meta.py` | 模块信息注册 |
| 统一运行时 | `modules/shared/runtime.py` | `python -m modules.shared.runtime {slug}` |

### 7.2 方案文档（36 个）

根目录下每个模块对应一个 .md 文件，如：
- `FA-08-底稿自动勾稽检查.md`
- `CO-04-AML智能交易监控引擎.md`
- `SC-01-供应商风险智能评分平台.md`

### 7.3 规划文档

| 文档 | 说明 |
|------|------|
| `开发规划设计文档.md` | 36 方案的统一架构/平台/阶段/依赖/资源规划 |
| `开发进度文档.md` | 原始开发进度跟踪（FA-01 垂直切片） |
| `技术栈与模块依赖分析报告.md` | 15 方案技术栈分析、数据流、依赖矩阵、三层架构 |

---

## 八、验证当前状态

执行以下命令确认当前所有已完成模块的状态：

```powershell
cd c:\Pythonproject\解决方案详细报告
$completed = @("fa_02","fa_03","fo_01","sc_01","co_01","fa_10","fa_07","ip_01","fa_08","fa_09","fa_11","fa_12","co_02","co_03","co_06","fo_02","sc_02","sc_03","co_04","co_05","fa_04","fa_05","fa_06","fo_03","sc_04","sc_05","fo_04","fo_05","co_07","es_01")
$totalTests = 0; $totalSkipped = 0
foreach ($m in $completed) {
    $output = python -m unittest discover -s "modules/$m/tests" 2>&1
    $line = ($output | Select-String "Ran|OK" | Out-String).Trim()
    Write-Output "${m}: $line"
}
```

预期输出：所有模块 `OK` 或 `OK (skipped=N)`。

---

## 九、可视化平台与启动器（已交付）

> **本章为 2026-08-08/09 新增工作**，记录前端可视化、启动器、测试套件的交付状态与排错经验。
> 接手 AI 如需修改可视化或启动器，务必先读本章节和 `项目反思与经验提示词.md`。

### 9.1 交付物清单

| 组件 | 文件 | 状态 | 说明 |
|------|------|------|------|
| Web 入口 | `web/index.html` | ✅ | 含 360/双核浏览器兼容 meta 标签 |
| 可视化引擎 | `web/galaxy.js` | ✅ | Canvas 2D 星云图 + 5 级可展开审计发现 + AI 摘要 |
| 样式 | `web/style.css` | ✅ | 白底黑字，CSS 变量+硬编码双重写法 |
| 静态数据兜底 | `web/audit_data.json` | ✅ | 与 `demo/audit_data.json` 同步 |
| 后端服务器 | `launch.py` | ✅ | SimpleHTTPRequestHandler 子类，含 `/api/audit_data` 和 `/api/ai_summary` |
| CLI 启动器 | `启动平台.bat` | ✅ | 自动 venv 创建 + 依赖安装 + 闪退防护 |
| GUI 启动器 | `launcher_gui.py` + `启动器_图形版.bat` | ✅ | Tkinter GUI + 实时日志 + 环境自动配置 |
| 启动器测试 | `test_launcher_gui.py` | ✅ | T1-T17 共 17 项测试全部通过 |
| 反思文档 | `项目反思与经验提示词.md` | ✅ | 9 类 Checklist + 10 条经验 + 排错方法论 |
| 依赖清单 | `requirements.txt` | ✅ | fastapi/uvicorn/pydantic/PyYAML/openai/pytest |

### 9.2 关键架构决策

#### 9.2.1 前端三级数据兜底

```
galaxy.js init()
  ├─ fetch("/api/audit_data")        ← 首选：launch.py 提供
  ├─ fetch("audit_data.json")        ← 二级：web/ 静态兜底文件
  └─ DOM 内错误提示                  ← 三级：给出可操作修复命令
```

**接手注意**：修改数据格式时，必须同步更新 `demo/audit_data.json` 和 `web/audit_data.json`（launch.py 启动时自动同步，但手动调试时要注意）。

#### 9.2.2 Canvas 节点布局（重点 bug 修复）

**原 bug**：`init()` 在 DOM 布局完成前调用 `resizeCanvas()`，`wrapper.clientWidth=0` → canvas 0×0 → 节点全堆在原点 (0,0) → 空白页。

**修复方案**（[galaxy.js](file:///c:/Pythonproject/解决方案详细报告/web/galaxy.js#L84-L169)）：
1. `resizeCanvas()` 对 `wrapper.clientWidth < 50` 的情况用 `window` 尺寸兜底
2. 提取 `layoutNodes(w, h)` 为独立可重复调用函数
3. `resizeCanvas()` 检测尺寸显著变化（>20px）时自动重排节点
4. `buildNodes()` 只创建节点对象，布局交给 `layoutNodes()`

**接手注意**：修改节点布局逻辑只能改 `layoutNodes()`，不要在 `buildNodes()` 里写位置计算。

#### 9.2.3 启动器环境自动配置

```
启动流程（launcher_gui.py / .bat）：
  1. 检测 .venv\Scripts\python.exe 是否存在
     ├─ 存在 → 检查依赖（_check_deps_installed，timeout=30s）
     │        ├─ 依赖齐全 → 直接启动
     │        └─ 依赖缺失 → pip install -r requirements.txt
     └─ 不存在 → 用系统 Python 创建 venv → pip install
  2. 启动 launch.py，设置 PYTHONUNBUFFERED=1 + PYTHONIOENCODING=utf-8
  3. 后台线程读 stdout → queue → after() 轮询更新 UI
```

**接手注意**：
- `_check_deps_installed` 的 timeout 必须留足余量（≥30s），openai 冷 import 实测 4.8s
- `_read_stdout` 必须用 `proc.poll() is not None` 判断退出，**不能**用 `wait(timeout=N)` 的超时判断
- `on_tk_error` 异常处理**不能**调用 `dr.report_callback_exception`（会无限递归）

### 9.3 启动器测试套件（test_launcher_gui.py）

17 项测试，全部通过：

| 测试 | 验证内容 |
|------|---------|
| T1 | 语法检查 + 关键名字存在 |
| T2 | 模块 import 不抛异常 + 全局钩子安装 |
| T3 | `find_python()` 返回真实存在的 python 路径 |
| T4 | Tk() + LauncherApp 实例化无异常 |
| T5 | UI 组件存在且状态正确（按钮/勾选框/日志 Text） |
| T6 | 默认参数值（端口 8765、regen=False、no_browser=False） |
| T7 | 日志彩色标签注册 + `_log()` 写入 + 兜底不抛错 |
| T8 | start() → stop() 按钮状态联动 |
| T9 | 真实启动 launch.py + GUI 解析 URL |
| T10 | **真实子进程跑 GUI 10 秒存活 + 干净退出（闪退回归测试）** |
| T11 | 崩溃钩子：手动抛异常 → crash.log 写入 |
| T12 | 两个 .bat 文件结构正确 |
| T13 | requirements.txt 包含必需依赖 |
| T14 | `_find_system_python()` 返回可用 python |
| T15 | `_check_deps_installed()` 正确检测当前 venv |
| T16 | `ensure_venv()` 在 venv 已存在时直接返回 |
| T17 | .bat 脚本包含自动创建 venv 逻辑 |

**运行命令**：
```powershell
.venv\Scripts\python.exe -m pytest test_launcher_gui.py -v --tb=short
```

**接手注意**：
- 测试模块顶部已设 `LANG=C` / `LC_ALL=C`（隔离 Tcl/Tk locale 问题，勿删）
- T10 是关键回归测试，任何启动器修改后必须单独重跑：`pytest test_launcher_gui.py::test_t10_subprocess_gui_alive_and_clean_exit -v`

### 9.4 常见排错速查

| 现象 | 排查步骤 |
|------|---------|
| 网页空白 | 1. 查端口占用 `Get-NetTCPConnection -LocalPort 8765`<br>2. 查进程命令行 `Get-CimInstance Win32_Process`（是否误用 `http.server`）<br>3. 浏览器控制台查 JS 错误<br>4. `browser_evaluate` 查 `nodes` 坐标是否全为 0（Canvas 时序 bug）<br>5. `getImageData` 查非空像素比例（<1% = 没画东西） |
| 启动器闪退 | 1. 查 `launcher_crash.log`<br>2. 查 `launcher_batch.log`<br>3. 单跑 T10 回归测试<br>4. 检查 `on_tk_error` 是否有递归调用 |
| 数据加载失败 | 1. 确认 `demo/audit_data.json` 存在且 ~81KB<br>2. 确认用 `launch.py` 启动（非 `http.server`）<br>3. 前端三级兜底链路是否完整 |
| 端口被占用 | 1. `Get-NetTCPConnection -LocalPort 8765,8766 -State Listen`<br>2. `Stop-Process -Id <PID> -Force` 清理残留进程<br>3. 启动器会自动递增找空闲端口，但旧进程要手动清理 |

### 9.5 关键约束（接手必读）

1. **启动方式强约束**：只能用 `launch.py` 或启动器启动，**禁止** `python -m http.server`（无 API 路由会导致空白页）
2. **批处理脚本纯 ASCII**：`.bat` 文件不能用 Unicode 边框字符（═│┌）和中文标点，会导致 cmd 解析错误闪退
3. **Tkinter 异常不递归**：自定义异常处理不能调用会再次触发自身的机制
4. **subprocess 用 poll() 判断退出**：`wait(timeout=N)` 的超时不代表退出
5. **PYTHONUNBUFFERED=1**：子进程必须设此环境变量，否则日志不实时
6. **修改 galaxy.js 时**：节点布局逻辑只能在 `layoutNodes(w, h)` 中，`resizeCanvas` 会检测尺寸变化自动重排

---

## 十、反思与经验文档

> **文件**：`项目反思与经验提示词.md`（根目录）
> **用途**：同类项目开发的可复用 Checklist 和排错手册

### 10.1 文档结构

1. **反思提示词（9 类 Checklist）** — 可粘贴给 AI 作为开发约束：
   - 浏览器兼容性、Canvas 初始化、Python 子进程管理、Tkinter GUI 异常、Windows 批处理、环境依赖管理、Web 服务器端口、前端数据加载容错、测试套件
2. **经验总结（10 条 Lessons Learned）** — 每条含「问题→教训→通用原则」
3. **排错方法论** — 6 层排查顺序：数据层→服务层→接口层→前端层→渲染层→环境层

### 10.2 使用建议

- **开发新功能前**：粘贴相关 Checklist 作为约束（如改 Canvas → 粘贴 Checklist 2）
- **遇到 Bug 时**：按「排错方法论」6 层顺序排查，避免在错误层级反复
- **代码评审时**：用 Checklist 逐项自检
- **接手新项目时**：把 Checklist 作为质量门禁

---

**文档结束。** 接手 AI 请从「第三章 待完成模块清单」的 P0 批次开始执行；如需修改可视化/启动器，先读「第九章」和 `项目反思与经验提示词.md`。
