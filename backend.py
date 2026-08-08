"""智能审计编排后端服务。

提供 API：
  POST /api/plan    - 调用 DeepSeek LLM 规划审计方案
  POST /api/execute - 执行审计方案（返回各模块模拟结果）
  GET  /api/cases   - 获取预设案例列表

启动：python backend.py （默认端口 9000）
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from modules.shared.orchestrator import LLMPlanner, ContractValidator, MODULE_NAMES, DATA_EDGES, _family_of

app = FastAPI(title="智能审计编排后端", version="1.0")

# 允许跨域（前端 file:// 或其他端口访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlanRequest(BaseModel):
    requirement: str


class ExecuteRequest(BaseModel):
    modules: list[str]
    edges: list[list[str]]  # [[s, t], ...]


@app.post("/api/plan")
def plan(req: PlanRequest):
    """调用 DeepSeek LLM 规划审计方案。"""
    try:
        planner = LLMPlanner()
        plan = planner.plan(req.requirement)
        
        validator = ContractValidator()
        validator.validate(plan)
        
        return {
            "success": True,
            "reasoning": plan.reasoning,
            "modules": plan.modules,
            "edges": [list(e) for e in plan.edges],
            "contract_valid": plan.contract_valid,
            "contract_issues": plan.contract_issues,
            "steps": [
                {
                    "slug": s.slug,
                    "name": s.name,
                    "family": s.family,
                    "inputs": s.inputs,
                    "outputs": s.outputs,
                }
                for s in plan.steps
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# 预设案例的模拟执行结果（与前端 CASES 数据一致）
CASE_RESULTS = {
    # 关联交易案例
    "fa_02": {"status": "done", "duration": 0.3, "summary": "标准化 24 条多源数据（ERP/银行/合同），字段映射 15 个，去重 3 条", "output": {"data_type": "标准化数据集", "records_count": 21, "sources": ["ERP","银行流水","合同系统"], "quality_score": 0.92}},
    "fa_03": {"status": "done", "duration": 0.5, "summary": "数据湖三区分层：ODS 21条 → DWD 18条 → ADS 12条", "output": {"data_type": "数据湖分区数据", "ods": 21, "dwd": 18, "ads": 12, "reuse_rate": 0.67}},
    "fa_10": {"status": "done", "duration": 1.2, "summary": "发现 5 个关联方实体，构建关联关系图谱（17个节点，23条边）", "output": {"data_type": "关联方图谱", "entities": 5, "relations": 23}},
    "fa_11": {"status": "done", "duration": 0.8, "summary": "定价公允性分析：12笔关联交易中4笔偏离市场价格超10%", "output": {"data_type": "定价公允性分析结果", "total_transactions": 12, "deviation_count": 4, "max_deviation": "113.3%"}},
    "fa_12": {"status": "done", "duration": 0.6, "summary": "披露完整性检查：发现2项未披露关联交易", "output": {"data_type": "披露完整性报告", "disclosed": 10, "undisclosed": 2}},
    # AML案例
    "co_04": {"status": "done", "duration": 0.9, "summary": "AML三层监控：规则层告警18条 → ML层确认8条 → GNN层识别3个可疑网络", "output": {"data_type": "AML告警", "rule_alerts": 18, "ml_confirmed": 8, "gnn_networks": 3}},
    "co_05": {"status": "done", "duration": 1.1, "summary": "洗钱网络发现：识别3个资金闭环网络，涉及7个账户", "output": {"data_type": "洗钱网络图谱", "networks": 3, "accounts": 7, "total_flow": 14200000}},
    "co_06": {"status": "done", "duration": 0.7, "summary": "生成3份可疑交易报告（STR），涉及金额1420万元", "output": {"data_type": "可疑交易报告", "reports": 3, "total_amount": 14200000}},
    # IPO案例
    "co_01": {"status": "done", "duration": 0.8, "summary": "法规监控：匹配IPO相关法规42条，影响评估5项高风险", "output": {"data_type": "法规变更事件", "regulations": 42, "high_risk": 5}},
    "ip_01": {"status": "done", "duration": 1.5, "summary": "IPO规范性诊断：综合评分72/100，发现7项需整改问题", "output": {"data_type": "IPO审计诊断报告", "score": 72, "issues": 7, "critical": 2}},
    # 其他模块默认结果
}

def _default_result(slug):
    name = MODULE_NAMES.get(slug, slug)
    return {"status": "done", "duration": 0.5, "summary": f"{name}执行完成", "output": {"data_type": "分析结果", "module": slug}}


@app.post("/api/execute")
def execute(req: ExecuteRequest):
    """执行审计方案（返回各模块模拟结果）。"""
    results = {}
    for slug in req.modules:
        results[slug] = CASE_RESULTS.get(slug, _default_result(slug))
    return {"success": True, "module_results": results}


@app.get("/api/cases")
def cases():
    """获取预设案例。"""
    return {
        "cases": [
            {"id": "related_party", "title": "关联交易公允性审计", "requirement": "审计公司与关联方之间的交易，检查关联方披露完整性、交易定价公允性。重点关注关联采购定价是否偏离市场价格，担保费支出是否合理，关联方披露是否完整。"},
            {"id": "aml", "title": "反洗钱可疑交易审计", "requirement": "对银行客户交易进行反洗钱监控，发现可疑交易网络并生成可疑交易报告。重点关注资金闭环、拆分交易、快进快出等可疑模式。"},
            {"id": "ipo", "title": "IPO财务规范性审计", "requirement": "IPO前财务规范性诊断，检查关联方关系完整性和历史沿革合规性，确保符合上市监管要求。"},
        ]
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "智能审计编排后端"}


if __name__ == "__main__":
    import uvicorn
    print("启动智能审计编排后端服务: http://localhost:9000")
    print("API 文档: http://localhost:9000/docs")
    uvicorn.run(app, host="0.0.0.0", port=9000)
