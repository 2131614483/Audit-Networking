# AI组网与审计模块"预制菜"设计方案

> **文档版本：** v1.0  
> **编制日期：** 2026年7月5日  
> **核心命题：** 如何将36个审计智能化方案打包为"预制菜"式AI模块，通过统一组网架构实现即插即用、微调即交付

---

## 一、核心理念

### 1.1 什么是"预制菜"式AI模块

```
┌───────────────────────────────────────────────────────────────┐
│                    预制菜 vs Skill vs 传统模块                   │
├──────────────┬──────────────────┬──────────────────┬──────────┤
│    维度      │   WorkBuddy Skill │  预制菜AI模块      │  传统软件模块│
├──────────────┼──────────────────┼──────────────────┼──────────┤
│ 运行方式     │ Prompt指令驱动     │ 代码执行+算法运算   │ 编译执行  │
│ 定制方式     │ 修改Prompt        │ 配置+YAML+代码微调  │ 改代码    │
│ 交付物       │ SKILL.md + 提示词  │ 源码+Docker+README │ 二进制/包  │
│ 可执行性     │ 依赖宿主执行       │ 自包含可独立运行    │ 需整体部署 │
│ 组合性       │ 无原生编排         │ 组网编排引擎支持    │ 需手动集成 │
│ AI能力      │ LLM itself        │ ML/CV/NLP/KG/GNN  │ 无/调用API│
│ 代码修改     │ 不可修改           │ 可微调(配置+扩展点) │ 需Fork   │
│ 适用场景     │ 对话式任务         │ 审计业务自动化      │ 通用软件  │
└──────────────┴──────────────────┴──────────────────┴──────────┘
```

**预制菜AI模块的本质：** 是一份"半成品代码"，已实现核心算法和数据流，自带Docker镜像和README文档。使用者通过修改配置文件和少量扩展点代码即可适配具体业务场景——就像预制菜只需加热和微调口味即可上桌。

### 1.2 AI组网的核心理念

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AI组网架构理念                                │
│                                                                     │
│  不是把36个模块连成"网络"，而是建立一套                               │
│  ┌─────────────────────────────────────────────────────┐            │
│  │  模块发现 → 编排执行 → 消息传递 → 状态监控 → 结果汇聚  │            │
│  └─────────────────────────────────────────────────────┘            │
│  的统一运行时环境，让36个预制菜模块可以：                              │
│                                                                     │
│  ① 独立部署运行（每个模块一个Docker容器）                             │
│  ② 动态编排成链（像搭积木一样组合审计流程）                            │
│  ③ 通过消息总线通信（模块间松耦合）                                  │
│  ④ 配置驱动定制（不改核心代码即可适配90%场景）                        │
│  ⑤ 共享基础设施（数据湖/知识图谱/LLM总线/RPA/区块链）                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、AI组网总体架构

### 2.1 五层组网架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AI组网五层架构                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  第五层：审计流程编排层 (Audit Workflow Orchestration)                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │ 流程设计器│ │ 依赖解析 │ │ 并行调度 │ │ 异常处理 │ │ 人工审批 │  │   │
│  │  │ 拖拽编排  │ │ DAG引擎  │ │ 并发执行 │ │ 回滚重试 │ │ 决策节点 │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  第四层：预制菜模块层 (Pre-made Module Layer) - 36个模块               │   │
│  │                                                                       │   │
│  │  ┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐  │   │
│  │  │FA-01 ││FA-02 ││FA-04 ││FA-07 ││FA-10 ││CO-01 ││CO-04 ││...   │  │   │
│  │  │数据  ││标准  ││函证  ││底稿  ││关联方││法规  ││AML   ││36个  │  │   │
│  │  │接入  ││化    ││管理  ││生成  ││发现  ││监控  ││监控  ││模块  │  │   │
│  │  └──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘  │   │
│  │     │       │       │       │       │       │       │       │      │   │
│  │     └───────┴───────┴───────┴───────┴───────┴───────┴───────┴──────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  第三层：AI组网总线层 (AI Networking Bus)                             │   │
│  │                                                                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │ 模块注册  │ │ 消息路由  │ │ 配置中心  │ │ 状态总线  │ │ 日志采集  │  │   │
│  │  │ Registry  │ │ Kafka    │ │ Config    │ │ Status    │ │ Logging   │  │   │
│  │  │ 心跳+发现  │ │ Pub/Sub  │ │ 热更新    │ │ 健康检查  │ │ ELK/Loki  │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  第二层：共享平台服务层 (5大平台)                                      │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │ 数据湖   │ │ 知识图谱 │ │ LLM总线  │ │ RPA编排  │ │ 区块链   │  │   │
│  │  │ ADL      │ │ AKG      │ │ LSB      │ │ ROP      │ │ BCE      │  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  第一层：基础设施层 (Infrastructure)                                  │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │   │
│  │  │ K8s集群  │ │ 对象存储 │ │ 数据库   │ │ API网关  │ │ 监控告警 │  │   │
│  │  │ Docker   │ │ MinIO    │ │ PG+Neo4j │ │ Kong     │ │Prometheus│  │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键设计：预制菜模块与Skill的本质区别

```
┌─────────────────────────────────────────────────────────────────┐
│              预制菜模块 vs Skill —— 设计层面的差异               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Skill（WorkBuddy Skill）:                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  SKILL.md（纯文本指令）                                    │   │
│  │     ↓                                                     │   │
│  │  LLM读取指令 → 理解意图 → 调用工具 → 生成结果              │   │
│  │                                                           │   │
│  │  本质：Instruction-driven，依赖LLM的推理能力                │   │
│  │  局限：无法做真正的ML训练、图计算、实时流处理               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  预制菜AI模块:                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  src/engine.py（真实可执行代码）                            │   │
│  │     ↓                                                     │   │
│  │  Docker容器启动 → 加载模型 → 监听消息 → 执行算法 → 输出    │   │
│  │                                                           │   │
│  │  本质：Code-driven，是一个真实运行的微服务                   │   │
│  │  能力：ML训练/推理、GNN图计算、CV识别、实时流处理           │   │
│  │  微调方式：修改module.yaml配置 + 扩展src/custom/ 代码       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、预制菜模块标准规范

### 3.1 标准目录结构

```
module-{编号}-{名称}/
│
├── README.md                        # [必选] 模块说明 + 使用手册 + 定制指南
├── module.yaml                      # [必选] 模块元数据（注册、依赖、配置声明）
│
├── src/                             # [必选] 核心代码（可直接运行）
│   ├── __init__.py
│   ├── main.py                      # 模块入口：启动服务、注册到总线
│   ├── engine.py                    # 核心算法引擎（不可修改的部分）
│   ├── pipeline.py                  # 数据/执行管道（编排内部步骤）
│   ├── api.py                       # REST API接口（模块对外暴露的服务）
│   ├── models/                      # ML/CV/GNN模型文件或加载器
│   │   ├── __init__.py
│   │   └── model_loader.py          # 模型加载、推理接口
│   ├── connectors/                  # 模块专属连接器（如需要）
│   │   ├── __init__.py
│   │   └── custom_connector.py
│   └── custom/                      # [核心] 用户定制扩展点
│       ├── __init__.py
│       ├── custom_rules.py          # 自定义业务规则
│       ├── custom_thresholds.py     # 自定义阈值/参数
│       └── custom_formatter.py      # 自定义输出格式
│
├── config/                          # [必选] 配置文件
│   ├── default.yaml                 # 默认配置（不可修改，供参考）
│   ├── custom.yaml                  # 用户自定义配置（微调入口）
│   └── schema.yaml                  # 配置项Schema定义（JSON Schema格式）
│
├── templates/                       # [可选] 模板文件
│   ├── prompt_templates/            # LLM Prompt模板（如模块使用LLM）
│   ├── report_templates/            # 报告模板（Word/Excel/HTML）
│   └── rule_templates/              # 规则模板（如模块使用规则引擎）
│
├── tests/                           # [必选] 测试用例
│   ├── test_engine.py
│   ├── test_pipeline.py
│   ├── test_api.py
│   └── fixtures/                    # 测试数据
│       ├── sample_input.json
│       └── expected_output.json
│
├── docs/                            # [必选] 文档
│   ├── ARCHITECTURE.md              # 架构设计文档
│   ├── API.md                       # API接口文档
│   ├── CUSTOMIZATION.md             # 定制化指南（详细说明每个扩展点）
│   └── TROUBLESHOOTING.md           # 常见问题排查
│
├── Dockerfile                       # [必选] 容器镜像定义
├── docker-compose.module.yaml       # [必选] 模块独立部署编排
├── requirements.txt                 # [必选] Python依赖
├── Makefile                         # [可选] 常用命令快捷方式
└── .module-version                  # [必选] 版本号文件
```

### 3.2 module.yaml 元数据规范

```yaml
# module.yaml —— 预制菜模块的"身份证"
# 位于每个模块根目录，组网总线通过它发现和注册模块

module:
  # ===== 模块标识 =====
  id: "FA-01"                           # 唯一标识符
  name: "智能数据接入平台"               # 中文名
  name_en: "Intelligent Data Ingestion"  # 英文名
  version: "1.2.0"                       # 语义化版本
  category: "financial_audit"            # 业务分类: financial_audit/internal_audit/compliance/...
  
  # ===== 模块描述 =====
  description: |
    智能数据接入平台通过100+预置连接器模板、RPA自动采集、
    ML智能Schema映射和ETL数据管道，实现审计数据全自动接入。
  tags: [data-ingestion, rpa, etl, schema-mapping]
  difficulty: 3                          # 1-5（对应方案文档中的⭐难度）
  priority: "high"                       # high/medium/low

  # ===== 模块运行环境 =====
  runtime:
    language: "python"
    version: "3.11"
    framework: "fastapi"
    port: 8001                           # 模块监听端口
    health_check: "/api/v1/health"       # 健康检查端点
    
  # ===== 依赖声明 =====
  dependencies:
    # 平台依赖（5大共享平台）
    platforms:
      - adl                               # 需要数据湖平台
      - rop                               # 需要RPA编排平台
      - lsb                               # 需要LLM服务总线（可选）
    # 模块依赖（前置模块）
    modules: []                           # FA-01无前置模块依赖
    
  # ===== 对外接口 =====
  interfaces:
    # 消息队列接口（接收上游消息）
    consumes:
      - topic: "audit.task.trigger"
        schema: "TaskTriggerRequest"
    # 消息队列接口（产出下游消息）
    produces:
      - topic: "audit.data.ingested"
        schema: "DataIngestedEvent"
      - topic: "audit.data.quality_report"
        schema: "QualityReportEvent"
    # REST API接口
    rest_apis:
      - path: "/api/v1/datasources"
        method: "GET"
        description: "获取数据源列表"
      - path: "/api/v1/connectors"
        method: "POST"
        description: "创建连接器"
      - path: "/api/v1/schema-mapping"
        method: "POST"
        description: "执行Schema映射"
      - path: "/api/v1/quality/check"
        method: "POST"
        description: "执行质量检查"
        
  # ===== 资源配置 =====
  resources:
    cpu: "2"
    memory: "4Gi"
    gpu: false                           # 是否需要GPU
    storage: "10Gi"                      # 持久化存储需求
    
  # ===== 配置暴露（用户可微调项） =====
  configurable:
    # 这些配置项会暴露给用户，通过config/custom.yaml修改
    - key: "connector.concurrency"
      type: "integer"
      default: 5
      description: "连接器并发执行数量"
      validation: "1-20"
    - key: "connector.retry.max_attempts"
      type: "integer"
      default: 3
      description: "连接器失败重试次数"
    - key: "quality.threshold.completeness"
      type: "float"
      default: 0.95
      description: "完整性检查阈值"
    - key: "quality.threshold.accuracy"
      type: "float"
      default: 0.98
      description: "准确性检查阈值"
    - key: "schema.mapping.confidence_threshold"
      type: "float"
      default: 0.90
      description: "Schema自动映射置信度阈值"
    - key: "schema.mapping.model"
      type: "enum"
      default: "bert-base-chinese"
      options: ["bert-base-chinese", "xlm-roberta-base", "custom"]
      description: "Schema映射使用的NLP模型"
      
  # ===== 扩展点声明 =====
  extension_points:
    - id: "custom_connector_template"
      file: "src/custom/custom_connector.py"
      description: "自定义连接器模板，用于适配特殊数据源"
      example: "新增对用友U8旧版的适配"
    - id: "custom_quality_rule"
      file: "src/custom/custom_rules.py"
      description: "自定义数据质量检查规则"
      example: "添加行业特有的数据校验规则"
    - id: "custom_schema_mapping"
      file: "src/custom/custom_thresholds.py"
      description: "自定义Schema映射规则"
      example: "添加非标准会计科目的映射"
    - id: "custom_output_format"
      file: "src/custom/custom_formatter.py"
      description: "自定义数据输出格式"
      example: "输出为特定BI工具格式"
      
  # ===== 模块分类标签（用于模块市场检索）=====
  marketplace:
    icon: "data-ingestion"
    screenshots: ["docs/screenshots/dashboard.png"]
    demo_video: "https://example.com/demo/fa-01"
    changelog: "CHANGELOG.md"
    license: "proprietary"
    author: "KPMG Audit AI Team"
```

### 3.3 预制菜模块的三个"成熟度等级"

```
┌─────────────────────────────────────────────────────────────────┐
│                    预制菜成熟度等级                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  🥘 等级1：生鲜食材 (Raw Ingredients)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  现状：只有方案设计文档（.md），无代码                      │   │
│  │  交付物：module.yaml + README.md + config/default.yaml    │   │
│  │  状态：IA-02,03,04,06,07,08 / CO-03,06,08 / IT-04,05    │   │
│  │        FO-03,05,06 / TA-03,05,06 / SC-03,05 ...         │   │
│  │  用时：将方案文档转化为预制菜骨架 ≈ 2人天/模块              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  🍳 等级2：预制菜 (Pre-made) - 核心目标                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  现状：有完整代码实现 + Docker化 + README + 测试            │   │
│  │  交付物：完整的预制菜模块（上述目录结构的全部内容）           │   │
│  │  状态：FA-01 (唯一已完成的MVP)                              │   │
│  │  用时：将方案文档+等级1骨架 开发为完整模块                   │   │
│  │        简单模块(⭐⭐): 2-3周 / 中等模块(⭐⭐⭐): 4-6周     │   │
│  │        复杂模块(⭐⭐⭐⭐⭐): 8-12周                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  🍽️ 等级3：定制菜肴 (Customized Dish)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  现状：预制菜模块 + 客户现场微调（配置+扩展点代码）          │   │
│  │  交付物：针对具体客户定制的运行实例                          │   │
│  │  用时：在预制菜基础上微调 ≈ 1-5天/模块                      │   │
│  │  微调范围：config/custom.yaml + src/custom/ 下扩展点代码     │   │
│  │  原则：不修改 src/engine.py 等核心文件                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 四、AI组网总线设计（第三层核心）

### 4.1 模块注册与发现机制

```
┌─────────────────────────────────────────────────────────────────┐
│                    模块注册中心 (Module Registry)                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  启动时自动注册流程：                                             │
│                                                                 │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │ 预制菜   │    │  注册中心     │    │  编排引擎     │          │
│  │ 模块容器  │    │  (Registry)  │    │ (Orchestrator)│          │
│  └────┬─────┘    └──────┬───────┘    └──────┬───────┘          │
│       │                 │                    │                   │
│       │ ① 容器启动       │                    │                   │
│       │ 读取module.yaml │                    │                   │
│       │                 │                    │                   │
│       │ ② POST /register│                    │                   │
│       │─────────────────►                    │                   │
│       │  {module_id,    │                    │                   │
│       │   version,      │  ③ 写入注册表       │                   │
│       │   port,         │  (Redis/etcd)      │                   │
│       │   interfaces,   │                    │                   │
│       │   dependencies} │                    │                   │
│       │                 │                    │                   │
│       │ ④ 200 OK        │                    │                   │
│       │◄────────────────│                    │                   │
│       │                 │                    │                   │
│       │ ⑤ 心跳 (每10秒)  │                    │                   │
│       │ POST /heartbeat │                    │                   │
│       │─────────────────►                    │                   │
│       │                 │ ⑥ 超30秒无心跳      │                   │
│       │                 │ → 标记为UNHEALTHY  │                   │
│       │                 │                    │                   │
│       │                 │ ⑦ 模块变更事件      │                   │
│       │                 │────────────────────►│                   │
│       │                 │  (新模块上线/离线)   │  ⑧ 更新编排图    │
│                                                                 │
│  编排引擎消费事件：                                              │
│  - MODULE_REGISTERED: 新模块上线 → 可编排进审计流程              │
│  - MODULE_UNHEALTHY: 模块离线 → 暂停依赖此模块的流程             │
│  - MODULE_UPGRADED: 模块版本升级 → 平滑切换                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 消息路由总线（Kafka主题体系）

```
┌─────────────────────────────────────────────────────────────────┐
│                    Kafka 消息主题体系                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  三大消息通道：                                                   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  通道1：数据通道 (data.*)                                  │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ data.raw.{module_id}      原始数据流              │   │   │
│  │  │ data.normalized.{module_id} 标准化数据流          │   │   │
│  │  │ data.ingested               数据接入完成事件       │   │   │
│  │  │ data.quality_report         质量检查报告          │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │  特点：高吞吐量、消息体大（可能含数据文件引用）             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  通道2：事件通道 (event.*)                                 │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ event.module.status          模块状态变更         │   │   │
│  │  │ event.task.started           审计任务开始         │   │   │
│  │  │ event.task.completed         审计任务完成         │   │   │
│  │  │ event.task.failed            审计任务失败         │   │   │
│  │  │ event.alert.{severity}       告警事件             │   │   │
│  │  │ event.audit_log              审计日志（不可变）    │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │  特点：小消息体、需持久化、支持重放                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  通道3：指令通道 (cmd.*)                                   │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │ cmd.module.{module_id}.execute   执行指令         │   │   │
│  │  │ cmd.module.{module_id}.pause      暂停指令        │   │   │
│  │  │ cmd.module.{module_id}.resume     恢复指令        │   │   │
│  │  │ cmd.module.{module_id}.reload     重载配置        │   │   │
│  │  │ cmd.workflow.{flow_id}.start      启动流程        │   │   │
│  │  │ cmd.workflow.{flow_id}.abort      中止流程        │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │  特点：需确认响应、有时效性要求                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 配置中心设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    配置中心 (Config Center)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  配置三级继承体系：                                               │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Level 1: default.yaml (模块自带，不可修改)                  │ │
│  │  ─────────────────────────────────────────                  │ │
│  │  出厂默认值，定义了模块的所有可配置项及其默认值                │ │
│  │  随模块版本发布，保证可回滚到出厂状态                         │ │
│  └───────────────────────────────────────────────────────────┘ │
│                            ↓ 被覆盖                              │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Level 2: custom.yaml (用户修改，持久化存储)                 │ │
│  │  ─────────────────────────────────────────                  │ │
│  │  用户的定制配置，只包含与default不同的项                      │ │
│  │  存储在配置中心（etcd/Consul），支持热更新                    │ │
│  │  Git版本控制，支持配置回滚                                   │ │
│  └───────────────────────────────────────────────────────────┘ │
│                            ↓ 被覆盖                              │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  Level 3: 运行时参数 (API/环境变量动态注入)                  │ │
│  │  ─────────────────────────────────────────                  │ │
│  │  运行时的紧急参数覆盖（如临时调整并发度应对突发流量）          │ │
│  │  通过API或环境变量注入，重启后失效（回退到Level 2）           │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  配置热更新机制：                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  1. 用户修改 custom.yaml → 推送到配置中心                  │  │
│  │  2. 配置中心发出 ConfigChangeEvent 到 cmd 通道             │  │
│  │  3. 模块监听到 cmd.module.{id}.reload → 重新加载配置      │  │
│  │  4. 模块上报 ConfigApplied 事件确认                        │  │
│  │  5. 对于不支持热更新的配置项（需重启的），标记 restart_needed│  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 五、预制菜模块开发模板（以FA-01为例）

### 5.1 完整示例：将FA-01方案文档转化为预制菜模块

以下展示FA-01方案文档如何转化为标准预制菜模块的完整结构：

```
fa-01-data-ingestion/                     # 预制菜模块根目录
│
├── README.md                             # → 见下文 5.2
├── module.yaml                           # → 见上文 3.2
│
├── src/
│   ├── __init__.py                       # 模块初始化 + 版本信息
│   ├── main.py                           # FastAPI应用入口 + 注册到总线
│   ├── engine.py                         # 核心引擎（不变部分）
│   │   ├── DataIngestionEngine           # 数据接入引擎主类
│   │   ├── ConnectorManager              # 连接器管理器
│   │   ├── NormalizationEngine           # 标准化引擎
│   │   └── QualityEngine                 # 质量检查引擎
│   ├── pipeline.py                       # 执行管道
│   │   └── IngestionPipeline             # 采集→标准化→质检→存储管道
│   ├── api.py                            # REST API
│   ├── models/
│   │   ├── __init__.py
│   │   ├── audit_data_models.py          # 6张标准审计表ORM模型
│   │   └── schema_mapping_model.py       # ML Schema映射模型加载器
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py                       # 连接器基类
│   │   ├── api_connector.py              # API连接器
│   │   ├── db_connector.py               # 数据库连接器
│   │   ├── file_connector.py             # 文件连接器
│   │   └── rpa_connector.py              # RPA连接器
│   └── custom/                           # ★ 用户定制扩展点
│       ├── __init__.py
│       ├── custom_connector.py           # ★ 自定义连接器模板
│       ├── custom_rules.py               # ★ 自定义质量检查规则
│       ├── custom_schema.py              # ★ 自定义Schema映射
│       └── custom_formatter.py           # ★ 自定义输出格式
│
├── config/
│   ├── default.yaml                      # 出厂默认配置
│   ├── custom.yaml                       # 用户定制配置
│   └── schema.yaml                       # 配置Schema定义
│
├── templates/
│   ├── connector_templates/              # 连接器预置模板
│   │   ├── sap_s4hana.yaml               # SAP S/4HANA模板
│   │   ├── yonyou_nc.yaml                # 用友NC模板
│   │   ├── kingdee_cosmic.yaml           # 金蝶云星辰模板
│   │   └── ...                           # 100+预置模板
│   ├── schema_mappings/                  # Schema映射模板
│   │   ├── gl_account_mapping.yaml       # 科目映射
│   │   ├── voucher_mapping.yaml          # 凭证映射
│   │   └── ...
│   └── quality_checks/                   # 质量检查模板
│       ├── completeness.yaml             # 完整性检查
│       ├── consistency.yaml              # 一致性检查
│       └── ...
│
├── tests/
│   ├── test_engine.py
│   ├── test_connectors.py
│   ├── test_pipeline.py
│   ├── test_api.py
│   └── fixtures/
│       ├── sample_sap_export.csv
│       ├── sample_yonyou_export.xlsx
│       └── expected_normalized.json
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── CUSTOMIZATION.md                  # ★ 定制化指南
│   └── TROUBLESHOOTING.md
│
├── Dockerfile
├── docker-compose.module.yaml
├── requirements.txt
├── Makefile
└── .module-version
```

### 5.2 README.md 模板规范

每个预制菜模块的README必须包含以下标准章节：

```markdown
# [FA-01] 智能数据接入平台

> 🍳 预制菜成熟度：等级2 | 难度：⭐⭐⭐ | Python 3.11 | FastAPI

## 📋 模块简介

一句话：智能数据接入平台通过预置连接器模板、RPA自动采集、ML Schema映射，
将审计数据采集时间从占总工时30-40%压缩至5-8%。

## 🚀 快速启动（5分钟上手）

### 前置依赖
- Docker & Docker Compose
- 依赖平台：数据湖(ADL)、RPA编排(ROP)

### 一键启动
```bash
# 1. 克隆或下载模块
cd fa-01-data-ingestion

# 2. 复制并修改你的配置
cp config/default.yaml config/custom.yaml
vim config/custom.yaml    # 修改数据库连接、API密钥等

# 3. 启动
docker-compose -f docker-compose.module.yaml up -d

# 4. 验证
curl http://localhost:8001/api/v1/health
```

## ⚙️ 定制指南（核心！）

### 微调级别

| 级别 | 方式 | 修改内容 | 耗时 |
|------|------|---------|------|
| **L0 开箱即用** | 不改任何文件 | 使用默认配置 | 5分钟 |
| **L1 配置级** | 修改 config/custom.yaml | 调整参数、切换模型 | 30分钟 |
| **L2 模板级** | 添加 templates/ 下新模板 | 新增数据源适配 | 2小时 |
| **L3 扩展级** | 修改 src/custom/ 下代码 | 自定义业务逻辑 | 1天 |
| **L4 核心级** | 修改 src/engine.py | 修改核心算法 | 1周+ |

### 常用微调场景

#### 场景1：适配一个新的财务系统数据源
```yaml
# config/custom.yaml
connectors:
  custom:
    - name: "某客户自研ERP"
      type: "api"                        # 或 db/file/rpa
      template: "templates/connector_templates/custom_erp.yaml"
```
然后在 `templates/connector_templates/` 下创建对应的模板文件。

#### 场景2：添加行业特有的数据质量规则
```python
# 修改 src/custom/custom_rules.py
def check_industry_specific_rule(data_batch):
    """
    添加行业特有规则，例如：
    - 房地产行业：检查预收账款与合同负债的匹配
    - 制造业：检查生产成本归集完整性
    """
    # 你的自定义规则代码
    pass
```

#### 场景3：调整Schema映射模型
```yaml
# config/custom.yaml
schema:
  mapping:
    model: "custom"                      # 使用自定义模型
    custom_model_path: "/models/my_finetuned_bert"
    confidence_threshold: 0.85           # 降低自动映射阈值
```

### 扩展点清单

| 扩展点 | 文件位置 | 用途 |
|--------|---------|------|
| 自定义连接器 | `src/custom/custom_connector.py` | 适配特殊数据源 |
| 自定义质检规则 | `src/custom/custom_rules.py` | 添加业务特有校验 |
| 自定义Schema映射 | `src/custom/custom_schema.py` | 扩展标准数据模型 |
| 自定义输出格式 | `src/custom/custom_formatter.py` | 适配下游系统格式 |

## 📡 API接口

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 健康检查 | GET | `/api/v1/health` | 模块健康状态 |
| 数据源列表 | GET | `/api/v1/datasources` | 获取数据源列表 |
| 创建连接器 | POST | `/api/v1/connectors` | 配置新连接器 |
| 执行采集 | POST | `/api/v1/connectors/{id}/execute` | 触发数据采集 |
| Schema映射 | POST | `/api/v1/schema-mapping` | 执行字段映射 |
| 质量检查 | POST | `/api/v1/quality/check` | 执行数据质量检查 |
| 审计数据查询 | GET | `/api/v1/audit-data` | 查询标准化审计数据 |

## 📊 监控指标

模块自动上报以下Prometheus指标：
- `module_fa01_connector_executions_total` - 连接器执行次数
- `module_fa01_data_rows_ingested` - 接入数据行数
- `module_fa01_schema_mapping_accuracy` - Schema映射准确率
- `module_fa01_quality_score` - 数据质量评分

## 🔗 依赖关系

```
上游：无（数据采集的起点）
下游：FA-02(数据标准化)、FA-03(数据湖)、FA-04(函证)、FA-07(底稿)、FA-10(关联方)
平台：ADL(数据湖) + ROP(RPA编排) + LSB(LLM服务，可选)
```

## 📝 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.2.0 | 2026-07-04 | 完成API/DB/File/RPA四类连接器 |
| 1.1.0 | 2026-06-20 | 新增标准化引擎和质量检查引擎 |
| 1.0.0 | 2026-06-01 | 初始版本，MVP |
```

---

## 六、审计流程编排引擎

### 6.1 从模块到审计流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    审计流程编排示例                               │
│                                                                 │
│  示例：财务报表审计完整流程                                       │
│                                                                 │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐   │
│  │ FA-01   │────►│ FA-02   │────►│ FA-03   │────►│ FA-10   │   │
│  │ 数据接入 │     │ 标准化   │     │ 数据湖   │     │ 关联方   │   │
│  └─────────┘     └─────────┘     └─────────┘     │ 发现     │   │
│                                                   └────┬────┘   │
│                                                        │        │
│                     ┌──────────────────────────────────┤        │
│                     │                                  │        │
│                     ▼                                  ▼        │
│              ┌─────────┐     ┌─────────┐     ┌─────────┐       │
│              │ FA-04   │     │ FA-11   │     │ FA-12   │       │
│              │ 函证管理 │     │ 关联定价 │     │ 关联披露 │       │
│              └────┬────┘     └─────────┘     └─────────┘       │
│                   │                                             │
│              ┌────▼────┐     ┌─────────┐                       │
│              │ FA-05   │     │ FA-06   │                       │
│              │ 链上函证 │     │ 函证分析 │                       │
│              └─────────┘     └─────────┘                       │
│                     │         ┌─────────┐                       │
│                     └────────►│ FA-07   │                       │
│                               │ 底稿生成 │                       │
│                               └────┬────┘                       │
│                                    │                            │
│                              ┌─────┴─────┐                     │
│                              ▼           ▼                     │
│                        ┌─────────┐ ┌─────────┐                 │
│                        │ FA-08   │ │ FA-09   │                 │
│                        │ 勾稽检查 │ │ 底稿复核 │                 │
│                        └─────────┘ └─────────┘                 │
│                                                                 │
│  编排引擎负责：                                                   │
│  1. 按依赖关系拓扑排序执行                                       │
│  2. 并行组同时执行（FA-08和FA-09可并行）                          │
│  3. 上游模块输出 → 通过Kafka → 下游模块输入                      │
│  4. 异常时自动重试/暂停/告警                                     │
│  5. 人工审批节点（如质量检查不通过时暂停）                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 审计流程定义（YAML格式）

```yaml
# audit_workflows/financial_audit_full.yaml
# 财务报表审计完整流程定义

workflow:
  id: "financial_audit_full"
  name: "财务报表审计完整流程"
  version: "1.0"
  
  # 流程输入参数
  parameters:
    - name: "client_id"
      type: "string"
      required: true
      description: "被审计客户ID"
    - name: "fiscal_year"
      type: "integer"
      required: true
      description: "审计年度"
    - name: "materiality_threshold"
      type: "float"
      default: 0.05
      description: "重要性水平"
      
  # 流程步骤定义（DAG节点）
  steps:
    # 阶段1：数据采集（串行）
    - id: "data_ingestion"
      module: "FA-01"
      description: "从各系统采集原始数据"
      params:
        client_id: "${{parameters.client_id}}"
        fiscal_year: "${{parameters.fiscal_year}}"
        
    - id: "data_normalization"
      module: "FA-02"
      description: "数据标准化"
      depends_on: ["data_ingestion"]
      params:
        source: "${{steps.data_ingestion.output.raw_data_path}}"
        
    - id: "data_lake_load"
      module: "FA-03"
      description: "加载到审计数据湖"
      depends_on: ["data_normalization"]
      
    # 阶段2：关联方分析 + 函证（可并行）
    - id: "related_party_discovery"
      module: "FA-10"
      description: "知识图谱关联方发现"
      depends_on: ["data_lake_load"]
      
    - id: "confirmation_management"
      module: "FA-04"
      description: "函证管理"
      depends_on: ["data_lake_load"]
      
    # 阶段3：函证后续分析
    - id: "blockchain_confirmation"
      module: "FA-05"
      description: "区块链银行函证"
      depends_on: ["confirmation_management"]
      
    - id: "confirmation_analysis"
      module: "FA-06"
      description: "函证差异分析"
      depends_on: ["blockchain_confirmation"]
      
    # 阶段4：关联交易分析 + 底稿生成（可并行）
    - id: "related_pricing"
      module: "FA-11"
      description: "关联交易定价分析"
      depends_on: ["related_party_discovery"]
      
    - id: "related_disclosure"
      module: "FA-12"
      description: "关联交易披露检查"
      depends_on: ["related_party_discovery"]
      
    - id: "workpaper_generation"
      module: "FA-07"
      description: "智能底稿生成"
      depends_on: ["data_lake_load", "confirmation_analysis"]
      
    # 阶段5：底稿审核
    - id: "workpaper_cross_check"
      module: "FA-08"
      description: "底稿勾稽检查"
      depends_on: ["workpaper_generation"]
      
    - id: "workpaper_review"
      module: "FA-09"
      description: "AI底稿复核"
      depends_on: ["workpaper_generation"]
      
  # 人工审批节点
  approvals:
    - id: "approve_related_parties"
      after: "related_party_discovery"
      description: "审计经理确认关联方清单"
      timeout_hours: 24
      
    - id: "approve_workpapers"
      after: "workpaper_review"
      description: "审计经理签署底稿"
      timeout_hours: 48
      
  # 异常处理策略
  error_handling:
    retry:
      max_attempts: 3
      backoff: "exponential"
    on_failure: "pause_and_notify"     # 暂停流程并通知
    dead_letter: "kafka:dead_letter"   # 失败消息死信队列
```

---

## 七、36个模块的预制菜成熟度分布与转化路线

### 7.1 当前状态分布

```
现有资产盘点：

┌─────────────────────────────────────────────────────────────────┐
│                    36个模块的三种状态                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  🍽️ 等级2（完整预制菜 - 1个）                                    │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ FA-01 智能数据接入平台 — 65个文件，5018行代码，Docker化   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  📄 方案文档（设计蓝图 - 35个）                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 每个方案都是一份详细的.md设计文档，包含：                    │  │
│  │ - 问题定位（为什么需要）                                    │  │
│  │ - 技术架构设计（怎么做）                                    │  │
│  │ - 数据流设计（数据怎么走）                                  │  │
│  │ - 实施路径（怎么落地）                                      │  │
│  │ - ROI分析（值不值）                                         │  │
│  │                                                            │  │
│  │ 方案文档 → 预制菜模块 的映射关系：                           │  │
│  │ ┌──────────────┬───────────────────────────────────┐      │  │
│  │ │ 方案文档内容  │  预制菜模块对应物                    │      │  │
│  │ ├──────────────┼───────────────────────────────────┤      │  │
│  │ │ 问题定位      │  → README.md（模块简介章节）         │      │  │
│  │ │ 技术架构      │  → module.yaml（技术栈+依赖声明）   │      │  │
│  │ │ 数据流设计    │  → src/pipeline.py（执行管道）       │      │  │
│  │ │ 核心算法描述  │  → src/engine.py（核心引擎代码）     │      │  │
│  │ │ 接口设计      │  → src/api.py + module.yaml接口声明 │      │  │
│  │ │ 部署配置      │  → Dockerfile + docker-compose      │      │  │
│  │ │ 质量标准      │  → tests/ + config中的阈值配置      │      │  │
│  │ └──────────────┴───────────────────────────────────┘      │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 转化路线图

```
┌─────────────────────────────────────────────────────────────────┐
│              方案文档 → 预制菜模块 转化工程                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase 1：建立骨架（每个模块 1-2人天 × 35个 = ~70人天）          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 输入：方案设计文档 (.md)                                    │   │
│  │ 输出：等级1骨架（README + module.yaml + config + 空目录）    │   │
│  │                                                            │   │
│  │ 步骤：                                                     │   │
│  │  1. 从方案文档提取技术栈信息 → 生成 module.yaml            │   │
│  │  2. 从方案文档提取架构描述 → 生成 ARCHITECTURE.md          │   │
│  │  3. 从方案文档提取配置项 → 生成 config/default.yaml         │   │
│  │  4. 从方案文档提取接口定义 → 生成 api.py 骨架              │   │
│  │  5. 从方案文档提取定制点 → 生成 src/custom/ 扩展点         │   │
│  │  6. 从方案文档提取质量标准 → 生成 tests/fixtures           │   │
│  │  7. 创建 Dockerfile + docker-compose.module.yaml           │   │
│  │  8. 编写 README.md（含快速启动和定制指南）                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Phase 2：填充核心代码（按优先级和依赖分批）                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                             │   │
│  │  批次A（第一阶段基础模块，需8周）：                           │   │
│  │    FA-02, FA-03, CO-07, CO-08                              │   │
│  │    （数据湖平台的组成模块）                                  │   │
│  │                                                             │   │
│  │  批次B（第二阶段财务审计模块，需12周）：                      │   │
│  │    FA-04, FA-05, FA-06, FA-07, FA-08, FA-09,               │   │
│  │    FA-10, FA-11, FA-12                                     │   │
│  │                                                             │   │
│  │  批次C（第三阶段专项审计模块，需16周）：                      │   │
│  │    IA-01~08, CO-01~09, IT-01~05, FO-01~06,                │   │
│  │    TA-01~06, SC-01~05, ES-01~06                            │   │
│  │                                                             │   │
│  │  批次D（第四阶段高级模块，需12周）：                          │   │
│  │    IP-01~06, FI-01~05, CB-01~06, CM-01~05                 │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Phase 3：组网集成验证（持续进行）                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 每批次完成后，在组网环境下进行集成验证：                       │   │
│  │  1. 模块注册到注册中心                                      │   │
│  │  2. 编排审计流程（端到端验证）                               │   │
│  │  3. 消息总线连通性测试                                       │   │
│  │  4. 配置热更新验证                                          │   │
│  │  5. 异常场景演练（模块离线、消息丢失、超时等）                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 难度分级与资源配置

```
┌─────────────────────────────────────────────────────────────────┐
│          36个模块按难度分级 → 预制菜转化资源估算                    │
├────────┬────────┬────────────────────────────────┬──────────────┤
│ 难度    │ 方案数  │ 方案编号                         │ 每模块转化工时│
├────────┼────────┼────────────────────────────────┼──────────────┤
│ ⭐     │ 0      │ -                               │ -            │
│ ⭐⭐    │ 5      │ CM-03,04,05, CO-03, IP-05     │ 2-3周        │
│ ⭐⭐⭐   │ 14     │ FA-01,02,03,06,09,12 /         │ 4-6周        │
│        │        │ IA-03,04,06,07 / IT-04,05 /    │              │
│        │        │ FO-05,06 / TA-03 / SC-03       │              │
│ ⭐⭐⭐⭐  │ 10     │ FA-04,05,08,11 / CO-06,08,09 / │ 6-8周        │
│        │        │ FO-03 / TA-01,05 / IP-03        │              │
│ ⭐⭐⭐⭐⭐ │ 7      │ FA-07,10 / CO-01,02,04,05 /    │ 8-12周       │
│        │        │ CB-01 / CM-01                   │              │
├────────┼────────┼────────────────────────────────┼──────────────┤
│ 合计    │ 36     │ (FA-01已转化)                   │ ~800人周     │
└────────┴────────┴────────────────────────────────┴──────────────┘

注：以上为从方案文档到完整预制菜模块（等级2）的转化工时估算，
    实际执行中可按优先级分批进行。
```

---

## 八、预制菜模块市场与版本管理

### 8.1 模块市场设计

```
┌─────────────────────────────────────────────────────────────────┐
│                    预制菜模块市场 (Module Marketplace)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  概念：类似 npm / Docker Hub，但是面向审计AI模块                   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    模块市场门户                            │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │   │
│  │  │ 全部模块  │ │ 财务审计  │ │ 合规审计  │ │ 搜索...   │   │   │
│  │  │  (36)    │ │  (12)    │ │  (9)     │ │          │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │   │
│  │                                                         │   │
│  │  ┌──────────────────────────────────────────────────┐   │   │
│  │  │  FA-01 智能数据接入平台                      v1.2.0│   │   │
│  │  │  ┌────────────────────────────────────────┐      │   │   │
│  │  │  │  [模块图标]                              │      │   │   │
│  │  │  │                                         │      │   │   │
│  │  │  │  🍳 等级2 | ⭐⭐⭐ | Python 3.11        │      │   │   │
│  │  │  │  📦 5,018行代码 | 🐳 Docker化 | ✅ 已测试│      │   │   │
│  │  │  │  📥 安装: module pull fa-01             │      │   │   │
│  │  │  │  🚀 启动: module start fa-01            │      │   │   │
│  │  │  └────────────────────────────────────────┘      │   │   │
│  │  └──────────────────────────────────────────────────┘   │   │
│  │                                                         │   │
│  │  每个模块卡片展示：                                       │   │
│  │  - 成熟度等级（🥘生鲜 / 🍳预制菜 / 🍽️定制）               │   │
│  │  - 版本号 + 发布日期                                     │   │
│  │  - 依赖平台（ADL/AKG/LSB/ROP/BCE）                       │   │
│  │  - 依赖模块（前置模块列表）                               │   │
│  │  - 代码量 + 测试覆盖率                                   │   │
│  │  - 下载/安装命令                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 模块版本管理策略

```
┌─────────────────────────────────────────────────────────────────┐
│                    语义化版本 + 依赖锁定                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  版本号格式：MAJOR.MINOR.PATCH (遵循 SemVer 2.0)                 │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  MAJOR (主版本号): 不兼容的API修改                         │   │
│  │    例：1.x.x → 2.0.0 (修改了消息接口的schema)             │   │
│  │                                                           │   │
│  │  MINOR (次版本号): 向下兼容的功能新增                       │   │
│  │    例：1.2.0 → 1.3.0 (新增了MongoDB连接器模板)            │   │
│  │                                                           │   │
│  │  PATCH (修订号): 向下兼容的问题修复                        │   │
│  │    例：1.2.0 → 1.2.1 (修复了标准化的日期格式Bug)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  版本锁定文件 (module-lock.yaml):                                │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  # 审计流程的依赖锁定（类似 package-lock.json）            │   │
│  │  workflow: financial_audit_full                           │   │
│  │  version: "1.0"                                           │   │
│  │  modules:                                                 │   │
│  │    FA-01:                                                 │   │
│  │      version: "1.2.0"                                     │   │
│  │      checksum: "sha256:abc123..."                         │   │
│  │      docker_image: "registry/fa-01:1.2.0"                │   │
│  │    FA-02:                                                 │   │
│  │      version: "1.0.0"                                     │   │
│  │      checksum: "sha256:def456..."                         │   │
│  │    ...                                                     │   │
│  │  作用：保证审计流程的可复现性 —— 同一流程版本，            │   │
│  │        锁定所有依赖模块的确切版本                           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 九、部署与运维

### 9.1 三种部署模式

```
┌─────────────────────────────────────────────────────────────────┐
│                    预制菜模块的三种部署模式                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  模式1：独立单模块部署 (Standalone)                              │
│  ┌──────────────────────────────────────────────────────┐      │
│  │  docker-compose -f docker-compose.module.yaml up -d    │      │
│  │                                                       │      │
│  │  适用于：仅需单个审计能力的场景                         │      │
│  │  例如：客户只需要数据接入，不需要后续分析               │      │
│  │  ┌────────┐                                           │      │
│  │  │ FA-01  │ ← 模块独立运行，自带PostgreSQL/Redis      │      │
│  │  └────────┘                                           │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
│  模式2：组网多模块部署 (Networked)                               │
│  ┌──────────────────────────────────────────────────────┐      │
│  │  docker-compose -f docker-compose.network.yaml up -d   │      │
│  │                                                       │      │
│  │  适用于：需要完整审计链路的场景                         │      │
│  │  ┌────────┐ ┌────────┐ ┌────────┐                    │      │
│  │  │ FA-01  │→│ FA-02  │→│ FA-03  │→...                │      │
│  │  └────────┘ └────────┘ └────────┘                    │      │
│  │       │ Kafka消息总线 + 注册中心 + 5大共享平台          │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
│  模式3：K8s集群部署 (Production)                                 │
│  ┌──────────────────────────────────────────────────────┐      │
│  │  helm install audit-platform ./helm/audit-platform      │      │
│  │                                                       │      │
│  │  适用于：生产环境，大规模并发审计                        │      │
│  │  支持：自动扩缩容、滚动更新、多租户隔离                   │      │
│  └──────────────────────────────────────────────────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 CLI工具：模块管理命令

```bash
# 预制菜模块CLI工具 (audit-cli)

# 模块市场操作
audit-cli market list                    # 列出所有可用模块
audit-cli market search "数据接入"        # 搜索模块
audit-cli market info FA-01              # 查看模块详情

# 模块安装
audit-cli module pull FA-01              # 下载模块（代码+Docker镜像）
audit-cli module pull FA-01 --version 1.2.0  # 指定版本

# 模块配置
audit-cli module config FA-01            # 查看模块配置
audit-cli module config FA-01 --edit     # 编辑 custom.yaml
audit-cli module config FA-01 --validate # 验证配置合法性

# 模块生命周期
audit-cli module start FA-01             # 启动模块
audit-cli module stop FA-01              # 停止模块
audit-cli module restart FA-01           # 重启模块
audit-cli module status FA-01            # 查看模块状态
audit-cli module logs FA-01              # 查看模块日志
audit-cli module health FA-01            # 健康检查

# 模块微调
audit-cli module customize FA-01         # 交互式定制向导
audit-cli module test FA-01              # 运行模块测试
audit-cli module validate FA-01          # 验证模块完整性

# 组网编排
audit-cli workflow list                  # 列出所有审计流程
audit-cli workflow run financial_audit_full  # 启动审计流程
audit-cli workflow status financial_audit_full  # 查看流程状态
audit-cli workflow pause financial_audit_full  # 暂停流程
audit-cli workflow resume financial_audit_full # 恢复流程
```

---

## 十、方案价值总结

### 10.1 预制菜模式的核心优势

```
┌─────────────────────────────────────────────────────────────────┐
│               预制菜模式 vs 传统开发模式                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  传统模式：每个客户从零开发                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  需求分析 → 架构设计 → 编码 → 测试 → 部署 → 交付          │   │
│  │  ═══════════════ 3-6个月 ═══════════════════              │   │
│  │  问题：重复造轮子，质量不稳定，知识无法沉淀                 │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  预制菜模式：即取即用 + 微调                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  选择模块 → 配置定制 → 部署 → 交付                        │   │
│  │  ═══════ 1-5天（纯配置级） ═══════                        │   │
│  │  ═══════════ 2-4周（需扩展点开发） ═══════════            │   │
│  │  优势：快速交付、质量可控、持续迭代、知识复用                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 AI组网的独特价值

| 维度 | 价值 |
|------|------|
| **模块复用** | 36个模块通过组网总线共享基础设施，避免每个模块独立搭建数据湖/知识图谱/LLM服务 |
| **动态编排** | 审计流程不再硬编码，通过YAML定义流程DAG，灵活组合模块适应不同客户需求 |
| **松耦合通信** | 模块间通过Kafka异步通信，单个模块故障不影响整体流程，支持独立升级 |
| **配置驱动** | 90%的定制需求通过修改custom.yaml实现，不改核心代码 |
| **版本锁定** | module-lock.yaml保证审计流程的可复现性，满足审计合规要求 |
| **渐进交付** | 从方案文档→等级1骨架→等级2预制菜，分阶段产出，降低风险 |

---

## 附录A：36个模块预制菜优先级排序

```
┌─────────────────────────────────────────────────────────────────┐
│     建议第一批转化的预制菜模块（8个核心模块）                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  优先级排序依据：                                                 │
│  ① 依赖关系（被最多后续模块依赖）                                 │
│  ② 技术代表性（覆盖主要AI技术栈）                                 │
│  ③ 业务价值（直接可交付给客户使用）                               │
│                                                                 │
│  第一批（核心基础模块）：                                         │
│  ┌──────┬────────────────────┬────────┬────────┬───────────┐   │
│  │ 排名  │ 模块               │ 被依赖数 │ 技术栈   │ 预计工期   │   │
│  ├──────┼────────────────────┼────────┼────────┼───────────┤   │
│  │  1   │ FA-01 数据接入 ✓    │ 10+    │ RPA+API│ 已完成     │   │
│  │  2   │ FA-02 数据标准化    │ 10+    │ ML+NLP │ 6周       │   │
│  │  3   │ FA-03 数据湖       │ 全部    │ 数据湖  │ 6周       │   │
│  │  4   │ FA-07 底稿生成     │ 3      │ LLM+RPA│ 10周      │   │
│  │  5   │ FA-10 关联方发现   │ 4      │ KG+GNN │ 10周      │   │
│  │  6   │ CO-01 法规监控     │ 4      │LLM+RAG │ 8周       │   │
│  │  7   │ CO-04 AML监控     │ 2      │ GNN+ML │ 8周       │   │
│  │  8   │ CM-01 持续审计     │ 4      │实时流+ML│ 12周      │   │
│  └──────┴────────────────────┴────────┴────────┴───────────┘   │
│                                                                 │
│  这8个模块覆盖了组网架构的核心：                                   │
│  - AI技术栈全覆盖：ML/NLP/LLM/KG/GNN/RPA/实时流                  │
│  - 业务域覆盖：财务审计/合规审计/持续审计                         │
│  - 依赖骨架：支撑后续28个模块的开发                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 附录B：预制菜模块之间数据交换标准

```yaml
# 审计模块间消息标准格式（JSON Schema）
# 所有模块通过Kafka交换的数据必须遵循此标准

AuditMessage:
  type: object
  required: [header, body]
  properties:
    header:
      type: object
      required: [message_id, timestamp, source_module, target_module, workflow_id]
      properties:
        message_id: {type: string, format: uuid}
        timestamp: {type: string, format: date-time}
        source_module: {type: string, enum: [FA-01, FA-02, ...]}
        target_module: {type: string}
        workflow_id: {type: string}
        correlation_id: {type: string}        # 关联ID，用于追踪整条链
        message_type: {type: string, enum: [data, event, error, status]}
        version: {type: string, pattern: "^\\d+\\.\\d+\\.\\d+$"}
    body:
      type: object
      properties:
        data_ref: {type: string}               # 数据在数据湖中的引用路径
        summary: {type: object}                 # 摘要信息
        status: {type: string, enum: [success, partial, failed]}
        metrics: {type: object}                 # 执行指标
        errors: {type: array}                   # 错误详情
```

---

> **文档结束**  
> **下一步：** 基于此方案，可以开始将剩余的35个方案文档批量转化为等级1骨架，优先转化8个核心模块到等级2（完整预制菜），并与FA-01在组网环境下集成验证。
