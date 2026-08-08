"""[llm_rag] ES-06 AI-ESG审计方法论引擎。

纯 stdlib 实现的 ESG 审计方法论自动生成引擎：
  - _load_model  : 加载方法论模板库（按行业×标准×审计主题）+ 风险知识库 + 证据清单库 + 底稿字段模板
  - _preprocess  : 输入审计对象特征（行业/规模/业务范围/适用标准/审计目标），匹配方法论模板
  - _infer       : 模板匹配 → 程序生成 → 证据清单生成 → 底稿模板生成 → 质量自检
  - _postprocess : 输出完整审计方法论包（程序/证据清单/底稿/风险点/时间安排）+ 质量评分
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta

from modules.shared.base_engine import AbstractEngine


_INDUSTRY_TEMPLATES = {
    "制造业": {
        "GHG排放审计": {
            "subject": "GHG排放审计（制造业）",
            "scope": "覆盖Scope1直接排放（燃烧/工艺/制冷剂）和Scope2能源间接排放（电力/蒸汽）",
            "procedures": [
                {"id": "P1", "name": "组织边界确认", "steps": ["确认企业组织结构和运营控制边界", "识别所有排放源类别（燃烧/工艺/制冷/电解）", "获取最新的组织架构图和设施清单"]},
                {"id": "P2", "name": "活动数据验证", "steps": ["收集各设施燃料消耗台账（按月度）", "核对燃料账单与ERP记录", "抽查关键计量设备校准记录", "重新计算燃料消耗量加权平均"], "duration_days": 3},
                {"id": "P3", "name": "排放因子确认", "steps": ["检查排放因子来源（IPCC/国家指南/供应商实测）", "核对GWP值选择依据", "验证是否使用最新版本排放因子"], "duration_days": 2},
                {"id": "P4", "name": "Scope2双法计算", "steps": ["分别用位置法和市场法计算Scope2排放", "检查市场法数据来源（绿电证书/PPA合同）", "确认两种方法差异原因"], "duration_days": 2},
                {"id": "P5", "name": "计算重算与勾稽", "steps": ["对30%样本量的排放源重新计算", "合计数据与分设施数据勾稽校验", "比较当年与历史排放趋势合理性"], "duration_days": 3},
            ],
            "evidence_types": [
                {"category": "必需", "items": ["燃料采购发票", "电力账单/绿电证书", "生产设备清单", "计量设备校准记录", "排放因子手册"]},
                {"category": "推荐", "items": ["能耗监测系统数据导出", "锅炉/窑炉效率测试报告", "制冷剂充注记录", "第三方节能诊断报告"]},
                {"category": "验证", "items": ["上年度审计报告", "政府碳排放核查报告", "行业对标数据"]},
            ],
            "workpaper_fields": [
                "审计对象名称", "审计期间", "适用标准（ISSB S2/GRI 305）", "组织边界描述",
                "排放源清单（设施+类别）", "活动数据表（燃料类型/消耗量/单位）",
                "排放因子表（因子值/单位/来源）", "Scope1计算表", "Scope2位置法计算表",
                "Scope2市场法计算表", "GWP转换表", "合计排放汇总", "差异分析",
                "审计结论", "发现事项与建议",
            ],
            "risks": [
                {"risk": "排放因子过期", "mitigation": "强制检查排放因子版本号，使用IPCC AR6或国家最新指南"},
                {"risk": "活动数据完整性", "mitigation": "抽查ERP系统数据与实际台账，关注年末突击入账"},
                {"risk": "Scope2市场法偏差", "mitigation": "验证绿电证书是否真实对应企业用电量，检查证书序列号"},
                {"risk": "边界变化未披露", "mitigation": "比较两年组织架构图，检查并购/处置导致的边界变化"},
            ],
            "sample_strategy": "按设施规模分层抽样，大型设施100%覆盖，中小型设施抽取30%",
            "time_plan": [
                {"phase": "准备", "days": 2, "deliverable": "审计计划/资料清单"},
                {"phase": "实施", "days": 10, "deliverable": "工作底稿/计算表"},
                {"phase": "报告", "days": 3, "deliverable": "审计报告"},
            ],
        },
        "能源审计": {
            "subject": "能源消耗审计（制造业）",
            "scope": "覆盖各类型能源消耗（电力/天然气/蒸汽/柴油/可再生能源）",
            "procedures": [
                {"id": "E1", "name": "能源计量系统评估", "steps": ["检查能源计量器具配备率", "核对计量网络图与实际布局", "抽查计量设备检定证书"]},
                {"id": "E2", "name": "能耗数据核对", "steps": ["收集能源账单台账", "分车间/分产品能耗归集", "单位产品能耗计算与对标"]},
                {"id": "E3", "name": "能效指标验证", "steps": ["计算主要产品单位综合能耗", "与国家标准/行业标杆比较", "分析能耗差异原因"]},
            ],
            "evidence_types": [
                {"category": "必需", "items": ["能源购售发票", "各车间能耗日报/月报", "产品产量台账", "计量器具检定证书"]},
                {"category": "推荐", "items": ["能源管理体系文件", "节能技改项目记录", "能源审计报告"]},
            ],
            "workpaper_fields": [
                "审计对象名称", "审计期间", "能源消费总量（实物量）", "能源消费总量（标准煤）",
                "分品种能耗明细表", "分车间能耗明细表", "单位产品能耗", "能源计量系统描述",
                "节能措施与效果", "审计结论",
            ],
            "risks": [
                {"risk": "计量数据缺失", "mitigation": "关注计量盲区，评估能耗数据可信度分级"},
                {"risk": "能耗归集错误", "mitigation": "核对能耗分配方法，抽查分配比例合理性"},
            ],
            "sample_strategy": "月度全量，重点耗能设备100%覆盖",
            "time_plan": [
                {"phase": "准备", "days": 1, "deliverable": "资料清单"},
                {"phase": "实施", "days": 6, "deliverable": "工作底稿"},
                {"phase": "报告", "days": 2, "deliverable": "审计报告"},
            ],
        },
    },
    "金融业": {
        "气候风险审计": {
            "subject": "气候相关财务风险审计（金融业）",
            "scope": "覆盖TCFD四板块（治理/战略/风险管理/指标目标）及ISSB S2披露要求",
            "procedures": [
                {"id": "F1", "name": "治理架构评估", "steps": ["检查董事会气候风险监督职责", "确认管理层气候风险管理角色", "评估激励机制与气候目标挂钩情况"]},
                {"id": "F2", "name": "气候情景分析验证", "steps": ["核对情景分析方法选择依据", "检查物理风险和转型风险覆盖情况", "验证关键假设参数合理性", "评估情景分析与业务战略的整合度"]},
                {"id": "F3", "name": "风险流程检查", "steps": ["检查气候风险识别流程", "评估气候风险评估方法学", "验证气候风险在现有ERM中的整合度"]},
                {"id": "F4", "name": "投融资组合碳核查", "steps": ["获取投融资组合明细", "验证组合排放估算方法", "检查高碳资产敞口评估"]},
            ],
            "evidence_types": [
                {"category": "必需", "items": ["董事会会议纪要（气候相关）", "气候风险管理制度文件", "情景分析报告", "投融资组合明细", "风险偏好声明"]},
                {"category": "推荐", "items": ["TCFD aligned disclosure", "ISSB readiness assessment", "内部培训记录"]},
                {"category": "验证", "items": ["监管问询函回复", "同行机构披露对比", "NGO/评级机构评估报告"]},
            ],
            "workpaper_fields": [
                "审计对象名称", "审计期间", "适用标准（TCFD/ISSB S2）", "董事会监督评估",
                "管理层角色评估", "气候风险与机遇描述", "情景分析方法学", "情景假设参数",
                "转型风险敞口", "物理风险敞口", "风险整合度评估", "投融资组合碳足迹",
                "审计结论", "发现事项与建议",
            ],
            "risks": [
                {"risk": "情景分析假设不合理", "mitigation": "检查温度路径选择、关键参数、模型来源是否有行业依据"},
                {"risk": "气候风险未整合进现有ERM", "mitigation": "检查气候风险是否进入风险图谱、是否影响资本配置"},
                {"risk": "投融资排放估算方法学偏差", "mitigation": "核对使用的方法学（PCAF/SBTi Sector Standard）和数据质量"},
            ],
            "sample_strategy": "情景分析关键场景全量，投融资组合按资产类别分层抽样",
            "time_plan": [
                {"phase": "准备", "days": 2, "deliverable": "审计计划"},
                {"phase": "实施", "days": 12, "deliverable": "工作底稿"},
                {"phase": "报告", "days": 3, "deliverable": "审计报告"},
            ],
        },
    },
    "其他行业": {
        "通用ESG审计": {
            "subject": "ESG通用审计程序",
            "scope": "覆盖E（环境）/S（社会）/G（治理）三个维度关键议题",
            "procedures": [
                {"id": "G1", "name": "重要性评估", "steps": ["收集影响重要性议题清单", "评估财务重要性", "识别双重重要性交集"]},
                {"id": "G2", "name": "E维度关键议题验证", "steps": ["根据重要性评估结果选择E维度议题", "验证相关指标数据质量", "检查减排/节能/节水目标完成度"]},
                {"id": "G3", "name": "S维度关键议题验证", "steps": ["检查劳工权益（薪酬/工时/安全）", "评估多元化和包容性", "验证供应链社会责任"]},
                {"id": "G4", "name": "G维度关键议题验证", "steps": ["评估董事会结构和独立性", "检查反腐败合规机制", "验证数据治理和透明度"]},
            ],
            "evidence_types": [
                {"category": "必需", "items": ["ESG报告全文", "重要性评估文档", "董事会报告", "员工手册", "反腐败政策"]},
                {"category": "推荐", "items": ["第三方鉴证报告", "员工敬业度调查", "供应商评估报告"]},
            ],
            "workpaper_fields": [
                "审计对象名称", "审计期间", "适用标准", "双重重要性评估结果",
                "E维度审计发现", "S维度审计发现", "G维度审计发现",
                "关键数据验证结果", "审计结论", "发现事项与建议",
            ],
            "risks": [
                {"risk": "重要性评估不完整", "mitigation": "检查评估方法覆盖影响重要性和财务重要性双维度"},
                {"risk": "选择性披露", "mitigation": "对比行业同行披露范围，关注遗漏的重大议题"},
            ],
            "sample_strategy": "按重要性议题全量验证，支持数据抽样30%",
            "time_plan": [
                {"phase": "准备", "days": 2, "deliverable": "审计计划"},
                {"phase": "实施", "days": 8, "deliverable": "工作底稿"},
                {"phase": "报告", "days": 2, "deliverable": "审计报告"},
            ],
        },
    },
}


_AUDIT_GOAL_MAP = {
    "碳排放": "GHG排放审计",
    "气候": "GHG排放审计",
    "能源": "能源审计",
    "能效": "能源审计",
    "气候风险": "气候风险审计",
    "转型风险": "气候风险审计",
    "TCFD": "气候风险审计",
    "全面ESG": "通用ESG审计",
    "综合": "通用ESG审计",
    "水": "通用ESG审计",
    "多样性": "通用ESG审计",
}


class LLMEngine(AbstractEngine):
    """ES-06 AI-ESG审计方法论引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.industry_templates = {}
        self.goal_map = {}

    def _load_model(self):
        self.industry_templates = dict(_INDUSTRY_TEMPLATES)
        self.goal_map = dict(_AUDIT_GOAL_MAP)

    def _preprocess(self, input_data):
        items = input_data if isinstance(input_data, list) else [input_data]
        prepared = []
        for it in items:
            industry = it.get("industry", "其他行业")
            goal = it.get("audit_goal", "全面ESG")
            subject = it.get("subject") or self._match_subject(industry, goal)
            prepared.append({
                "company": it.get("company", ""),
                "industry": industry,
                "size": it.get("size", "中型"),
                "audit_goal": goal,
                "subject": subject,
                "standards": it.get("standards", ["ISSB IFRS S1", "ISSB IFRS S2"]),
                "period": it.get("period", "年度"),
                "scope_notes": it.get("scope_notes", ""),
                "extra_requirements": it.get("extra_requirements", []),
            })
        return prepared

    def _match_subject(self, industry: str, goal: str) -> str:
        if industry in self.industry_templates:
            for g_kw, subj in self.goal_map.items():
                if g_kw.lower() in goal.lower():
                    if subj in self.industry_templates[industry]:
                        return subj
            available = list(self.industry_templates[industry].keys())
            return available[0] if available else "通用ESG审计"
        return "通用ESG审计"

    def _infer(self, prepared):
        methodologies = []
        for p in prepared:
            template = self._select_template(p)
            if not template:
                continue
            methodology = self._build_methodology(p, template)
            methodologies.append(methodology)
        return methodologies

    def _select_template(self, p: dict) -> dict | None:
        ind = p["industry"]
        subj = p["subject"]
        if ind in self.industry_templates and subj in self.industry_templates[ind]:
            return self.industry_templates[ind][subj]
        for ind_name, subjs in self.industry_templates.items():
            if subj in subjs:
                return subjs[subj]
        other = self.industry_templates.get("其他行业", {})
        if subj in other:
            return other[subj]
        if other:
            return list(other.values())[0]
        return None

    def _build_methodology(self, p: dict, tpl: dict) -> dict:
        name = p["company"] or "[企业名称]"
        period = p["period"]
        tpl_subject = tpl["subject"]
        scope = self._customize_scope(tpl["scope"], p)
        procedures = self._customize_procedures(tpl["procedures"], p)
        evidence = self._customize_evidence(tpl["evidence_types"], p)
        workpaper = self._customize_workpaper(tpl["workpaper_fields"], p)
        risks = self._customize_risks(tpl["risks"], p)
        time_plan = self._customize_time_plan(tpl["time_plan"])
        return {
            "methodology_id": f"METH_{abs(hash(f'{name}|{tpl_subject}|{period}')) % 100000:05d}",
            "subject": tpl["subject"],
            "company": name,
            "industry": p["industry"],
            "period": period,
            "applicable_standards": p["standards"],
            "audit_scope": scope,
            "audit_procedures": procedures,
            "evidence_checklist": evidence,
            "workpaper_template": {
                "structure": self._workpaper_structure(workpaper),
                "fields": workpaper,
                "embedded_formulas": self._formula_suggestions(tpl["subject"]),
            },
            "risk_register": risks,
            "sample_strategy": tpl.get("sample_strategy", "按重要性分层抽样"),
            "time_plan": time_plan,
            "quality_checklist": self._quality_checklist(tpl["subject"]),
            "generated_at": datetime.now().isoformat(),
        }

    def _customize_scope(self, base_scope: str, p: dict) -> str:
        extras = []
        if p.get("scope_notes"):
            extras.append(p["scope_notes"])
        if p.get("standards"):
            extras.append(f"适用标准：{', '.join(p['standards'])}")
        if extras:
            return base_scope + "。" + "；".join(extras)
        return base_scope

    def _customize_procedures(self, base_procs: list, p: dict) -> list:
        customized = []
        for proc in base_procs:
            c_proc = dict(proc)
            c_proc["output"] = self._proc_output(proc["name"])
            c_proc["responsible_role"] = "ESG审计组"
            customized.append(c_proc)
        if p.get("extra_requirements"):
            for req in p["extra_requirements"]:
                customized.append({
                    "id": f"EXTRA_{len(customized)}",
                    "name": f"额外要求：{req}",
                    "steps": [f"根据额外要求执行专项审计程序：{req}"],
                    "output": "专项审计记录",
                })
        return customized

    def _customize_evidence(self, base_ev: list, p: dict) -> list:
        return base_ev

    def _customize_workpaper(self, base_fields: list, p: dict) -> list:
        return base_fields

    def _customize_risks(self, base_risks: list, p: dict) -> list:
        return base_risks

    def _customize_time_plan(self, base_plan: list) -> list:
        running = datetime.now()
        planned = []
        for phase in base_plan:
            planned.append({
                **phase,
                "start_date": running.strftime("%Y-%m-%d"),
                "end_date": (running + timedelta(days=phase["days"])).strftime("%Y-%m-%d"),
            })
            running += timedelta(days=phase["days"] + 1)
        return planned

    @staticmethod
    def _proc_output(name: str) -> str:
        if "边界" in name:
            return "组织边界确认表"
        if "数据" in name or "核对" in name:
            return "活动数据验证工作表"
        if "因子" in name:
            return "排放因子确认表"
        if "Scope" in name or "计算" in name:
            return "排放计算表（含公式）"
        if "重算" in name or "勾稽" in name:
            return "重算与勾稽差异分析表"
        return f"{name}审计记录"

    def _workpaper_structure(self, fields: list) -> list:
        sections = ["基本信息", "审计对象描述", "关键数据与计算", "验证结果", "差异分析", "审计结论"]
        grouped = []
        n = len(fields)
        per_sec = max(1, n // len(sections))
        for i, sec in enumerate(sections):
            start = i * per_sec
            end = start + per_sec if i < len(sections) - 1 else n
            grouped.append({
                "section": sec,
                "fields": fields[start:end],
            })
        return grouped

    def _formula_suggestions(self, subject: str) -> list:
        if "GHG" in subject or "排放" in subject:
            return [
                {"name": "Scope1排放", "formula": "Σ(燃料消耗量 × 排放因子 × GWP)"},
                {"name": "Scope2位置法", "formula": "Σ(购电量 × 区域电网OM排放因子)"},
                {"name": "Scope2市场法", "formula": "Σ(购电量 × 供应商/PPA合同排放因子)"},
                {"name": "排放强度", "formula": "总排放量 / 营业收入（或产量）"},
            ]
        if "能源" in subject:
            return [
                {"name": "能源消耗总量", "formula": "Σ(各能源实物量 × 折算系数)"},
                {"name": "单位产品能耗", "formula": "综合能耗 / 产品产量"},
            ]
        if "气候风险" in subject:
            return [
                {"name": "转型风险敞口", "formula": "高碳资产估值 × 情景冲击系数"},
            ]
        return [{"name": "单位指标", "formula": "指标值 / 业务量"}]

    def _quality_checklist(self, subject: str) -> list:
        return [
            {"check": "审计程序覆盖所有重要性议题", "method": "程序清单 vs 重要性评估结果逐一核对"},
            {"check": "证据清单覆盖所有审计程序", "method": "每个程序至少一种必需证据"},
            {"check": "底稿字段可支撑审计报告", "method": "底稿字段 vs 报告披露项勾稽检查"},
            {"check": "适用标准引用准确", "method": "标准编号/版本号核对"},
            {"check": "风险点对应控制措施", "method": "每个风险至少一个缓解措施"},
            {"check": "抽样方法有统计依据", "method": "抽样策略 vs 审计准则要求"},
            {"check": "时间安排合理可行", "method": "各阶段天数 vs 行业经验值"},
        ]

    def _postprocess(self, result):
        if not isinstance(result, list):
            result = [result]
        summary = {
            "total_methodologies": len(result),
            "industries_covered": list({m["industry"] for m in result}),
            "subjects_covered": list({m["subject"] for m in result}),
            "avg_procedures": sum(len(m["audit_procedures"]) for m in result) / max(1, len(result)),
            "avg_evidence_items": sum(
                sum(len(cat["items"]) for cat in m["evidence_checklist"]) for m in result
            ) / max(1, len(result)),
            "generated_at": datetime.now().isoformat(),
        }
        quality_flags = []
        for m in result:
            if not m["evidence_checklist"]:
                quality_flags.append(f"{m['subject']}: 证据清单为空")
            if not m["audit_procedures"]:
                quality_flags.append(f"{m['subject']}: 审计程序为空")
        return {
            "methodologies": result,
            "summary": summary,
            "quality_flags": quality_flags,
            "generated_at": datetime.now().isoformat(),
        }
