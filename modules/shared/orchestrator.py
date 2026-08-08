"""智能审计编排引擎 —— 需求解析 → 模块组网 → 拓扑执行 → 结果汇总。

工作流程：
1. AuditPlanner：解析自然语言审计需求，匹配模块，根据依赖补全，生成执行DAG
2. ContractValidator：按 network_schema.json 校验接口契约一致性
3. TopoExecutor：拓扑排序后逐模块执行 pipeline.run()，按接口契约传递数据
4. ReportGenerator：汇总各模块输出，生成审计报告
"""
from __future__ import annotations

import importlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from modules.shared.contract import load_contracts, ModuleContract

import json
import os
from typing import Optional

# DeepSeek LLM 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-flash"


# ======================================================================
# 静态数据：模块家族映射、关键词字典、数据流边
# ======================================================================

FAMILY_MAP: dict[str, str] = {
    "fa": "财务审计",
    "co": "合规审计",
    "ip": "IPO审计",
    "cm": "持续审计",
    "fo": "舞弊审计",
    "it": "IT审计",
    "ta": "税务审计",
    "sc": "供应链审计",
    "es": "ESG审计",
    "fi": "金融审计",
    "ia": "内部审计",
    "cb": "跨境审计",
}


def _family_of(slug: str) -> str:
    """根据 slug 前缀推断技术家族。"""
    prefix = slug.split("_")[0] if "_" in slug else slug[:2]
    return FAMILY_MAP.get(prefix, "通用审计")


# 模块名称快查（避免每次加载 schema 才能拿到名字）
MODULE_NAMES: dict[str, str] = {
    "fa_02": "多源数据自动标准化",
    "fa_03": "审计数据湖建设",
    "fa_04": "智能函证管理平台",
    "fa_05": "区块链银行函证",
    "fa_06": "AI函证差异智能分析",
    "fa_07": "智能底稿自动生成平台",
    "fa_08": "底稿自动勾稽检查",
    "fa_09": "AI底稿质量复核助手",
    "fa_10": "知识图谱关联方发现引擎",
    "fa_11": "关联交易定价公允性AI分析",
    "fa_12": "关联交易披露完整性检查",
    "co_01": "全球法规智能监控平台",
    "co_02": "AI法规影响评估引擎",
    "co_03": "合规审计程序自动更新",
    "co_04": "AML智能交易监控引擎",
    "co_05": "知识图谱洗钱网络发现",
    "co_06": "AI可疑交易报告自动生成",
    "co_07": "AI数据资产自动发现与分类",
    "co_08": "知识图谱数据流分析",
    "co_09": "隐私合规自动审计引擎",
    "ip_01": "IPO审计智能加速平台",
    "ip_02": "AI监管反馈智能回复系统",
    "ip_03": "知识图谱历史沿革梳理系统",
    "ip_04": "AI财务规范性智能诊断系统",
    "ip_05": "IPO案例知识库与RAG系统",
    "ip_06": "整改方案AI推荐引擎",
    "cm_01": "持续审计技术平台",
    "cm_02": "智能预警分级与自动处理系统",
    "cm_03": "持续审计方法论框架",
    "cm_04": "持续审计价值量化模型",
    "cm_05": "持续审计仪表板",
    "fo_01": "全量交易智能舞弊扫描",
    "fo_02": "知识图谱舞弊网络分析",
    "fo_03": "NLP文本舞弊信号检测",
    "fo_04": "AI电子取证平台",
    "fo_05": "多语言智能翻译与分析",
    "fo_06": "证据链智能构建",
    "it_01": "IT审计自动化平台",
    "it_02": "AI配置合规扫描引擎",
    "it_03": "AI代码审计助手",
    "it_04": "IT持续审计平台",
    "it_05": "区块链审计日志存证",
    "ta_01": "AI发票智能审计平台",
    "ta_02": "发票四单自动匹配引擎",
    "ta_03": "进项税额转出AI计算",
    "ta_04": "AI转让定价文档自动生成",
    "ta_05": "ML可比公司智能筛选",
    "ta_06": "知识图谱全球关联交易分析",
    "sc_01": "供应商风险智能评分平台",
    "sc_02": "知识图谱供应链网络分析",
    "sc_03": "供应商持续风险监控平台",
    "sc_04": "ML采购价格异常检测平台",
    "sc_05": "AI采购价格基准平台",
    "es_01": "ESG多源数据智能采集平台",
    "es_02": "AI碳排放自动核算引擎",
    "es_03": "卫星遥感AI环境监测平台",
    "es_04": "知识图谱绿色漂洗检测平台",
    "es_05": "ESG审计知识库与AI助手",
    "es_06": "AI-ESG审计方法论引擎",
    "fi_01": "AI信贷资产质量评估引擎",
    "fi_02": "知识图谱担保链风险分析系统",
    "fi_03": "ML贷款违约预测验证系统",
    "fi_04": "监管报表智能核对平台",
    "fi_05": "AI监管口径自动更新系统",
    "ia_01": "动态风险地图与智能审计计划",
    "ia_02": "持续风险监控平台",
    "ia_03": "审计资源智能分配引擎",
    "ia_04": "审计价值仪表板",
    "ia_05": "AI驱动的管理建议书",
    "ia_06": "内审价值量化模型",
    "ia_07": "智能整改跟踪平台",
    "ia_08": "整改效果自动验证",
    "cb_01": "联邦学习跨境审计平台",
    "cb_02": "数据脱敏网关与合规路由系统",
    "cb_03": "多法域合规知识库",
    "cb_04": "AI多准则自动转换引擎",
    "cb_05": "AI多语言审计协作平台",
    "cb_06": "集团审计智能协作平台",
}

# 每个模块关联的关键词（用于需求文本匹配）
MODULE_KEYWORDS: dict[str, list[str]] = {
    # FA - 财务审计
    "fa_02": ["数据标准化", "多源数据", "数据接入", "ETL", "字段映射"],
    "fa_03": ["数据湖", "数据仓库", "数据存储", "ODS", "DWD", "ADS"],
    "fa_04": ["函证", "银行函证", "函证管理"],
    "fa_05": ["区块链函证", "链上函证"],
    "fa_06": ["函证差异", "函证分析"],
    "fa_07": ["底稿", "审计底稿", "工作底稿", "底稿生成"],
    "fa_08": ["底稿勾稽", "勾稽检查"],
    "fa_09": ["底稿复核", "底稿质量"],
    "fa_10": ["关联方", "关联关系", "股权", "关联交易发现", "关联方识别"],
    "fa_11": ["定价公允", "关联交易定价", "公允性", "转让定价", "定价分析"],
    "fa_12": ["披露完整性", "关联交易披露", "信息披露", "披露检查"],
    # CO - 合规审计
    "co_01": ["法规", "法规监控", "合规", "监管", "法规变更"],
    "co_02": ["法规影响", "影响评估"],
    "co_03": ["合规程序", "审计程序更新"],
    "co_04": ["反洗钱", "AML", "可疑交易", "交易监控"],
    "co_05": ["洗钱网络", "洗钱", "资金网络", "知识图谱洗钱"],
    "co_06": ["可疑交易报告", "SAR", "STR", "报告生成"],
    "co_07": ["数据资产", "数据分类", "数据发现"],
    "co_08": ["数据流", "数据血缘"],
    "co_09": ["隐私合规", "数据隐私", "GDPR"],
    # IP - IPO审计
    "ip_01": ["IPO", "上市", "财务规范", "历史沿革", "IPO审计"],
    "ip_02": ["监管反馈", "问询函", "反馈回复"],
    "ip_03": ["历史沿革", "股权沿革", "工商变更"],
    "ip_04": ["财务规范性", "财务诊断"],
    "ip_05": ["IPO案例", "案例知识库"],
    "ip_06": ["整改方案", "整改推荐"],
    # CM - 持续审计
    "cm_01": ["持续审计", "实时监控", "实时审计"],
    "cm_02": ["预警", "预警分级", "智能预警"],
    "cm_03": ["方法论", "审计方法论"],
    "cm_04": ["价值量化", "审计价值"],
    "cm_05": ["仪表板", "看板", "dashboard"],
    # FO - 舞弊审计
    "fo_01": ["舞弊扫描", "全量交易", "舞弊检测"],
    "fo_02": ["舞弊网络", "舞弊图谱"],
    "fo_03": ["文本舞弊", "NLP舞弊"],
    "fo_04": ["电子取证", "取证"],
    "fo_05": ["多语言", "翻译"],
    "fo_06": ["证据链", "证据构建"],
    # IT - IT审计
    "it_01": ["IT审计", "系统审计"],
    "it_02": ["配置合规", "配置扫描"],
    "it_03": ["代码审计", "源代码"],
    "it_04": ["IT持续审计", "日志审计"],
    "it_05": ["区块链存证", "日志存证"],
    # TA - 税务审计
    "ta_01": ["发票", "发票审计", "OCR"],
    "ta_02": ["四单匹配", "发票匹配"],
    "ta_03": ["进项税", "税额转出"],
    "ta_04": ["转让定价文档", "定价文档"],
    "ta_05": ["可比公司", "ML筛选"],
    "ta_06": ["全球关联交易", "跨国关联"],
    # SC - 供应链审计
    "sc_01": ["供应商风险", "供应商评分"],
    "sc_02": ["供应链", "供应链网络"],
    "sc_03": ["供应商监控", "持续监控供应商"],
    "sc_04": ["采购价格", "价格异常"],
    "sc_05": ["价格基准", "采购基准"],
    # ES - ESG审计
    "es_01": ["ESG数据", "ESG采集"],
    "es_02": ["碳排放", "碳核算"],
    "es_03": ["遥感", "卫星", "环境监测"],
    "es_04": ["绿色漂洗", "漂绿"],
    "es_05": ["ESG知识库"],
    "es_06": ["ESG方法论"],
    # FI - 金融审计
    "fi_01": ["信贷资产", "信贷质量"],
    "fi_02": ["担保链", "担保风险"],
    "fi_03": ["违约预测", "贷款违约"],
    "fi_04": ["监管报表", "报表核对"],
    "fi_05": ["监管口径", "口径更新"],
    # IA - 内部审计
    "ia_01": ["风险地图", "审计计划", "风险评估"],
    "ia_02": ["风险监控", "持续风险"],
    "ia_03": ["资源分配", "审计资源"],
    "ia_04": ["价值仪表板", "审计仪表板"],
    "ia_05": ["管理建议书", "管理建议"],
    "ia_06": ["内审价值", "价值量化"],
    "ia_07": ["整改跟踪", "整改管理"],
    "ia_08": ["整改验证", "效果验证"],
    # CB - 跨境审计
    "cb_01": ["联邦学习", "跨境审计"],
    "cb_02": ["数据脱敏", "脱敏网关"],
    "cb_03": ["多法域", "法域合规"],
    "cb_04": ["多准则", "准则转换"],
    "cb_05": ["多语言审计", "协作平台"],
    "cb_06": ["集团审计", "集团协作"],
}

# 数据流边：(生产者 slug, 消费者 slug)
# 来源：network_schema.json 中每个模块 outputs[].module 字段
DATA_EDGES: list[tuple[str, str]] = [
    # FA 家族
    ("fa_02", "fa_03"),
    ("fa_03", "fa_07"),
    ("fa_03", "fa_10"),
    ("fa_03", "fo_02"),
    ("fa_03", "cm_01"),
    ("fa_03", "ip_01"),
    ("fa_06", "fa_07"),
    ("fa_07", "ip_01"),
    ("fa_08", "fa_09"),
    ("fa_10", "ip_01"),
    ("fa_10", "fa_11"),
    ("fa_10", "fa_12"),
    # CO 家族
    ("co_01", "co_02"),
    ("co_01", "co_03"),
    ("co_01", "co_07"),
    ("co_01", "co_09"),
    ("co_01", "ip_01"),
    ("co_02", "co_03"),
    ("co_04", "co_05"),
    ("co_04", "co_06"),
    ("co_05", "co_04"),  # 反馈环路
    ("co_05", "co_06"),
    # IP 家族（ip_01 为汇聚节点，无下游输出）
    # CM 家族
    ("cm_01", "cm_02"),
    ("cm_01", "cm_03"),
    ("cm_01", "cm_04"),
    ("cm_01", "cm_05"),
    # IA 家族
    ("ia_01", "ia_02"),
    ("ia_02", "ia_06"),
    ("ia_06", "ia_04"),
    # SC 家族
    ("sc_01", "sc_03"),
    ("sc_03", "sc_04"),
    # ES 家族
    ("es_01", "sc_01"),
    ("es_01", "es_02"),
    ("es_01", "es_03"),
    ("es_01", "es_04"),
    ("es_01", "es_05"),
    ("es_01", "es_06"),
    # FI 家族
    ("fi_02", "fi_01"),
    ("fi_01", "fi_03"),
    # CB 家族
    ("cb_01", "cb_02"),
    ("cb_01", "cb_03"),
    ("cb_01", "cb_04"),
    ("cb_01", "cb_05"),
    ("cb_01", "cb_06"),
    # TA 家族
    ("ta_01", "ta_02"),
]

# 构建反向邻接表：consumer → [producers]
_UPSTREAM_MAP: dict[str, list[str]] = defaultdict(list)
for _src, _dst in DATA_EDGES:
    _UPSTREAM_MAP[_dst].append(_src)

# 构建正向邻接表：producer → [consumers]
_DOWNSTREAM_MAP: dict[str, list[str]] = defaultdict(list)
for _src, _dst in DATA_EDGES:
    _DOWNSTREAM_MAP[_src].append(_dst)


# 用户输入数据路由：哪些 key 应传递给对应模块
USER_INPUT_KEYS: dict[str, list[str]] = {
    "fa_02": ["records"],
    "fa_03": ["records"],
    "fa_04": ["confirmations"],
    "fa_05": ["confirmations"],
    "fa_06": ["confirmations"],
    "fa_07": ["records"],
    "fa_10": ["shareholders", "records"],
    "fa_11": ["transactions"],
    "fa_12": ["transactions", "disclosures"],
    "co_01": ["regulations"],
    "co_04": ["transactions", "customers"],
    "co_05": [],
    "co_06": [],
    "ip_01": ["records", "regulations"],
    "ip_03": ["history_events"],
    "ip_04": ["records"],
    "cm_01": ["records"],
    "fo_01": ["transactions"],
    "fo_02": ["records"],
    "fo_03": ["documents"],
    "fi_02": ["guarantees"],
    "fi_01": ["loans"],
    "sc_01": ["suppliers"],
    "sc_02": ["supply_chain"],
    "es_01": ["esg_data"],
    "ia_01": ["risks"],
    "cb_01": ["cross_border_data"],
    "ta_01": ["invoices"],
    "it_01": ["it_config"],
}


# ======================================================================
# 数据类
# ======================================================================


@dataclass
class AuditRequirement:
    """审计需求。"""
    text: str                    # 原始需求文本
    domain: str = ""             # 识别的业务域
    keywords: list[str] = field(default_factory=list)  # 提取的关键词


@dataclass
class PlanStep:
    """执行计划中的一个步骤。"""
    slug: str                    # 模块slug
    name: str                    # 模块名称
    family: str                  # 技术家族
    inputs: list[str]            # 依赖的上游模块
    outputs: list[str]           # 下游模块
    status: str = "pending"      # pending/running/done/failed/skipped
    result: Any = None           # 执行结果
    error: str = ""              # 错误信息
    duration: float = 0          # 执行耗时


@dataclass
class ExecutionPlan:
    """组网执行方案。"""
    requirement: str             # 原始需求
    reasoning: str               # AI规划推理过程
    modules: list[str]           # 选中的模块列表
    edges: list[tuple[str, str]]  # 数据流边
    steps: list[PlanStep]        # 执行步骤（拓扑排序后）
    contract_valid: bool = True  # 接口契约是否一致
    contract_issues: list[str] = field(default_factory=list)


@dataclass
class ExecutionResult:
    """执行结果。"""
    plan: ExecutionPlan
    module_outputs: dict[str, Any]  # 各模块输出
    final_report: dict             # 汇总报告
    execution_log: list[str]       # 执行日志
    success: bool                  # 是否全部成功
    total_duration: float          # 总耗时


# ======================================================================
# AuditPlanner —— 需求解析与模块组网
# ======================================================================


class AuditPlanner:
    """解析自然语言审计需求，匹配模块，补全依赖，生成执行 DAG。"""

    def __init__(self):
        self._contracts: dict[str, ModuleContract] | None = None

    @property
    def contracts(self) -> dict[str, ModuleContract]:
        if self._contracts is None:
            self._contracts = load_contracts()
        return self._contracts

    def _extract_keywords(self, text: str) -> list[str]:
        """从需求文本提取关键词（遍历 MODULE_KEYWORDS 做子串匹配）。"""
        hits: list[str] = []
        seen = set()
        for _slug, kws in MODULE_KEYWORDS.items():
            for kw in kws:
                if kw in text and kw not in seen:
                    hits.append(kw)
                    seen.add(kw)
        return hits

    def _match_modules(self, keywords: list[str]) -> list[str]:
        """根据关键词匹配候选模块。"""
        matched: dict[str, int] = defaultdict(int)
        for kw in keywords:
            for slug, kws in MODULE_KEYWORDS.items():
                if kw in kws:
                    matched[slug] += 1
        # 按命中数降序
        return [slug for slug, _ in sorted(matched.items(), key=lambda x: -x[1])]

    def _resolve_upstream(self, slug: str, visited: set[str] | None = None) -> set[str]:
        """递归向上找所有上游依赖模块。"""
        if visited is None:
            visited = set()
        result: set[str] = set()
        for up in _UPSTREAM_MAP.get(slug, []):
            if up in visited:
                continue
            visited.add(up)
            result.add(up)
            result |= self._resolve_upstream(up, visited)
        return result

    def plan(self, requirement_text: str) -> ExecutionPlan:
        """解析需求 → 匹配模块 → 补全依赖 → 生成 DAG。"""
        # 1. 提取关键词
        keywords = self._extract_keywords(requirement_text)

        # 2. 匹配候选模块
        candidates = self._match_modules(keywords)

        if not candidates:
            # 兜底：无法匹配时默认走数据标准化
            candidates = ["fa_02"]
            keywords = ["数据标准化"]

        # 3. 补全上游依赖（递归向上）
        all_modules: set[str] = set(candidates)
        for slug in list(candidates):
            all_modules |= self._resolve_upstream(slug)

        # 4. 生成数据流边（仅保留两端都在选中集合中的边）
        selected = all_modules
        edges: list[tuple[str, str]] = [
            (s, d) for s, d in DATA_EDGES
            if s in selected and d in selected
        ]

        # 5. 拓扑排序
        ordered = self._topo_sort(selected, edges)

        # 6. 生成推理过程文本
        reasoning = self._build_reasoning(
            requirement_text, keywords, candidates, all_modules, edges
        )

        # 7. 构建 PlanStep 列表
        steps: list[PlanStep] = []
        for slug in ordered:
            inputs = [s for s, d in edges if d == slug]
            outputs = [d for s, d in edges if s == slug]
            steps.append(PlanStep(
                slug=slug,
                name=MODULE_NAMES.get(slug, slug),
                family=_family_of(slug),
                inputs=inputs,
                outputs=outputs,
            ))

        return ExecutionPlan(
            requirement=requirement_text,
            reasoning=reasoning,
            modules=ordered,
            edges=edges,
            steps=steps,
        )

    def _topo_sort(
        self, nodes: set[str], edges: list[tuple[str, str]]
    ) -> list[str]:
        """Kahn 拓扑排序；遇到环时按剩余节点名字追加（不阻断）。"""
        in_deg: dict[str, int] = {n: 0 for n in nodes}
        adj: dict[str, list[str]] = defaultdict(list)
        for s, d in edges:
            adj[s].append(d)
            in_deg[d] = in_deg.get(d, 0) + 1

        queue = deque([n for n in nodes if in_deg.get(n, 0) == 0])
        result: list[str] = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for nb in adj.get(node, []):
                in_deg[nb] -= 1
                if in_deg[nb] == 0:
                    queue.append(nb)

        # 处理环中剩余节点
        remaining = [n for n in nodes if n not in result]
        # 按 in_deg 升序、再按名字
        remaining.sort(key=lambda n: (in_deg.get(n, 0), n))
        result.extend(remaining)
        return result

    def _build_reasoning(
        self,
        requirement: str,
        keywords: list[str],
        candidates: list[str],
        all_modules: set[str],
        edges: list[tuple[str, str]],
    ) -> str:
        """生成 AI 规划推理过程文本。"""
        lines: list[str] = []
        lines.append(f"【需求分析】{requirement}")
        lines.append(f"【关键词提取】{', '.join(keywords) if keywords else '（默认）'}")

        # 候选匹配
        match_parts: list[str] = []
        for slug in candidates:
            name = MODULE_NAMES.get(slug, slug)
            hit_kws = [
                kw for kw in keywords
                if kw in MODULE_KEYWORDS.get(slug, [])
            ]
            match_parts.append(f"{slug}({name}) ← 关键词[{', '.join(hit_kws)}]")
        lines.append("【模块匹配】" + "；".join(match_parts))

        # 依赖补全
        added = all_modules - set(candidates)
        if added:
            added_names = [
                f"{s}({MODULE_NAMES.get(s, s)})" for s in sorted(added)
            ]
            lines.append(f"【依赖补全】根据 DATA_EDGES 递归补全上游：{', '.join(added_names)}")
        else:
            lines.append("【依赖补全】无额外上游依赖")

        # 数据流
        edge_strs = [f"{s}→{d}" for s, d in edges]
        lines.append(f"【数据流】{', '.join(edge_strs) if edge_strs else '（无内部边）'}")
        lines.append(f"【执行顺序】{' → '.join(sorted(all_modules))}")

        return "\n".join(lines)


# ======================================================================
# LLMPlanner —— 基于 DeepSeek LLM 的需求理解与模块组网
# ======================================================================


class LLMPlanner:
    """基于 DeepSeek LLM 的审计需求理解和模块组网规划器。

    调用 deepseek-v4-flash 模型，将自然语言审计需求转换为结构化的模块组网方案。
    LLM 负责需求理解和模块选择，依赖补全和拓扑排序仍用确定性算法保证正确性。
    """

    SYSTEM_PROMPT = """你是一个审计智能化平台的 AI 规划引擎。用户会给你一个审计需求，你需要从78个模块中选择合适的模块来组成审计方案。

可用模块清单（slug: 名称 - 功能描述）：
fa_02: 多源数据自动标准化 - 数据接入和字段标准化
fa_03: 审计数据湖建设 - 数据湖三区分层存储
fa_04: 智能函证管理平台 - 函证全流程管理
fa_05: 区块链银行函证 - 银行函证区块链存证
fa_06: AI函证差异智能分析 - 函证回函差异分析
fa_07: 智能底稿自动生成平台 - 审计底稿自动生成
fa_08: 底稿自动勾稽检查 - 底稿勾稽关系检查
fa_09: AI底稿质量复核助手 - 底稿质量AI复核
fa_10: 知识图谱关联方发现引擎 - 关联方关系图谱发现
fa_11: 关联交易定价公允性AI分析 - 关联交易定价公允性分析
fa_12: 关联交易披露完整性检查 - 关联交易披露完整性检查
ia_01: 动态风险地图与智能审计计划 - 风险评估和审计计划
ia_02: 持续风险监控平台 - 风险持续监控
ia_03: 审计资源智能分配引擎 - 审计资源分配
ia_04: 审计价值仪表板 - 审计价值可视化
ia_05: AI驱动的管理建议书 - 管理建议书生成
ia_06: 内审价值量化模型 - 内审价值量化
ia_07: 智能整改跟踪平台 - 整改跟踪管理
ia_08: 整改效果自动验证 - 整改效果验证
co_01: 全球法规智能监控平台 - 法规监控和变更跟踪
co_02: AI法规影响评估引擎 - 法规影响评估
co_03: 合规审计程序自动更新 - 合规程序更新
co_04: AML智能交易监控引擎 - 反洗钱交易监控
co_05: 知识图谱洗钱网络发现 - 洗钱网络图谱分析
co_06: AI可疑交易报告自动生成 - 可疑交易报告生成
co_07: AI数据资产自动发现与分类 - 数据资产分类
co_08: 知识图谱数据流分析 - 数据流图谱分析
co_09: 隐私合规自动审计引擎 - 隐私合规审计
it_01: IT审计自动化平台 - IT审计自动化
it_02: AI配置合规扫描引擎 - 配置合规扫描
it_03: AI代码审计助手 - 代码审计
it_04: IT持续审计平台 - IT持续审计
it_05: 区块链审计日志存证 - 审计日志存证
fo_01: 全量交易智能舞弊扫描 - 舞弊交易扫描
fo_02: 知识图谱舞弊网络分析 - 舞弊网络分析
fo_03: NLP文本舞弊信号检测 - 文本舞弊检测
fo_04: AI电子取证平台 - 电子取证
fo_05: 多语言智能翻译与分析 - 多语言翻译
fo_06: 证据链智能构建 - 证据链构建
ta_01: AI发票智能审计平台 - 发票审计
ta_02: 发票四单自动匹配引擎 - 发票匹配
ta_03: 进项税额转出AI计算 - 税额转出计算
ta_04: AI转让定价文档自动生成 - 转让定价文档
ta_05: ML可比公司智能筛选 - 可比公司筛选
ta_06: 知识图谱全球关联交易分析 - 全球关联交易分析
sc_01: 供应商风险智能评分平台 - 供应商风险评分
sc_02: 知识图谱供应链网络分析 - 供应链网络分析
sc_03: 供应商持续风险监控平台 - 供应商风险监控
sc_04: ML采购价格异常检测平台 - 采购价格异常检测
sc_05: AI采购价格基准平台 - 采购价格基准
es_01: ESG多源数据智能采集平台 - ESG数据采集
es_02: AI碳排放自动核算引擎 - 碳排放核算
es_03: 卫星遥感AI环境监测平台 - 环境监测
es_04: 知识图谱绿色漂洗检测平台 - 绿色漂洗检测
es_05: ESG审计知识库与AI助手 - ESG知识库
es_06: AI-ESG审计方法论引擎 - ESG方法论
ip_01: IPO审计智能加速平台 - IPO审计加速
ip_02: AI监管反馈智能回复系统 - 监管反馈回复
ip_03: 知识图谱历史沿革梳理系统 - 历史沿革梳理
ip_04: AI财务规范性智能诊断系统 - 财务规范性诊断
ip_05: IPO案例知识库与RAG系统 - IPO案例库
ip_06: 整改方案AI推荐引擎 - 整改方案推荐
fi_01: AI信贷资产质量评估引擎 - 信贷资产评估
fi_02: 知识图谱担保链风险分析系统 - 担保链风险分析
fi_03: ML贷款违约预测验证系统 - 贷款违约预测
fi_04: 监管报表智能核对平台 - 监管报表核对
fi_05: AI监管口径自动更新系统 - 监管口径更新
cb_01: 联邦学习跨境审计平台 - 联邦学习跨境审计
cb_02: 数据脱敏网关与合规路由系统 - 数据脱敏路由
cb_03: 多法域合规知识库 - 多法域知识库
cb_04: AI多准则自动转换引擎 - 多准则转换
cb_05: AI多语言审计协作平台 - 多语言协作
cb_06: 集团审计智能协作平台 - 集团审计协作
cm_01: 持续审计技术平台 - 持续审计平台
cm_02: 智能预警分级与自动处理系统 - 预警分级处理
cm_03: 持续审计方法论框架 - 持续审计方法论
cm_04: 持续审计价值量化模型 - 持续审计价值量化
cm_05: 持续审计仪表板 - 持续审计仪表板

数据依赖关系（上游→下游）：
fa_02→fa_03, fa_03→fa_07, fa_03→fa_10, fa_03→fo_02, fa_03→cm_01, fa_03→ip_01
fa_06→fa_07, fa_07→ip_01, fa_10→ip_01, fa_10→fa_11, fa_10→fa_12, fa_08→fa_09
co_01→co_02, co_01→co_03, co_01→co_07, co_01→co_09, co_01→ip_01
co_04→co_05, co_05→co_04, co_04→co_06, co_05→co_06, co_02→co_03
es_01→sc_01, es_01→es_02, es_01→es_03, es_01→es_04, es_01→es_05, es_01→es_06
cb_01→cb_02, cb_01→cb_03, cb_01→cb_04, cb_01→cb_05, cb_01→cb_06
cm_01→cm_02, cm_01→cm_03, cm_01→cm_04, cm_01→cm_05
ta_01→ta_02, fi_01→fi_03, fi_02→fi_01
ia_01→ia_02, ia_02→ia_06, ia_06→ia_04
sc_01→sc_03, sc_03→sc_04

你的任务：
1. 理解用户的审计需求
2. 从模块清单中选择直接相关的模块（不要选太多，3-6个为宜）
3. 根据数据依赖关系，自动补全必要的上游模块（如选了fa_10就要补fa_03→fa_02）
4. 输出选择理由和执行顺序

请严格按以下JSON格式输出（不要输出其他内容）：
{
  "reasoning": "需求理解和模块选择的推理过程，2-4句话",
  "matched_keywords": ["关键词1", "关键词2"],
  "selected_modules": ["slug1", "slug2", "slug3"],
  "modules_role": {"slug1": "角色说明", "slug2": "角色说明"}
}"""

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or DEEPSEEK_API_KEY
        self.model = model or DEEPSEEK_MODEL
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=DEEPSEEK_BASE_URL)
        return self._client

    def plan(self, requirement_text: str) -> ExecutionPlan:
        """调用 LLM 做需求理解，然后用确定性算法补全依赖和排序。"""
        # 1. 调用 LLM 选择模块
        llm_result = self._call_llm(requirement_text)

        # 2. 补全上游依赖（确定性算法，保证正确性）
        selected = set(llm_result["selected_modules"])
        for slug in list(selected):
            selected |= self._resolve_upstream(slug)

        # 3. 生成数据流边
        edges = [(s, d) for s, d in DATA_EDGES if s in selected and d in selected]

        # 4. 拓扑排序
        ordered = self._topo_sort(selected, edges)

        # 5. 构建推理文本（融合 LLM 的推理和确定性补全说明）
        reasoning = self._build_reasoning(
            requirement_text, llm_result, selected, edges, ordered
        )

        # 6. 构建 PlanStep
        steps = []
        for slug in ordered:
            inputs = [s for s, d in edges if d == slug]
            outputs = [d for s, d in edges if s == slug]
            steps.append(PlanStep(
                slug=slug, name=MODULE_NAMES.get(slug, slug),
                family=_family_of(slug), inputs=inputs, outputs=outputs,
            ))

        return ExecutionPlan(
            requirement=requirement_text, reasoning=reasoning,
            modules=ordered, edges=edges, steps=steps,
        )

    def _call_llm(self, requirement: str) -> dict:
        """调用 DeepSeek API，返回解析后的 JSON。"""
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": requirement},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=2000,
            )
            content = resp.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            # LLM 调用失败时回退到关键词匹配
            return self._fallback(requirement, str(e))

    def _fallback(self, requirement: str, error: str) -> dict:
        """LLM 失败时回退到关键词匹配。"""
        planner = AuditPlanner()
        kws = planner._extract_keywords(requirement)
        candidates = planner._match_modules(kws)
        if not candidates:
            candidates = ["fa_02"]
        return {
            "reasoning": f"（LLM调用失败: {error[:80]}，回退到关键词匹配）选择了以下模块来满足审计需求。",
            "matched_keywords": kws,
            "selected_modules": candidates,
            "modules_role": {s: MODULE_NAMES.get(s, s) for s in candidates},
        }

    def _resolve_upstream(self, slug, visited=None):
        """递归向上找依赖（复用 AuditPlanner 的逻辑）。"""
        if visited is None:
            visited = set()
        result = set()
        for up in _UPSTREAM_MAP.get(slug, []):
            if up in visited:
                continue
            visited.add(up)
            result.add(up)
            result |= self._resolve_upstream(up, visited)
        return result

    def _topo_sort(self, nodes, edges):
        """拓扑排序（同 AuditPlanner）。"""
        in_deg = {n: 0 for n in nodes}
        adj = defaultdict(list)
        for s, d in edges:
            adj[s].append(d)
            in_deg[d] = in_deg.get(d, 0) + 1
        queue = deque([n for n in nodes if in_deg.get(n, 0) == 0])
        result = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for nb in adj.get(node, []):
                in_deg[nb] -= 1
                if in_deg[nb] == 0:
                    queue.append(nb)
        remaining = [n for n in nodes if n not in result]
        remaining.sort(key=lambda n: (in_deg.get(n, 0), n))
        result.extend(remaining)
        return result

    def _build_reasoning(self, requirement, llm_result, all_modules, edges, ordered):
        """构建融合 LLM 推理和确定性补全的推理文本。"""
        lines = []
        lines.append("【LLM 需求理解】")
        lines.append(llm_result.get("reasoning", ""))
        lines.append("")
        lines.append(f"【关键词】{', '.join(llm_result.get('matched_keywords', []))}")

        roles = llm_result.get("modules_role", {})
        lines.append("【LLM 选定模块】")
        for slug in llm_result.get("selected_modules", []):
            role = roles.get(slug, "")
            lines.append(f"  • {slug}({MODULE_NAMES.get(slug, slug)}) - {role}")

        # 依赖补全
        llm_selected = set(llm_result.get("selected_modules", []))
        added = all_modules - llm_selected
        if added:
            lines.append("【自动补全上游依赖】")
            for s in sorted(added):
                lines.append(f"  • {s}({MODULE_NAMES.get(s, s)})")

        edge_strs = [f"{s}→{d}" for s, d in edges]
        lines.append(f"【数据流】{', '.join(edge_strs)}")
        lines.append(f"【执行顺序】{' → '.join(ordered)}")

        return "\n".join(lines)


# ======================================================================
# ContractValidator —— 接口契约校验
# ======================================================================


class ContractValidator:
    """按 network_schema.json 校验 plan 中每条边的接口契约一致性。"""

    def __init__(self):
        self._contracts: dict[str, ModuleContract] | None = None

    @property
    def contracts(self) -> dict[str, ModuleContract]:
        if self._contracts is None:
            self._contracts = load_contracts()
        return self._contracts

    def validate(self, plan: ExecutionPlan) -> tuple[bool, list[str]]:
        """校验 plan 中的数据流边。

        返回 (是否通过, 问题列表)。问题写入 plan.contract_issues。
        """
        issues: list[str] = []
        contracts = self.contracts

        for src, dst in plan.edges:
            # 检查两端模块是否在 schema 中有定义
            if src not in contracts:
                issues.append(f"边 {src}→{dst}：生产者 {src} 不在 network_schema 中")
                continue
            if dst not in contracts:
                issues.append(f"边 {src}→{dst}：消费者 {dst} 不在 network_schema 中")
                continue

            src_contract = contracts[src]
            dst_contract = contracts[dst]

            # 检查 src 是否有指向 dst 的 output
            src_output = next(
                (o for o in src_contract.outputs if o.module == dst), None
            )
            if src_output is None:
                issues.append(
                    f"边 {src}→{dst}：{src} 的 outputs 中未定义指向 {dst} 的输出"
                )

            # 检查 dst 是否有来自 src 的 input
            dst_input = next(
                (i for i in dst_contract.inputs if i.module == src), None
            )
            if dst_input is None:
                issues.append(
                    f"边 {src}→{dst}：{dst} 的 inputs 中未定义来自 {src} 的输入"
                )

            # 检查格式兼容性
            if src_output and dst_input:
                if src_output.format != dst_input.format:
                    issues.append(
                        f"边 {src}→{dst}：格式不兼容 "
                        f"({src} 输出 {src_output.format} ≠ {dst} 输入 {dst_input.format})"
                    )
                if src_output.data_type != dst_input.data_type:
                    issues.append(
                        f"边 {src}→{dst}：数据类型不一致 "
                        f"({src} 输出「{src_output.data_type}」≠ {dst} 输入「{dst_input.data_type}」)"
                    )
                # v2.0 强类型字段校验（双方均有 fields_typed 时逐字段校验）
                if src_output.fields_typed and dst_input.fields_typed:
                    out_map = {f.name: f for f in src_output.fields_typed}
                    for in_field in dst_input.fields_typed:
                        if in_field.name not in out_map:
                            if not in_field.nullable:
                                issues.append(
                                    f"边 {src}→{dst}：字段「{in_field.name}」"
                                    f"消费者要求非空但生产者未提供"
                                )
                            continue
                        ok, msg = in_field.is_compatible_with(out_map[in_field.name])
                        if not ok:
                            issues.append(f"边 {src}→{dst}：{msg}")

        plan.contract_valid = len(issues) == 0
        plan.contract_issues = issues
        return plan.contract_valid, issues


# ======================================================================
# TopoExecutor —— 拓扑排序执行
# ======================================================================


class TopoExecutor:
    """拓扑排序后逐模块执行 pipeline.run()，按接口契约传递数据。

    模块执行失败时记录错误但不阻断后续模块，并用模拟数据填充输出。
    """

    def execute(
        self, plan: ExecutionPlan, user_input: dict | None = None
    ) -> ExecutionResult:
        """执行计划中的所有步骤。"""
        user_input = user_input or {}
        log: list[str] = []
        outputs: dict[str, Any] = {}
        total_start = time.time()

        # v2.0 数据对齐层：执行前对用户输入做多模态数据对齐
        aligned_input = dict(user_input)  # 拷贝，避免修改原数据
        try:
            from modules.shared.aligner import DataAligner, EntityRecord
            aligner = DataAligner()
            # 从 user_input 提取实体记录（shareholders + records 中的 counterparty）
            entities: list = []
            for sh in user_input.get("shareholders", []):
                if isinstance(sh, dict):
                    entities.append(EntityRecord(
                        entity_id=sh.get("name", ""), source="shareholders",
                        name=sh.get("name", ""), uscc=sh.get("uscc", ""),
                        aliases=sh.get("related_entities", []),
                        attributes={"role": sh.get("role", "")},
                    ))
            for rec in user_input.get("records", []):
                raw = rec.get("raw_data", {}) if isinstance(rec, dict) else {}
                cp = raw.get("counterparty")
                if cp:
                    entities.append(EntityRecord(
                        entity_id=cp, source=rec.get("source", "unknown"),
                        name=cp, uscc="", aliases=[], attributes={},
                    ))
            # 提取时间记录
            time_records = []
            for rec in user_input.get("records", []):
                raw = rec.get("raw_data", {}) if isinstance(rec, dict) else {}
                if raw.get("event_time") or raw.get("period"):
                    time_records.append({"event_time": raw.get("event_time") or raw.get("period")})
            align_result = aligner.align({
                "entities": entities,
                "time_records": time_records,
                "modal_records": [],
            })
            rpt = align_result.get("report", {})
            if rpt.get("entities_aligned", 0) > 0 or rpt.get("times_aligned", 0) > 0:
                log.append(
                    f"=== 数据对齐层：实体对齐 {rpt.get('entities_aligned', 0)} 簇，"
                    f"时间对齐 {rpt.get('times_aligned', 0)} 条，"
                    f"模态融合 {rpt.get('modalities_fused', 0)} 条 ==="
                )
                # 将对齐后的实体簇信息注入 aligned_input
                clusters = align_result.get("clusters", [])
                if clusters:
                    aligned_input["entity_clusters"] = [
                        {"canonical_id": c.canonical_id, "canonical_name": c.canonical_name,
                         "uscc": c.uscc, "member_count": len(c.members),
                         "confidence": c.match_confidence}
                        for c in clusters
                    ]
        except Exception as exc:
            log.append(f"=== 数据对齐层跳过：{type(exc).__name__}: {exc} ===")

        total = len(plan.steps)
        log.append(f"=== 开始执行审计编排（共 {total} 个模块）===")

        for idx, step in enumerate(plan.steps, 1):
            step.status = "running"
            prefix = f"[{idx}/{total}] {step.slug} {step.name}"
            log.append(f"{prefix} → 运行中...")

            # 收集输入数据（使用对齐后的数据）
            input_data = self._collect_inputs(step, outputs, aligned_input)

            start = time.time()
            try:
                result = self._run_pipeline(step.slug, input_data)
                step.status = "done"
                step.result = result
                step.duration = round(time.time() - start, 3)
                outputs[step.slug] = result
                log.append(
                    f"{prefix} → ✓ 完成 ({step.duration}s)"
                )
            except Exception as exc:
                step.status = "failed"
                step.error = f"{type(exc).__name__}: {exc}"
                step.duration = round(time.time() - start, 3)
                # 用模拟数据填充，确保 demo 不中断
                mock = self._generate_mock_output(step.slug, input_data)
                step.result = mock
                outputs[step.slug] = mock
                log.append(
                    f"{prefix} → ✗ 失败 ({step.duration}s) "
                    f"[{step.error}] → 已用模拟数据替代"
                )

        total_duration = round(time.time() - total_start, 3)
        success = all(s.status == "done" for s in plan.steps)

        status_summary = (
            f"成功 {sum(1 for s in plan.steps if s.status == 'done')}/"
            f"失败 {sum(1 for s in plan.steps if s.status == 'failed')}/"
            f"总计 {total}"
        )
        log.append(f"=== 执行完成：{status_summary}，总耗时 {total_duration}s ===")

        return ExecutionResult(
            plan=plan,
            module_outputs=outputs,
            final_report={},
            execution_log=log,
            success=success,
            total_duration=total_duration,
        )

    def _collect_inputs(
        self,
        step: PlanStep,
        outputs: dict[str, Any],
        user_input: dict,
    ) -> dict:
        """收集上游模块输出 + 用户输入数据。"""
        data: dict[str, Any] = {}

        # 上游模块输出
        for up_slug in step.inputs:
            if up_slug in outputs:
                up_result = outputs[up_slug]
                # 把上游结果以 {upstream_module: result} 形式放入
                data[up_slug] = up_result
                # 同时展开 result 的顶层 key（便于下游读取）
                if isinstance(up_result, dict):
                    for k, v in up_result.items():
                        if k not in data:
                            data[k] = v

        # 模块专属输入（user_input 中以 slug 为 key 的适配数据，优先级最高）
        slug_input = user_input.get(step.slug)
        if isinstance(slug_input, dict):
            data.update(slug_input)

        # 用户输入数据路由（通用 key 路由，作为兜底）
        for key in USER_INPUT_KEYS.get(step.slug, []):
            if key in user_input:
                data[key] = user_input[key]

        return data

    def _run_pipeline(self, slug: str, input_data: dict) -> Any:
        """动态导入模块 pipeline 并执行 run()。"""
        module_path = f"modules.{slug}.pipeline"
        mod = importlib.import_module(module_path)
        Pipeline_cls = getattr(mod, "Pipeline", None)
        if Pipeline_cls is None:
            raise AttributeError(f"{module_path} 中未找到 Pipeline 类")
        pipeline = Pipeline_cls()
        return pipeline.run(input_data)

    # ------------------------------------------------------------------
    # 模拟数据生成（模块执行失败时的兜底）
    # ------------------------------------------------------------------

    def _generate_mock_output(self, slug: str, input_data: dict) -> Any:
        """根据模块类型生成模拟输出数据。"""
        generator = _MOCK_GENERATORS.get(slug, _mock_generic)
        return generator(slug, input_data)


# ======================================================================
# 模拟数据生成函数
# ======================================================================


def _mock_fa_02(slug: str, data: dict) -> dict:
    records = data.get("records", [])
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "standardized_records": [
            {
                "source": r.get("source", "unknown"),
                "raw": r.get("raw_data", {}),
                "standardized": True,
                "confidence": 0.92,
            }
            for r in records[:20]
        ],
        "stats": {
            "total": len(records),
            "standardized": len(records),
            "need_review": 0,
        },
    }


def _mock_fa_03(slug: str, data: dict) -> dict:
    records = data.get("records", [])
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "layers": {
            "ODS": {"count": len(records), "description": "原始数据层"},
            "DWD": {"count": len(records), "description": "标准化明细层"},
            "ADS": {"count": max(1, len(records) // 2), "description": "分析就绪层"},
        },
        "stats": {"total_records": len(records), "layers": 3},
    }


def _mock_fa_10(slug: str, data: dict) -> dict:
    shareholders = data.get("shareholders", [])
    records = data.get("records", [])
    # 从 records 提取交易对手
    counterparties = list({
        r.get("raw_data", {}).get("counterparty", "")
        for r in records
        if r.get("raw_data", {}).get("counterparty")
    })
    nodes = [{"id": f"E{i+1}", "name": sh.get("name", f"实体{i+1}"),
              "type": sh.get("role", "股东")} for i, sh in enumerate(shareholders)]
    for j, cp in enumerate(counterparties):
        nodes.append({"id": f"CP{j+1}", "name": cp, "type": "交易对手"})
    edges = [{"from": n["id"], "to": "E1", "relation": "关联交易"}
             for n in nodes if n["id"] != "E1"]
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "related_parties": [
            {"entity_id": n["id"], "entity_name": n["name"],
             "relation_type": n["type"]}
            for n in nodes
        ],
        "graph": {"nodes": nodes, "edges": edges},
        "stats": {"entities": len(nodes), "relations": len(edges)},
    }


def _mock_fa_11(slug: str, data: dict) -> dict:
    txs = data.get("transactions", [])
    analyses = []
    for t in txs:
        dev = t.get("deviation", 0)
        fair = "公允" if abs(dev) < 10 else ("偏离" if abs(dev) < 30 else "严重不公允")
        analyses.append({
            "id": t.get("id", "?"),
            "counterparty": t.get("counterparty", "?"),
            "amount": t.get("amount", 0),
            "pricing": t.get("pricing", "协议价"),
            "market_price": t.get("market_price", 0),
            "deviation": dev,
            "fairness": fair,
        })
    unfair = sum(1 for a in analyses if a["fairness"] != "公允")
    avg_dev = round(sum(a["deviation"] for a in analyses) / max(len(analyses), 1), 2)
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "pricing_analysis": analyses,
        "stats": {"total": len(analyses), "unfair": unfair, "avg_deviation": avg_dev},
    }


def _mock_fa_12(slug: str, data: dict) -> dict:
    txs = data.get("transactions", [])
    disclosures = data.get("disclosures", [])
    disclosed_set = {d.get("counterparty") for d in disclosures} if disclosures else set()
    checks = []
    for t in txs:
        cp = t.get("counterparty", "?")
        is_disclosed = cp in disclosed_set if disclosed_set else True
        checks.append({
            "id": t.get("id", "?"),
            "counterparty": cp,
            "amount": t.get("amount", 0),
            "disclosed": is_disclosed,
            "gap": "已披露" if is_disclosed else "未披露",
        })
    missing = sum(1 for c in checks if not c["disclosed"])
    rate = round((len(checks) - missing) / max(len(checks), 1) * 100, 1)
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "disclosure_check": checks,
        "stats": {"total": len(checks), "missing": missing, "complete_rate": rate},
    }


def _mock_co_01(slug: str, data: dict) -> dict:
    regulations = data.get("regulations", [])
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "regulations": [
            {"id": r.get("id", f"R{i+1}"), "title": r.get("title", "?"),
             "jurisdiction": r.get("jurisdiction", "CN"),
             "impact_level": r.get("impact_level", "中")}
            for i, r in enumerate(regulations)
        ],
        "stats": {"total": len(regulations), "high_impact": 0},
    }


def _mock_co_04(slug: str, data: dict) -> dict:
    txs = data.get("transactions", [])
    alerts = []
    for i, t in enumerate(txs):
        amt = t.get("amount", 0)
        is_suspicious = abs(amt) > 400000 or "货款" not in t.get("purpose", "")
        if is_suspicious:
            alerts.append({
                "alert_id": f"AL{i+1:04d}",
                "tx_id": t.get("tx_id", f"TX{i+1}"),
                "alert_type": "大额可疑",
                "risk_score": round(min(0.5 + abs(amt) / 10000000, 0.99), 2),
                "amount": amt,
            })
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "alerts": alerts,
        "stats": {"total_txs": len(txs), "alerts": len(alerts),
                  "alert_rate": round(len(alerts) / max(len(txs), 1) * 100, 1)},
    }


def _mock_co_05(slug: str, data: dict) -> dict:
    # 从上游 co_04 输出获取告警
    alerts = data.get("co_04", {})
    if isinstance(alerts, dict):
        alert_list = alerts.get("alerts", [])
    else:
        alert_list = []
    txs = data.get("transactions", [])
    nodes = [{"id": t.get("from_account", "?"), "name": t.get("from_account", "?")}
             for t in txs]
    edges = [{"from": t.get("from_account", "?"), "to": t.get("to_account", "?"),
              "amount": t.get("amount", 0)} for t in txs]
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "networks": [
            {"network_id": "N001", "type": "资金闭环",
             "risk_score": 0.85, "path": "A→B→C→A"}
        ],
        "graph": {"nodes": nodes, "edges": edges},
        "stats": {"networks": 1, "high_risk": 1,
                  "based_on_alerts": len(alert_list)},
    }


def _mock_co_06(slug: str, data: dict) -> dict:
    co_04 = data.get("co_04", {})
    co_05 = data.get("co_05", {})
    alert_count = 0
    if isinstance(co_04, dict):
        alert_count = len(co_04.get("alerts", []))
    reports = [
        {"report_id": "SAR-001", "type": "可疑交易报告",
         "summary": f"基于 {alert_count} 条告警生成",
         "severity": "高"},
    ]
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "reports": reports,
        "stats": {"reports": len(reports)},
    }


def _mock_ip_01(slug: str, data: dict) -> dict:
    records = data.get("records", [])
    regulations = data.get("regulations", [])
    issues = [
        {"issue_id": "IP-001", "category": "关联方披露",
         "severity": "高", "description": "关联方识别不完整"},
        {"issue_id": "IP-002", "category": "财务规范性",
         "severity": "中", "description": "会计政策变更披露不充分"},
    ]
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "diagnosis": issues,
        "stats": {"records_analyzed": len(records),
                  "regulations_checked": len(regulations),
                  "issues": len(issues), "high_risk": 1},
    }


def _mock_generic(slug: str, data: dict) -> dict:
    """通用模拟数据生成器。"""
    return {
        "module": slug,
        "name": MODULE_NAMES.get(slug, slug),
        "mock": True,
        "message": "模块执行失败，已生成模拟输出",
        "input_keys": list(data.keys()),
    }


_MOCK_GENERATORS: dict[str, Any] = {
    "fa_02": _mock_fa_02,
    "fa_03": _mock_fa_03,
    "fa_10": _mock_fa_10,
    "fa_11": _mock_fa_11,
    "fa_12": _mock_fa_12,
    "co_01": _mock_co_01,
    "co_04": _mock_co_04,
    "co_05": _mock_co_05,
    "co_06": _mock_co_06,
    "ip_01": _mock_ip_01,
    "ip_04": _mock_ip_01,
}


# ======================================================================
# ReportGenerator —— 结果汇总与报告生成
# ======================================================================


class ReportGenerator:
    """汇总各模块输出，生成结构化审计报告。"""

    def generate(self, result: ExecutionResult) -> dict:
        """生成最终审计报告。"""
        plan = result.plan
        findings: list[dict] = []
        module_results: dict[str, Any] = {}

        for step in plan.steps:
            if step.result is None:
                continue
            output = step.result
            is_mock = isinstance(output, dict) and output.get("mock", False)
            module_results[step.slug] = {
                "name": step.name,
                "family": step.family,
                "status": step.status,
                "duration": step.duration,
                "is_mock": is_mock,
                "error": step.error or None,
                "summary": self._summarize_output(step.slug, output),
            }
            # 提取审计发现
            findings.extend(self._extract_findings(step.slug, output))

        success_count = sum(1 for s in plan.steps if s.status == "done")
        return {
            "audit_requirement": plan.requirement,
            "plan_summary": {
                "modules": len(plan.steps),
                "edges": len(plan.edges),
                "success": success_count,
                "failed": len(plan.steps) - success_count,
                "contract_valid": plan.contract_valid,
            },
            "findings": findings,
            "module_results": module_results,
            "execution_log": result.execution_log,
            "total_duration": result.total_duration,
        }

    def _summarize_output(self, slug: str, output: Any) -> dict:
        """提取模块输出的摘要信息（兼容真实 pipeline 与模拟数据）。"""
        if not isinstance(output, dict):
            return {"type": str(type(output))}

        # 模拟数据格式：直接取 stats
        stats = output.get("stats", {})
        if stats:
            return {"stats": stats}

        # 真实 pipeline 输出格式适配
        if slug == "fa_11" and "fairness_summary" in output:
            fs = output["fairness_summary"]
            return {"stats": {
                "total": fs.get("total_transactions", 0),
                "fair_rate": fs.get("fair_rate", 0),
                "needs_adjustment": fs.get("needs_adjustment_count", 0),
            }}

        if slug == "fa_12" and "completeness_summary" in output:
            cs = output["completeness_summary"]
            return {"stats": {
                "total": cs.get("total_transactions", 0),
                "undisclosed": cs.get("undisclosed", 0),
                "completeness_score": cs.get("completeness_score", 100),
                "risk_level": cs.get("risk_level", "low"),
            }}

        if slug == "co_04" and "summary" in output:
            s = output["summary"]
            return {"stats": {
                "total_txs": s.get("total_transactions", 0),
                "alerts": s.get("total_sars", len(output.get("alerts", []))),
            }}

        if slug == "fa_10" and "summary" in output:
            s = output["summary"]
            return {"stats": {
                "targets": s.get("total_targets", 0),
                "related": s.get("total_related", 0),
                "hidden": s.get("total_hidden", 0),
                "cycles": s.get("total_cycles", 0),
            }}

        if slug == "co_05" and "summary" in output:
            s = output["summary"]
            return {"stats": {
                "networks": s.get("total_networks", len(output.get("networks", []))),
                "high_risk": s.get("high_risk_count", 0),
            }}

        if slug == "co_06" and "summary" in output:
            s = output["summary"]
            return {"stats": {
                "reports": s.get("total_reports", len(output.get("reports", []))),
            }}

        if slug in ("ip_01", "ip_04") and "summary" in output:
            s = output["summary"]
            return {"stats": {
                "issues": s.get("total_issues", 0),
                "high_risk": s.get("high_risk_count", 0),
            }}

        # 兜底：返回 key 列表
        return {"keys": [k for k in output.keys() if k != "mock"]}

    def _extract_findings(self, slug: str, output: Any) -> list[dict]:
        """从模块输出中提取审计发现（兼容真实 pipeline 与模拟数据）。"""
        findings: list[dict] = []
        if not isinstance(output, dict):
            return findings

        # fa_11: 定价不公允的交易
        if slug == "fa_11":
            # 模拟数据格式
            for item in output.get("pricing_analysis", []):
                if item.get("fairness") != "公允":
                    findings.append({
                        "source": "fa_11",
                        "severity": "高" if item.get("fairness") == "严重不公允" else "中",
                        "title": f"关联交易定价{item.get('fairness')}",
                        "detail": f"交易对手 {item.get('counterparty')}，"
                                  f"金额 {item.get('amount')}，"
                                  f"偏离率 {item.get('deviation')}%",
                    })
            # 真实 pipeline 格式
            for item in output.get("transactions", []):
                level = item.get("fairness_level", "")
                if level and level not in ("fair", "FAIR"):
                    sev = "高" if "significantly" in level.lower() else "中"
                    findings.append({
                        "source": "fa_11",
                        "severity": sev,
                        "title": f"关联交易定价{level}",
                        "detail": f"交易对手 {item.get('related_party')}，"
                                  f"金额 {item.get('amount')}，"
                                  f"偏离率 {item.get('deviation_rate')}%",
                    })

        # fa_12: 未披露的关联交易
        if slug == "fa_12":
            # 模拟数据格式
            for item in output.get("disclosure_check", []):
                if not item.get("disclosed"):
                    findings.append({
                        "source": "fa_12",
                        "severity": "高",
                        "title": "关联交易未披露",
                        "detail": f"交易对手 {item.get('counterparty')}，"
                                  f"金额 {item.get('amount')} 未在年报中披露",
                    })
            # 真实 pipeline 格式
            for item in output.get("missing_items", []):
                sev = item.get("severity", "高")
                findings.append({
                    "source": "fa_12",
                    "severity": sev if sev in ("高", "中", "低") else "高",
                    "title": "关联交易未披露",
                    "detail": f"交易对手 {item.get('related_party')}，"
                              f"金额 {item.get('amount')}，"
                              f"原因：{item.get('reason', '未披露')}",
                })

        # fa_10: 隐藏关联方 / 关联环路（真实格式）
        if slug == "fa_10":
            for net in output.get("networks", []):
                if not isinstance(net, dict):
                    continue
                # 模拟格式有 type/path/risk_score
                if net.get("type"):
                    findings.append({
                        "source": "fa_10",
                        "severity": "高",
                        "title": f"关联网络：{net.get('type')}",
                        "detail": f"路径 {net.get('path')}，"
                                  f"风险评分 {net.get('risk_score')}",
                    })
                # 真实格式有 hidden_links / cycles
                for hl in net.get("hidden_links", []):
                    findings.append({
                        "source": "fa_10",
                        "severity": "高",
                        "title": f"隐藏关联方：{hl.get('name', '?')}",
                        "detail": f"路径 {hl.get('path')}，"
                                  f"跳数 {hl.get('hops')}，"
                                  f"强度 {hl.get('strength')}",
                    })
                for cyc in net.get("cycles", []):
                    findings.append({
                        "source": "fa_10",
                        "severity": "中",
                        "title": "关联方环路检测",
                        "detail": str(cyc),
                    })

        # co_04: 可疑交易告警
        if slug == "co_04":
            for alert in output.get("alerts", []):
                # 兼容模拟格式（alert_type）和真实格式（pattern）
                alert_name = alert.get("alert_type") or alert.get("pattern", "可疑交易")
                tx_ref = alert.get("tx_id") or alert.get("sar_id", "?")
                risk = alert.get("risk_score", 0)
                if isinstance(risk, (int, float)):
                    sev = "高" if risk > 0.7 else "中"
                else:
                    sev = "高"
                findings.append({
                    "source": "co_04",
                    "severity": sev,
                    "title": f"AML告警：{alert_name}",
                    "detail": f"交易/SAR {tx_ref}，"
                              f"风险评分 {risk}，"
                              f"金额 {alert.get('amount')}",
                })

        # co_05: 洗钱网络
        if slug == "co_05":
            for net in output.get("networks", []):
                if not isinstance(net, dict):
                    continue
                net_type = net.get("type") or net.get("network_type", "洗钱网络")
                risk = net.get("risk_score", 0)
                findings.append({
                    "source": "co_05",
                    "severity": "高",
                    "title": f"洗钱网络：{net_type}",
                    "detail": f"路径 {net.get('path', '?')}，"
                              f"风险评分 {risk}",
                })

        # ip_01 / ip_04: IPO合规问题
        if slug in ("ip_01", "ip_04"):
            # 模拟格式
            for issue in output.get("diagnosis", []):
                findings.append({
                    "source": slug,
                    "severity": issue.get("severity", "中"),
                    "title": f"IPO问题：{issue.get('category')}",
                    "detail": issue.get("description", ""),
                })
            # 真实格式 issues 列表
            for issue in output.get("issues", []):
                if not isinstance(issue, dict):
                    continue
                findings.append({
                    "source": slug,
                    "severity": issue.get("severity", "中"),
                    "title": f"IPO问题：{issue.get('category', issue.get('title', '?'))}",
                    "detail": issue.get("description", issue.get("detail", "")),
                })
            # ip_01 真实格式：findings 列表
            for item in output.get("findings", []):
                if not isinstance(item, dict):
                    continue
                raw_sev = item.get("severity", "medium")
                sev_map = {"high": "高", "medium": "中", "low": "低",
                           "critical": "高", "高": "高", "中": "中", "低": "低"}
                sev = sev_map.get(str(raw_sev).lower(), "中")
                findings.append({
                    "source": slug,
                    "severity": sev,
                    "title": f"IPO发现：{item.get('category', item.get('finding_id', '?'))}",
                    "detail": item.get("description", item.get("detail", "")),
                })
            # ip_04 真实格式：problems 列表
            for item in output.get("problems", []):
                if not isinstance(item, dict):
                    continue
                raw_sev = item.get("severity", item.get("level", "medium"))
                sev_map = {"high": "高", "medium": "中", "low": "低",
                           "critical": "高", "高": "高", "中": "中", "低": "低"}
                sev = sev_map.get(str(raw_sev).lower(), "中")
                findings.append({
                    "source": slug,
                    "severity": sev,
                    "title": f"财务规范性：{item.get('category', item.get('problem_id', '?'))}",
                    "detail": item.get("description", item.get("detail", item.get("suggestion", ""))),
                })

        # ip_03: 历史沿革异常
        if slug == "ip_03":
            for item in output.get("anomalies", []):
                if not isinstance(item, dict):
                    continue
                raw_sev = item.get("severity", item.get("level", "medium"))
                sev_map = {"high": "高", "medium": "中", "low": "低",
                           "critical": "高", "高": "高", "中": "中", "低": "低"}
                sev = sev_map.get(str(raw_sev).lower(), "中")
                findings.append({
                    "source": slug,
                    "severity": sev,
                    "title": f"沿革异常：{item.get('type', item.get('category', '?'))}",
                    "detail": item.get("description", item.get("detail", str(item))),
                })

        # 通用兜底：扫描常见发现字段（anomalies / violations / warnings / risks）
        if not findings and isinstance(output, dict):
            for field in ("anomalies", "violations", "warnings", "risks"):
                items = output.get(field, [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    raw_sev = item.get("severity", item.get("level", "medium"))
                    sev_map = {"high": "高", "medium": "中", "low": "低",
                               "critical": "高", "高": "高", "中": "中", "低": "低"}
                    sev = sev_map.get(str(raw_sev).lower(), "中")
                    title = item.get("title", item.get("name", item.get("type", field)))
                    detail = item.get("description", item.get("detail", item.get("message", str(item))))
                    findings.append({
                        "source": slug,
                        "severity": sev,
                        "title": str(title)[:80],
                        "detail": str(detail)[:200],
                    })

        # ===== 数据溯源：给每条发现关联 source_records（原始数据条目） =====
        self._attach_source_records(slug, findings)

        return findings

    def _attach_source_records(self, slug: str, findings: list[dict]) -> None:
        """为发现列表附加原始数据溯源记录（in-place 修改）。"""
        if not findings:
            return
        try:
            import sys
            from pathlib import Path
            demo_path = str(Path(__file__).resolve().parent.parent.parent / "demo")
            if demo_path not in sys.path:
                sys.path.insert(0, demo_path)
            from data_adapter import lookup_source_records

            # 使用缓存避免重复加载同一个模块的原始数据
            cache = getattr(self, "_raw_data_cache", None)
            if cache is None:
                cache = {}
                self._raw_data_cache = cache

            for f in findings:
                matched = lookup_source_records(slug, f, raw_data_cache=cache)
                if matched:
                    # 附加数据集来源信息
                    datasets = {}
                    for rec in matched:
                        src = rec.get("_source_file", "unknown")
                        if src not in datasets:
                            datasets[src] = []
                        # 脱敏：移除内部溯源字段展示，但保留引用
                        clean_rec = {k: v for k, v in rec.items() if not k.startswith("_")}
                        clean_rec["_ref"] = {
                            "file": src,
                            "row": rec.get("_row_index", -1),
                            "dataset": rec.get("_dataset", slug),
                        }
                        datasets[src].append(clean_rec)
                    # source_records 结构: {文件名: [记录, ...]}
                    f["source_records"] = datasets
                    f["datasets"] = list(datasets.keys())
                else:
                    f["source_records"] = {}
                    f["datasets"] = []
        except Exception as e:
            # 溯源失败不阻塞主流程
            for f in findings:
                if "source_records" not in f:
                    f["source_records"] = {}
                if "datasets" not in f:
                    f["datasets"] = []


# ======================================================================
# 主入口
# ======================================================================


def run_audit(requirement: str, input_data: dict | None = None) -> ExecutionResult:
    """端到端审计：需求 → 规划 → 校验 → 执行 → 报告。"""
    planner = AuditPlanner()
    plan = planner.plan(requirement)

    validator = ContractValidator()
    validator.validate(plan)

    executor = TopoExecutor()
    result = executor.execute(plan, input_data or {})

    result.final_report = ReportGenerator().generate(result)
    return result


def run_audit_with_llm(requirement: str, input_data: dict | None = None) -> ExecutionResult:
    """使用 DeepSeek LLM 的端到端审计：需求 → LLM规划 → 校验 → 执行 → 报告。"""
    planner = LLMPlanner()
    plan = planner.plan(requirement)

    validator = ContractValidator()
    validator.validate(plan)

    executor = TopoExecutor()
    result = executor.execute(plan, input_data or {})

    result.final_report = ReportGenerator().generate(result)
    return result
