# AI组网方案 —— 知识图谱增强设计

> **文档版本：** v1.0  
> **编制日期：** 2026年7月5日  
> **关联文档：** AI组网与预制菜模块设计方案.md（主方案）  
> **核心命题：** 将知识图谱从"一个共享平台"升级为AI组网的"神经网络系统"

---

## 一、认知跃迁：KG从"乘客"到"司机"

### 1.1 两种定位的对比

```
┌─────────────────────────────────────────────────────────────────────┐
│                 KG在AI组网中的角色演化                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  角色A：共享平台（当前定位）                                         │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  AKG是5大平台之一，17个业务模块调用它的API                     │   │
│  │  例：FA-10调用AKG做关联方发现，CO-05调用AKG做洗钱网络分析       │   │
│  │                                                               │   │
│  │  组网总线 ──→ AKG平台 ──→ 业务模块（作为"数据源"被消费）       │   │
│  │                                                               │   │
│  │  本质：KG是AI组网服务的"一个乘客"，和其他4个平台平级            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│                          ▼ 认知跃迁 ▼                               │
│                                                                     │
│  角色B：组网神经系统（增强定位）                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  知识图谱渗入组网架构的每一层，成为"连接器"和"记忆体"          │   │
│  │                                                               │   │
│  │  Layer 5 编排层 ← KG提供流程推荐、最优路径规划               │   │
│  │  Layer 4 模块层 ← KG提供模块语义发现、能力匹配               │   │
│  │  Layer 3 总线层 ← KG替代Redis做语义化模块注册               │   │
│  │  Layer 2 平台层 ← KG作为跨模块统一知识本体                   │   │
│  │  Layer 1 基础层 ← KG作为不可变审计证据链存储                 │   │
│  │                                                               │   │
│  │  本质：KG是AI组网的"神经系统"——既是感知网，也是记忆体         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 四张图谱、四大职责

```
┌─────────────────────────────────────────────────────────────────────┐
│              KG在AI组网中的四张图、四大职责                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  图1：模块能力图谱 (Module Capability Graph)                    │ │
│  │  职责：模块注册与语义发现                                       │ │
│  │  节点：36个预制菜模块                                           │ │
│  │  边：    DEPENDS_ON（依赖）、COMPATIBLE_WITH（兼容）             │ │
│  │        CAN_REPLACE（可替代）、EXTENDS（扩展）                   │ │
│  │  查询：  "找到能做发票审计且支持PDF OCR的模块"                   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  图2：审计流程编排图谱 (Workflow Graph)                          │ │
│  │  职责：流程推荐与最优路径规划                                   │ │
│  │  节点：模块执行实例 + 数据节点                                  │ │
│  │  边：    NEXT_STEP（下一步）、PRODUCES（产出数据）               │ │
│  │        CONSUMES（消费数据）、ALTERNATIVE（替代路径）            │ │
│  │  查询：  "给定客户是制造业+有ERP系统+年度审计，推荐最优流程"      │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  图3：审计统一本体图谱 (Audit Ontology Graph)                    │ │
│  │  职责：跨模块知识共享与语义对齐                                 │ │
│  │  节点：审计实体（公司/科目/凭证/人员/交易/法规/风险...）         │ │
│  │  边：    BELONGS_TO（归属）、RELATED_TO（关联）                  │ │
│  │        CONTROLS（控制）、TRANSFERS_TO（流转）                   │ │
│  │  查询：  "某公司在所有审计模块中的关联关系全景"                   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  图4：审计证据链图谱 (Evidence Chain Graph)                      │ │
│  │  职责：跨模块审计轨迹的不可变记录                               │ │
│  │  节点：审计证据（每步操作的输入/输出/决策）                      │ │
│  │  边：    DERIVED_FROM（溯源）、SUPPORTS（支持结论）              │ │
│  │        CONTRADICTS（矛盾）、VERIFIED_BY（验证）                 │ │
│  │  查询：  "追溯某条审计发现的完整证据链——从原始数据到最终结论"     │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、图1：模块能力图谱 —— 语义化的模块注册中心

### 2.1 为什么用KG替代Redis做注册中心？

```
┌─────────────────────────────────────────────────────────────────┐
│            Redis注册 vs Neo4j注册 —— 能力对比                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Redis：                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  SET module:FA-01 '{"name":"智能数据接入","deps":[]}'     │   │
│  │                                                           │   │
│  │  能做：按ID精确查找，心跳检测                               │   │
│  │  不能做：按能力语义搜索，依赖关系推理，兼容性分析             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Neo4j：                                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  CREATE (m:Module {id:'FA-01', name:'智能数据接入'})      │   │
│  │  CREATE (m)-[:HAS_CAPABILITY]->(:Capability {name:'RPA'}) │   │
│  │  CREATE (m)-[:PRODUCES]->(:DataType {name:'凭证数据'})    │   │
│  │                                                           │   │
│  │  能做：按能力语义搜索，依赖关系推理，兼容性分析              │   │
│  │  也能做：心跳检测（更新 :Module 节点的 last_heartbeat）     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 模块能力图谱的数据模型

```cypher
// ===== 节点类型 =====

// 预制菜模块
(:Module {
    id: "FA-01",
    name: "智能数据接入平台",
    version: "1.2.0",
    maturity: "L2",                    // L1/L2/L3
    category: "financial_audit",
    difficulty: 3,
    status: "ONLINE",                   // ONLINE/OFFLINE/DEGRADED
    last_heartbeat: datetime(),
    port: 8001,
    docker_image: "registry/fa-01:1.2.0",
    code_lines: 5018,
    test_coverage: 0.85
})

// AI能力
(:Capability {name: "RPA", category: "automation"})
(:Capability {name: "ML_Schema_Mapping", category: "machine_learning"})
(:Capability {name: "NLP_Entity_Extraction", category: "nlp"})
(:Capability {name: "GNN_Graph_Analysis", category: "graph_learning"})
(:Capability {name: "LLM_Report_Generation", category: "llm"})
(:Capability {name: "CV_OCR", category: "computer_vision"})
(:Capability {name: "RealTime_Streaming", category: "streaming"})
(:Capability {name: "Blockchain_Evidence", category: "blockchain"})
// ... 30+ AI能力标签

// 数据类型（模块的输入/输出）
(:DataType {name: "凭证数据", schema: "core_voucher"})
(:DataType {name: "科目余额", schema: "core_gl_balance"})
(:DataType {name: "银行函证", schema: "bank_confirmation"})
(:DataType {name: "关联方清单", schema: "related_party_list"})
(:DataType {name: "审计底稿", schema: "audit_workpaper"})
(:DataType {name: "可疑交易告警", schema: "aml_alert"})
// ... 50+ 审计数据类型

// 业务场景
(:Scenario {name: "制造业年度审计"})
(:Scenario {name: "金融业反洗钱审计"})
(:Scenario {name: "IPO三年一期审计"})
(:Scenario {name: "跨境集团联合审计"})

// 技术栈
(:TechStack {name: "Python", version: "3.11"})
(:TechStack {name: "FastAPI", version: "0.104"})
(:TechStack {name: "Neo4j", version: "5.x"})
(:TechStack {name: "PyTorch", version: "2.1"})
// ... 

// ===== 关系类型 =====

// 模块能力关系
(m:Module)-[:HAS_CAPABILITY {proficiency: 0.9}]->(c:Capability)

// 模块依赖关系
(m1:Module)-[:DEPENDS_ON {type: "hard"}]->(m2:Module)     // 硬依赖（必须）
(m1:Module)-[:DEPENDS_ON {type: "soft"}]->(m2:Module)     // 软依赖（建议）
(m1:Module)-[:COMPATIBLE_WITH]->(m2:Module)                // 兼容可协作
(m1:Module)-[:CAN_REPLACE {similarity: 0.85}]->(m2:Module) // 可替代

// 数据流关系
(m:Module)-[:CONSUMES]->(d:DataType)    // 模块消费某类数据
(m:Module)-[:PRODUCES]->(d:DataType)    // 模块产出某类数据

// 场景适配关系
(m:Module)-[:SUITABLE_FOR {score: 0.9}]->(s:Scenario)

// 技术栈关系
(m:Module)-[:USES {role: "primary"}]->(t:TechStack)
```

### 2.3 语义查询示例

```cypher
// 查询1：找所有能做"发票识别"且有"OCR能力"的模块
MATCH (m:Module)-[:HAS_CAPABILITY]->(c:Capability)
WHERE c.name IN ['CV_OCR', 'NLP_Entity_Extraction']
  AND m.maturity IN ['L2', 'L3']
  AND m.status = 'ONLINE'
RETURN m.id, m.name, m.maturity, collect(c.name) AS capabilities
ORDER BY m.maturity DESC

// 查询2：给定当前已部署模块，推荐可以添加到流程中的下一个模块
MATCH (deployed:Module {id: 'FA-02'})-[:PRODUCES]->(d:DataType)
MATCH (next:Module)-[:CONSUMES]->(d)
WHERE NOT next.id IN ['FA-01', 'FA-02']  // 排除已部署的
  AND next.status = 'ONLINE'
RETURN next.id, next.name, d.name AS shared_data,
       [(next)-[:HAS_CAPABILITY]->(c) | c.name] AS capabilities
ORDER BY size(capabilities) DESC
LIMIT 5

// 查询3：找到FA-07（底稿生成）的所有替代模块或兼容模块
MATCH (m:Module {id: 'FA-07'})
MATCH (alt:Module)
WHERE (m)-[:CAN_REPLACE]-(alt) OR (m)-[:COMPATIBLE_WITH]-(alt)
RETURN alt.id, alt.name, alt.maturity

// 查询4：给定业务场景，推荐完整的模块链
// "制造业年度审计需要哪些模块，按什么顺序？"
MATCH path = (start:Module)-[:DEPENDS_ON|PRODUCES|CONSUMES*1..5]->(end:Module)
WHERE start.id = 'FA-01'  // 数据接入永远是起点
  AND EXISTS {
    MATCH (end)-[:SUITABLE_FOR]->(:Scenario {name: '制造业年度审计'})
  }
RETURN [n IN nodes(path) | n.id] AS module_chain
ORDER BY length(path)
LIMIT 3

// 查询5：能力缺口分析——"缺少什么模块才能完成ESG审计全流程？"
MATCH (required:Capability)
WHERE required.name IN ['CV_Satellite_Imagery', 'ESG_Factor_Calculation', 'Greenwashing_Detection']
  AND NOT EXISTS {
    MATCH (m:Module)-[:HAS_CAPABILITY]->(required)
    WHERE m.status = 'ONLINE'
  }
RETURN required.name AS missing_capability,
       "建议开发或引入此能力的预制菜模块" AS recommendation
```

---

## 三、图2：审计流程编排图谱 —— 从DAG到智能推荐

### 3.1 编排引擎的进化

```
┌─────────────────────────────────────────────────────────────────┐
│               编排引擎的三级进化                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Level 1：静态DAG编排（当前设计）                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  YAML定义流程 → 拓扑排序 → 按序执行                       │   │
│  │  局限：流程是写死的，不会根据数据特征自适应调整              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Level 2：KG增强的条件分支编排                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  KG存储历史执行数据 → 根据前置模块输出 → 动态选择下一模块   │   │
│  │                                                           │   │
│  │  例：                                                     │   │
│  │  FA-02标准化后发现数据质量评分=0.98 → 跳过FA-03详细校验   │   │
│  │  FA-02标准化后发现数据质量评分=0.65 → 触发FA-03全量校验   │   │
│  │  FA-10关联方发现输出关联方>100个 → 启动FA-11定价分析      │   │
│  │  FA-10关联方发现输出关联方<5个 → 跳过FA-11,直接FA-12     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Level 3：GNN驱动的流程优化推荐                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  基于历史审计项目数据训练GNN模型：                          │   │
│  │                                                           │   │
│  │  输入特征：                                                │   │
│  │  - 客户行业、规模、历史审计发现                            │   │
│  │  - 已有数据源类型、数据量级                                │   │
│  │  - 审计目标、风险偏好、时间预算                            │   │
│  │                                                           │   │
│  │  GNN输出：                                                 │   │
│  │  - 推荐模块链（最优路径）                                  │   │
│  │  - 每个模块的预估执行时间                                  │   │
│  │  - 每个模块的预估发现风险概率                              │   │
│  │  - 替代路径（如果某模块不可用）                            │   │
│  │                                                           │   │
│  │  模型架构：GraphSAGE编码器 + 注意力池化 + MLP解码器        │   │
│  │  训练数据：历史审计项目的流程执行日志                       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 流程编排图谱的数据模型

```cypher
// 流程定义节点
(:Workflow {
    id: "financial_audit_v2",
    name: "财务报表审计流程v2",
    version: "2.1",
    created_at: datetime(),
    avg_execution_time_minutes: 45,
    success_rate: 0.94
})

// 流程步骤（模块实例 + 运行时参数）
(:Step {
    id: "step_data_ingestion",
    order: 1,
    module_id: "FA-01",
    params: '{"client_id": "auto", "fiscal_year": 2025}',
    timeout_minutes: 30,
    retry_policy: "exponential_backoff_3"
})

// 数据节点（中间产物）
(:DataArtifact {
    id: "artifact_voucher_2025",
    type: "normalized_voucher",
    row_count: 1500000,
    quality_score: 0.92,
    size_mb: 250
})

// 决策节点（条件分支）
(:DecisionPoint {
    id: "decision_quality_gate",
    rule: "quality_score < 0.8 THEN full_check ELSE skip_detailed_check",
    evaluated_at: datetime()
})

// ===== 关系 =====

// 流程结构
(w:Workflow)-[:CONTAINS]->(s:Step)
(s1:Step)-[:NEXT {condition: "always"}]->(s2:Step)
(s1:Step)-[:NEXT {condition: "quality_score < 0.8"}]->(s3:Step)

// 数据流
(s:Step)-[:PRODUCES]->(a:DataArtifact)
(s:Step)-[:CONSUMES]->(a:DataArtifact)

// 决策分支
(s:Step)-[:LEADS_TO]->(d:DecisionPoint)
(d:DecisionPoint)-[:BRANCH {condition: "true"}]->(s_true:Step)
(d:DecisionPoint)-[:BRANCH {condition: "false"}]->(s_false:Step)

// 历史执行记录
(s:Step)-[:EXECUTED_IN {duration_ms: 12345, status: "success", 
                         cpu_usage: 0.65, memory_mb: 2048}]->(run:ExecutionRun)
```

### 3.3 基于KG的流程优化查询

```cypher
// 查询1：找到某客户最适合的审计流程
// 基于相似客户的历史执行数据推荐
MATCH (customer:Client {industry: '制造业', revenue_range: '10-50亿'})
MATCH (similar:Client)
WHERE similar.industry = customer.industry
  AND abs(similar.revenue - customer.revenue) / customer.revenue < 0.3

MATCH (similar)-[:USED_WORKFLOW]->(w:Workflow)
MATCH (w)-[:CONTAINS]->(s:Step)
MATCH (s)-[:EXECUTED_IN]->(run:ExecutionRun)
WHERE run.status = 'success'

WITH w, avg(run.duration_ms) AS avg_duration,
     count(DISTINCT similar) AS usage_count,
     collect(DISTINCT s.module_id) AS module_chain

RETURN w.name, avg_duration, usage_count, module_chain
ORDER BY usage_count DESC, avg_duration ASC
LIMIT 3

// 查询2：流程瓶颈分析
MATCH (s:Step)-[:EXECUTED_IN]->(run:ExecutionRun)
WHERE run.status = 'success'
WITH s.module_id AS module, avg(run.duration_ms) AS avg_dur, count(run) AS runs
ORDER BY avg_dur DESC
LIMIT 5

MATCH (m:Module {id: module})-[:HAS_CAPABILITY]->(c:Capability)
MATCH (m)-[:CAN_REPLACE]->(alt:Module)-[:HAS_CAPABILITY]->(c)

RETURN module, avg_dur, runs,
       collect(DISTINCT alt.id) AS faster_alternatives,
       collect(DISTINCT c.name) AS shared_capabilities

// 查询3：数据溯源——"这份底稿的结论追溯到哪些原始凭证？"
MATCH path = (wp:DataArtifact {type: 'audit_workpaper', id: 'WP-2025-003'})
            -[:DERIVED_FROM*1..10]->
            (source:DataArtifact {type: 'raw_voucher'})
RETURN [n IN nodes(path) | 
  {type: n.type, id: n.id, module: n.produced_by}] AS derivation_chain,
  length(path) AS derivation_depth
```

---

## 四、图3：审计统一本体图谱 —— 跨模块的"通用语言"

### 4.1 核心问题：模块间的语义鸿沟

```
┌─────────────────────────────────────────────────────────────────┐
│                  模块间语义鸿沟                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  问题：不同模块对同一实体的称呼不一致                             │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  FA-01（数据接入）管它叫："核心企业" (core_company)       │    │
│  │  FA-10（关联方）管它叫："被审计实体" (audited_entity)     │    │
│  │  FA-04（函证） 管它叫："被询证方" (confirming_party)    │    │
│  │  CO-04（AML） 管它叫："客户" (customer)                 │    │
│  │  SC-01（供应链）管它叫："采购方" (buyer)                 │    │
│  │                                                        │    │
│  │  它们说的都是同一个公司！但各模块用自己的命名               │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
│  解决方案：审计统一本体图谱                                      │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  (:Company {unified_id: "C-20250001"})                  │    │
│  │      ↑                                                  │    │
│  │      ├── FA-01 视其为 :CoreCompany                      │    │
│  │      ├── FA-10 视其为 :AuditedEntity                    │    │
│  │      ├── FA-04 视其为 :ConfirmingParty                  │    │
│  │      ├── CO-04 视其为 :Customer                         │    │
│  │      └── SC-01 视其为 :Buyer                            │    │
│  │                                                        │    │
│  │  各模块用自己的名字，但通过本体图找到统一ID               │    │
│  └────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 审计统一本体模型

```cypher
// ===== 五层本体架构 =====

// Layer 1: 核心实体层（所有审计域共享）
(:Entity {unified_id: "E-xxxx"})
├── (:Organization)      // 组织（公司/子公司/分支机构/部门）
├── (:Person)            // 自然人（高管/股东/员工/关联人）
├── (:Account)           // 会计科目
├── (:Transaction)       // 交易/凭证
├── (:Asset)             // 资产（固定/无形/金融）
├── (:Contract)          // 合同/协议
├── (:Regulation)        // 法规/准则
├── (:Risk)              // 风险
└── (:Evidence)          // 审计证据

// Layer 2: 关系层
(:Organization)-[:CONTROLS]->(:Organization)           // 股权控制
(:Organization)-[:EMPLOYS]->(:Person)                  // 雇佣关系
(:Person)-[:RELATED_TO {type: "family"}]->(:Person)    // 亲属关系
(:Transaction)-[:BETWEEN]->(:Organization)              // 交易对手
(:Transaction)-[:POSTED_TO]->(:Account)                // 记账科目
(:Transaction)-[:AUTHORIZED_BY]->(:Person)              // 审批人
(:Contract)-[:BINDS]->(:Organization)                   // 合同约束
(:Asset)-[:OWNED_BY]->(:Organization)                   // 资产归属
(:Regulation)-[:APPLIES_TO]->(:Transaction)             // 法规适用
(:Risk)-[:ASSOCIATED_WITH]->(:Entity)                   // 风险关联
(:Evidence)-[:SUPPORTS]->(:Transaction)                 // 证据支持

// Layer 3: 模块上下文层（每个模块的"视角"）
// FA-01 数据接入视角
(:Organization)-[:REGISTERED_AS {module: "FA-01"}]->(:CoreCompany)
// FA-10 关联方视角
(:Organization)-[:IDENTIFIED_AS {module: "FA-10"}]->(:RelatedParty)
// FA-04 函证视角
(:Organization)-[:CONFIRMED_AS {module: "FA-04"}]->(:ConfirmingParty)
// CO-04 AML视角
(:Person)-[:FLAGGED_AS {module: "CO-04"}]->(:PEP_Customer)
// SC-01 供应链视角
(:Organization)-[:EVALUATED_AS {module: "SC-01"}]->(:Supplier)

// Layer 4: 时间线层
(:Entity)-[:AT_TIME {timestamp: datetime()}]->(:Snapshot)
// 保留同一实体在不同时间点的快照，支持时序分析

// Layer 5: 推理规则层
// 规则示例：如果A公司持有B公司51%股权，且B公司持有C公司30%股权
// 则推理：A公司通过B公司间接控制C公司
(:Organization {id: "A"})-[:CONTROLS {percentage: 51}]->(:Organization {id: "B"})
(:Organization {id: "B"})-[:CONTROLS {percentage: 30}]->(:Organization {id: "C"})
// 推理边（由规则引擎自动生成）：
// (:Organization {id: "A"})-[:INDIRECTLY_CONTROLS]->(:Organization {id: "C"})
```

### 4.3 跨模块关联查询示例

```cypher
// 查询：获取某公司在所有36个模块中的"全景画像"
MATCH (org:Organization {unified_id: "C-20250001"})

// 财务视角（FA模块）
OPTIONAL MATCH (org)-[:REGISTERED_AS]->(cc:CoreCompany)
OPTIONAL MATCH (cc)<-[:AUDITED]-(:AuditWorkpaper)

// 关联方视角（FA-10）
OPTIONAL MATCH (org)-[:IDENTIFIED_AS]->(rp:RelatedParty)
OPTIONAL MATCH (rp)-[:RELATED_TO]->(related:Organization)

// 函证视角（FA-04）
OPTIONAL MATCH (org)-[:CONFIRMED_AS]->(cp:ConfirmingParty)
OPTIONAL MATCH (cp)<-[:SENT_TO]-(c:Confirmation)

// 合规视角（CO模块）
OPTIONAL MATCH (org)-[:REGISTERED_IN]->(j:Jurisdiction)
OPTIONAL MATCH (j)-[:REQUIRES]->(r:Regulation)

// 供应链视角（SC-01）
OPTIONAL MATCH (org)-[:EVALUATED_AS]->(s:Supplier)
OPTIONAL MATCH (s)-[:HAS_RISK_SCORE]->(rs:RiskScore)

// 税务视角（TA模块）
OPTIONAL MATCH (org)-[:ISSUED]->(inv:Invoice)

RETURN org.name AS company,
       collect(DISTINCT rp.id) AS related_parties,
       count(DISTINCT c) AS confirmation_count,
       collect(DISTINCT r.name) AS applicable_regulations,
       rs.score AS supplier_risk_score,
       count(DISTINCT inv) AS invoice_count
```

---

## 五、图4：审计证据链图谱 —— 不可篡改的审计轨迹

### 5.1 设计动机

```
┌─────────────────────────────────────────────────────────────────┐
│                    为什么需要证据链图谱？                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  审计的本质：                                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  原始数据 → 分析处理 → 中间结论 → 最终审计意见             │   │
│  │                                                           │   │
│  │  在AI组网中，这个链条被拆分到N个模块：                       │   │
│  │                                                           │   │
│  │  FA-01采集 → FA-02清洗 → FA-03入库 → FA-10分析           │   │
│  │     → FA-07底稿 → FA-08勾稽 → FA-09复核                  │   │
│  │                                                           │   │
│  │  问题：当审计师看到最终底稿中的一条调整建议时，             │   │
│  │  她如何快速追溯到原始凭证？                               │   │
│  │  她如何确认处理过程没有被篡改？                            │   │
│  │  她如何知道中间经过了哪些AI模块的处理？                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  证据链图谱 = 区块链存证(BCE) + 知识图谱(AKG) 的融合             │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  区块链提供：不可篡改的时间戳 + 数据哈希链上存证            │   │
│  │  知识图谱提供：可查询的关联关系 + 图遍历追溯               │   │
│  │                                                           │   │
│  │  两者结合：每个证据节点都有链上哈希 → 任何篡改会被发现     │   │
│  │           所有证据节点连成图 → 任意两点之间可追溯           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 证据链图谱数据模型

```cypher
// 证据节点（每个模块执行的输入/输出/决策都产生证据节点）
(:Evidence {
    id: "EV-20250705-001",
    type: "MODULE_INPUT",              // MODULE_INPUT/MODULE_OUTPUT/DECISION/APPROVAL/ADJUSTMENT
    module_id: "FA-01",
    workflow_run_id: "RUN-20250705-001",
    timestamp: datetime(),
    data_hash: "sha256:abc123...",     // 数据摘要（链上存证）
    blockchain_tx: "0x1234...",        // 链上交易哈希
    operator: "system",                // 操作者（system/auditor_name）
    description: "从SAP系统采集2025年度凭证数据",
    data_ref: "s3://audit-lake/raw/2025/sap_vouchers.parquet"
})

// 证据节点之间的关系
(ev1:Evidence)-[:DERIVED_FROM {
    transformation: "NORMALIZATION",    // 经过了什么处理
    module: "FA-02",
    rules_applied: ["date_format_unify", "currency_convert"]
}]->(ev2:Evidence)

(ev1:Evidence)-[:SUPPORTS {
    confidence: 0.95,
    reasoning: "数据质量评分0.92，高于阈值0.85"
}]->(finding:AuditFinding)

(ev1:Evidence)-[:CONTRADICTS {
    severity: "HIGH",
    description: "银行函证余额与账面余额差异超过重要性水平"
}]->(ev2:Evidence)

// 人工决策节点
(ev:Evidence)-[:APPROVED_BY {
    timestamp: datetime(),
    auditor_id: "AUD-001",
    comment: "确认关联方清单完整性"
}]->(approval:ApprovalDecision)

// 调整分录
(:Adjustment {
    id: "ADJ-20250705-015",
    amount: -15000000,
    account: "应收账款",
    reason: "需计提坏账准备",
    evidence_ref: "EV-20250705-089"
})-[:SUGGESTED_BY]->(:Evidence {module_id: "FA-09"})
```

### 5.3 证据追溯查询

```cypher
// 查询1：完整证据链追溯——"从最终审计意见追溯到原始数据"
MATCH path = (opinion:AuditOpinion {id: "OP-2025-Q4"})
            -[:SUPPORTED_BY*1..20]->
            (raw:Evidence {type: "MODULE_INPUT", module_id: "FA-01"})

WITH path, [n IN nodes(path) WHERE n:Module | n.id] AS modules_chain
RETURN 
  [n IN nodes(path) | {
    type: labels(n)[0],
    module: n.module_id,
    timestamp: n.timestamp,
    hash: n.data_hash
  }] AS evidence_chain,
  length(path) AS chain_length,
  modules_chain

// 查询2：异常检测——"哪个模块的处理改变了数据的关键属性？"
MATCH (input:Evidence {type: "MODULE_INPUT"})
      -[:DERIVED_FROM]->(output:Evidence {type: "MODULE_OUTPUT"})
WHERE input.data_hash <> output.data_hash  // 数据确实被修改了
  AND output.module_id <> 'FA-01'          // 不是原始采集
RETURN input.module_id AS from_module,
       output.module_id AS to_module,
       output.description AS what_changed,
       output.rules_applied AS rules

// 查询3：矛盾发现——"不同模块对同一实体得出了矛盾结论"
MATCH (e1:Evidence)-[:ABOUT]->(entity:Organization)
MATCH (e2:Evidence)-[:ABOUT]->(entity)
MATCH (e1)-[:CONTRADICTS]->(e2)
RETURN entity.name, 
       e1.module_id AS module_a, e1.description AS conclusion_a,
       e2.module_id AS module_b, e2.description AS conclusion_b,
       e1.severity
```

---

## 六、四图协同：AI组网的知识图谱全景

### 6.1 四图之间的交互关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                      四张图谱的协同关系                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│                        ┌─────────────────────┐                      │
│                        │   图1：模块能力图谱    │                      │
│                        │   (注册中心)          │                      │
│                        │   模块+能力+依赖      │                      │
│                        └──────────┬──────────┘                      │
│                                   │                                  │
│                    "哪些模块可以组合？"                              │
│                                   │                                  │
│                                   ▼                                  │
│                        ┌─────────────────────┐                      │
│                        │   图2：流程编排图谱    │                      │
│                        │   (编排引擎)          │                      │
│                        │   流程+步骤+决策      │                      │
│                        └──────────┬──────────┘                      │
│                                   │                                  │
│              ┌────────────────────┼────────────────────┐             │
│              │                    │                    │             │
│     "执行中用哪些         "各模块产出什么       "如何追溯            │
│      统一实体？"          知识？"              全过程？"            │
│              │                    │                    │             │
│              ▼                    ▼                    ▼             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │ 图3：统一本体图谱 │  │ 图3与图4的交叉点 │  │ 图4：证据链图谱   │     │
│  │ (跨模块语义对齐)  │  │ (知识沉淀+留痕)  │  │ (不可变审计轨迹)  │     │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘     │
│                                                                     │
│  协同流程示例：                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  1. 图1 → 发现FA-01、FA-02、FA-10可以组成关联方审计链        │   │
│  │  2. 图2 → 编排执行这个链，条件分支自动决策                   │   │
│  │  3. 图3 → FA-01用"核心企业"，FA-10用"关联方"，统一ID对齐    │   │
│  │  4. 图4 → 每一步操作产生不可变证据，哈希上链，可完整追溯     │   │
│  │                                                                 │
│  │  四张图共享底层节点（Module、Organization、Evidence），        │   │
│  │  逻辑上分开存储但物理上可存储在同一个Neo4j集群的不同数据库中   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.2 实现路径

```
┌─────────────────────────────────────────────────────────────────┐
│                   KG增强的阶段性实现路径                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase 1 (M1-M3)：图1模块能力图谱 + 图3基础本体                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  - 将36个方案的module.yaml导入Neo4j                      │   │
│  │  - 建立模块→能力→数据类型的图谱关系                        │   │
│  │  - 替换Redis注册中心为Neo4j（保留Redis做缓存）            │   │
│  │  - 建立基础审计本体（20+实体类型）                        │   │
│  │  - 实现模块语义搜索API                                    │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Phase 2 (M4-M6)：图2流程编排                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  - 将审计流程YAML转为图谱结构                              │   │
│  │  - 实现条件分支的动态决策                                  │   │
│  │  - 基于历史数据训练流程优化GNN模型                         │   │
│  │  - 实现流程推荐API（输入客户画像→输出推荐模块链）          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Phase 3 (M7-M12)：图4证据链 + 图3全量本体                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  - 每个模块执行自动产生证据节点                            │   │
│  │  - 证据哈希上链（BCE平台）                                 │   │
│  │  - 建立完整的审计统一本体（50+实体类型，100+关系类型）     │   │
│  │  - 实现端到端证据链追溯（从原始数据到审计意见）             │   │
│  │  - 实现跨模块矛盾发现和一致性检查                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Phase 4 (M13+)：持续进化                                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  - 图1：模块市场推荐系统（基于使用模式推荐模块组合）       │   │
│  │  - 图2：自主审计Agent（LLM+KG联合规划审计策略）           │   │
│  │  - 图3：自动本体学习（从新数据中自动发现新实体类型）       │   │
│  │  - 图4：智能异常检测（GNN发现证据链中的异常模式）          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 七、与原方案的对照：哪些改变、哪些不变

```
┌─────────────────────────────────────────────────────────────────┐
│                KG增强方案 vs 原方案的变更对照                      │
├──────────────────────────────┬──────────────────────────────────┤
│  原方案组件                   │  KG增强后的变化                   │
├──────────────────────────────┼──────────────────────────────────┤
│  Redis注册中心               │  保留Redis做热数据缓存             │
│                              │  → Neo4j做语义化注册主存储         │
├──────────────────────────────┼──────────────────────────────────┤
│  YAML静态流程定义            │  保留YAML做基础流程模板            │
│                              │  → KG做动态条件分支和GNN推荐       │
├──────────────────────────────┼──────────────────────────────────┤
│  AKG平台（业务KG）           │  不变，仍然是17个业务模块的KG底座  │
│                              │  → 新增组网KG（独立实例）          │
├──────────────────────────────┼──────────────────────────────────┤
│  BCE区块链存证               │  不变，仍负责哈希上链              │
│                              │  → KG负责存证节点的图关联          │
├──────────────────────────────┼──────────────────────────────────┤
│  Kafka消息总线               │  不变，仍是实时通信骨干            │
│                              │  → KG不替代Kafka（不适合高频消息）  │
├──────────────────────────────┼──────────────────────────────────┤
│  module.yaml元数据           │  不变，仍是模块定义的标准格式       │
│                              │  → 增加自动导入Neo4j的脚本         │
├──────────────────────────────┼──────────────────────────────────┤
│  预制菜模块目录结构           │  完全不变                         │
│                              │  → 每个模块的engine.py不感知KG     │
├──────────────────────────────┼──────────────────────────────────┤
│  36个方案文档                │  完全不变                         │
│                              │  → SKG作为组网基础设施，不修改业务  │
└──────────────────────────────┴──────────────────────────────────┘

核心原则：KG增强是"组网基础设施"的升级，不侵入36个预制菜模块的业务代码。
        模块只需要在module.yaml中声明自己的能力和数据类型，
        KG层自动构建图结构，模块代码完全不感知KG的存在。
```

---

## 八、关键设计决策：KG vs Kafka的职责边界

```
┌─────────────────────────────────────────────────────────────────┐
│                 KG vs Kafka —— 各司其职                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Kafka（消息总线）：                                             │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  职责：实时数据流传递                                      │   │
│  │  时机：模块间"这一刻"发生了什么                            │   │
│  │  场景：                                                   │   │
│  │    - FA-01采集完成 → 发送data.ingested事件 → FA-02启动   │   │
│  │    - 100万条凭证数据 → 通过Kafka流转（不经过KG）           │   │
│  │  特点：高吞吐、低延迟、流式                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  KG（知识图谱）：                                               │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  职责：结构化知识存储与推理                                │   │
│  │  时机：模块间"是什么关系"、"之前发生过什么"               │   │
│  │  场景：                                                   │   │
│  │    - "这个客户在哪些模块中被分析过？结果如何？"            │   │
│  │    - "FA-10发现的关联方和FA-04发送的函证接收方是否匹配？" │   │
│  │    - "从原始凭证到审计意见的完整证据链是什么？"            │   │
│  │  特点：语义化、关联查询、图推理                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ⚠ 关键认知：KG不能替代Kafka做实时消息传递，                    │
│               Kafka不能替代KG做语义查询和图推理。                │
│              两者互补，不是竞争关系。                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 附录：Neo4j部署方案

```yaml
# KG增强方案的Neo4j集群部署
neo4j:
  mode: "cluster"                     # 集群模式（非单机）
  instances:
    core: 3                           # 核心节点（读写）
    read_replica: 2                   # 只读副本（查询加速）
  
  databases:
    - name: "module_graph"            # 图1：模块能力图谱
      purpose: "registry"
    - name: "workflow_graph"          # 图2：编排图谱
      purpose: "orchestration"
    - name: "ontology_graph"          # 图3：统一本体图谱
      purpose: "semantic_alignment"
    - name: "evidence_graph"          # 图4：证据链图谱
      purpose: "audit_trail"
  
  # 图1和2对延迟敏感（参与在线流程），使用高性能配置
  # 图3和4是批量写入+查询场景，使用标准配置
  resource_tiers:
    high_performance:                  # 用于 module_graph + workflow_graph
      cpu: "8"
      memory: "32Gi"
      storage: "200Gi SSD"
    standard:                          # 用于 ontology_graph + evidence_graph
      cpu: "4"
      memory: "16Gi"
      storage: "500Gi SSD"

  # Neo4j + Redis 双活设计
  redis_cache:
    purpose: "hot_cache"              # Redis缓存Neo4j查询热点
    ttl: 60                           # 缓存60秒
    patterns:
      - "MATCH (m:Module) WHERE m.status = 'ONLINE'"  # 在线模块列表
      - "MATCH (m:Module)-[:DEPENDS_ON]->(d:Module)"   # 依赖关系
```

---

> **文档结束**  
> **结论：** KG在AI组网中不仅是"一个共享平台"，而是渗透到架构每一层的"神经系统"。它不替代任何现有组件（Kafka/Redis/BCE），而是在语义层面对它们进行增强——让模块发现更智能、流程编排更灵活、跨模块知识可共享、审计轨迹可追溯。
