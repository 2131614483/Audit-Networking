"""数据→模块接口对齐适配层。

把 demo/synthetic_data/<slug>/ 下的数据文件，
按 modules/shared/network_schema.json 的接口契约 + 各模块 _collect 期望格式，
对齐成 Pipeline.run(input_data) 能接受的输入。

原则：模块代码不动，只做数据侧的字段映射与结构对齐。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_ROOT = Path(__file__).parent / "synthetic_data"


def _load_jsonl(path: Path, slug: str = "", limit: int = 0) -> list[dict]:
    """加载JSONL并注入溯源标记：_source_file / _row_index / _dataset。"""
    if not path.exists():
        return []
    recs = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    # 注入溯源标记（内部字段，引擎需容错）
                    rec["_source_file"] = path.name
                    rec["_row_index"] = i
                    rec["_dataset"] = slug
                recs.append(rec)
    return recs


def _load_text(path: Path, limit: int = 0) -> list[str]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    return lines[:limit] if limit else lines


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_raw_data(slug: str, limit: int = 100) -> dict[str, Any]:
    """加载模块对应的 synthetic_data 原始数据文件，每条记录带溯源标记。"""
    mod_dir = DATA_ROOT / slug
    data: dict[str, Any] = {}
    if not mod_dir.exists():
        return data
    # 按文件扩展名加载
    for f in mod_dir.iterdir():
        if f.suffix == ".jsonl":
            key = f.stem
            data[key] = _load_jsonl(f, slug, limit)
        elif f.suffix == ".json":
            data[f.stem] = _load_json(f)
        elif f.suffix == ".txt":
            data[f.stem] = _load_text(f, limit)
    return data


# ======================================================================
# 模块接口适配规则表
# 每个 slug → 适配函数，把 raw_data 对齐成 pipeline.run() 期望的格式
# 规则来源：network_schema.json inputs[].fields + pipeline._collect() 期望的 key
# ======================================================================

def _adapt_records(raw: dict) -> list[dict]:
    """通用：把 records.jsonl 包装成 [{source, source_type, raw_data}] 格式。"""
    recs = raw.get("records", [])
    return [
        {
            "source": r.get("source", "unknown"),
            "source_type": r.get("source_type", "api"),
            "raw_data": r,
        }
        for r in recs
    ]


def _adapt_documents(raw: dict) -> list[dict]:
    """通用：把 text_corpus 转成 documents 列表。"""
    texts = raw.get("text_corpus", [])
    return [{"content": t, "title": f"文档{i+1}", "doc_type": "文本"} for i, t in enumerate(texts)]


def _adapt_transactions(raw: dict) -> list[dict]:
    """通用：直接取 transactions.jsonl。"""
    return raw.get("transactions", [])


# ---------- 各模块精确适配规则 ----------

ADAPT_RULES: dict[str, Any] = {
    # FA 家族 — engine._preprocess 期望的 key
    "fa_02": lambda r: {"fields": [{"raw_name": k, "source": rec.get("source","ERP")} for rec in r.get("records", [])[:30] for k in rec.keys() if k not in ("source","source_type")][:50]},
    "fa_03": lambda r: {"records": _adapt_records(r), "batch_id": "ADAPT-FA03", "project_code": "P1"},
    "fa_04": lambda r: {"confirmations": r.get("records", [])[:50]},
    "fa_05": lambda r: {"transactions": r.get("confirmations", r.get("records", []))[:50]},
    "fa_06": lambda r: {"items": r.get("confirmations", r.get("records", []))[:50]},
    "fa_07": lambda r: {"entity": {"name": "测试企业", "code": "600001"}, "period": {"year": 2025, "quarter": "Q2"}, "subjects": r.get("shareholders", [])[:20]},
    "fa_08": lambda r: {"workpapers": [{"workpaper_id": f"WP{i+1}", "title": f"底稿{i+1}", "content": d} for i, d in enumerate(r.get("text_corpus", [])[:20])]},
    "fa_09": lambda r: {"workpapers": [{"workpaper_id": f"WP{i+1}", "title": f"底稿{i+1}", "content": d} for i, d in enumerate(r.get("text_corpus", [])[:20])]},
    "fa_10": lambda r: {"shareholders": r.get("shareholders", []), "records": r.get("records", [])[:100]},
    "fa_11": lambda r: {"transactions": r.get("transactions", [])[:50], "peers": [], "history": []},
    "fa_12": lambda r: {"transactions": r.get("transactions", [])[:50], "disclosure_text": " ".join(r.get("text_corpus", [])[:5]), "related_parties": r.get("shareholders", [])},
    # CO 家族
    "co_01": lambda r: {"enterprise": {"name": "测试企业", "industry": "制造业", "code": "600001"}, "regulations": r.get("records", [])[:50]},
    "co_02": lambda r: {"regulation_text": r.get("text_corpus", [""])[0] if r.get("text_corpus") else "", "regulation_title": "测试法规", "enterprise": {"name": "测试企业", "industry": "制造业"}},
    "co_03": lambda r: {"action": "analyze_change", "regulation_change": "测试法规变更通知"},
    "co_04": lambda r: {"transactions": r.get("transactions", [])[:50], "customers": [{"customer_id": t.get("customer_id","C1")} for t in r.get("transactions", [])[:10]]},
    "co_05": lambda r: {"graph": r.get("graph", {}), "nodes": r.get("graph", {}).get("nodes", []), "edges": r.get("graph", {}).get("edges", [])},
    "co_06": lambda r: {"alert": {"alert_id": "A001", "risk_score": 0.8, "entity_id": "E1"}, "transactions": r.get("transactions", [])[:20]},
    "co_07": lambda r: {"assets": r.get("records", [])[:50]},
    "co_08": lambda r: {"systems": [{"system_id": "S1", "name": "ERP"}], "datasets": r.get("records", [])[:30]},
    "co_09": lambda r: {"policies": r.get("records", [])[:50]},
    # IP 家族
    "ip_01": lambda r: {"enterprise": {"name": "测试企业", "code": "600001", "industry": "制造业"}, "financial_data": {"2023": {"revenue": 1000000, "profit": 200000, "assets": 5000000, "paid_in_capital": 3000000}, "2024": {"revenue": 1200000, "profit": 250000, "assets": 5500000, "paid_in_capital": 3000000}, "2025": {"revenue": 1500000, "profit": 300000, "assets": 6000000, "paid_in_capital": 3000000}}},
    "ip_02": lambda r: {"question": r.get("text_corpus", ["请说明关联交易公允性"])[0] if r.get("text_corpus") else "请说明关联交易公允性", "industry": "制造业", "board": "主板"},
    "ip_03": lambda r: {"company_name": "测试企业", "events": [
        {"event_type": "设立", "date": "2015-03-15", "description": "公司成立，注册资本1000万", "shareholders": [{"name": "张三", "ratio": 60}, {"name": "李四", "ratio": 40}], "has_resolution": True},
        {"event_type": "增资", "date": "2017-06-20", "description": "增资至3000万", "shareholders": [{"name": "张三", "ratio": 55}, {"name": "李四", "ratio": 35}, {"name": "王五", "ratio": 10}], "has_resolution": True},
        {"event_type": "股权转让", "date": "2016-01-10", "description": "李四转让5%给王五", "shareholders": [{"name": "张三", "ratio": 60}, {"name": "李四", "ratio": 35}, {"name": "王五", "ratio": 5}], "has_resolution": False},
        {"event_type": "增资", "date": "2019-09-01", "description": "引入战略投资者，增资至5000万", "shareholders": [{"name": "张三", "ratio": 45}, {"name": "李四", "ratio": 28}, {"name": "王五", "ratio": 8}, {"name": "投资机构A", "ratio": 19}], "has_resolution": True},
        {"event_type": "减资", "date": "2021-12-15", "description": "回购部分股权，减资至4500万", "shareholders": [{"name": "张三", "ratio": 48}, {"name": "李四", "ratio": 30}, {"name": "王五", "ratio": 10}, {"name": "投资机构A", "ratio": 12}], "has_resolution": False},
        {"event_type": "改制", "date": "2023-05-20", "description": "整体变更为股份公司", "shareholders": [{"name": "张三", "ratio": 48}, {"name": "李四", "ratio": 30}, {"name": "王五", "ratio": 10}, {"name": "投资机构A", "ratio": 12}], "has_resolution": False},
    ]},
    "ip_04": lambda r: {"financials": {"revenue": 1800000, "profit": 280000, "assets": 5500000, "liabilities": 3200000, "inventory": 1200000, "accounts_receivable": 1500000, "current_assets": 2000000, "current_liabilities": 1600000, "gross_margin": 0.48, "net_margin": 0.16, "current_ratio": 1.25, "debt_ratio": 0.58, "ar_turnover": 2.8, "inv_turnover": 2.1, "rev_yoy": 0.45, "ocf_to_net_profit": 0.42, "related_party_ratio": 0.28}, "industry": "制造业"},
    "ip_05": lambda r: {"query": r.get("text_corpus", ["IPO案例查询"])[0] if r.get("text_corpus") else "IPO案例查询", "industry": "制造业", "board": "主板"},
    "ip_06": lambda r: {"issues": [{"issue_id": f"I{i+1}", "risk_level": "high", "urgency": "urgent", "description": d} for i, d in enumerate(r.get("text_corpus", [])[:20])]},
    # CM 家族
    "cm_01": lambda r: {"metrics": r.get("records", [])[:50]},
    "cm_02": lambda r: r.get("records", [])[:50],
    "cm_03": lambda r: {"action": "recommend", "scenario_text": (r.get("text_corpus", ["持续审计场景"])[0] if r.get("text_corpus") else "持续审计场景"), "top_k": 5, "risk_level": "medium", "resource_level": "medium"},
    "cm_04": lambda r: {"action": "quantify", "risks": [{"risk_id": "R01", "risk_type": "financial_error", "name": "财务差错", "baseline_prob": 0.05, "mitigated_prob": 0.01, "avg_impact": 2000000, "category": "风险避免"}], "costs": {"initial_investment": 7200000, "annual_operating": 2000000, "annual_maintenance": 100000, "annual_training": 50000}, "time_horizon_years": 3, "scenario": "base"},
    "cm_05": lambda r: {"invoices": r.get("records", [])[:20], "orders": r.get("records", [])[:20], "receipts": [], "payments": []},
    # FO 家族
    "fo_01": lambda r: {"transactions": r.get("transactions", [])[:50]},
    "fo_02": lambda r: {"entities": r.get("shareholders", []), "transactions": r.get("transactions", [])[:50]},
    "fo_03": lambda r: {"documents": _adapt_documents(r)},
    "fo_04": lambda r: {"evidence_items": [{"evidence_id": f"E{i+1}", "device_id": "D1", "file_path": d.get("media_uri","")} for i, d in enumerate(r.get("media_refs", [])[:30])]},
    "fo_05": lambda r: {"texts": r.get("text_corpus", [])[:30]},
    "fo_06": lambda r: {"evidence": [{"evidence_id": f"E{i+1}", "evidence_type": "document", "source": "audit"} for i in range(min(20, len(r.get("records", []))))], "cases": []},
    # IT 家族
    "it_01": lambda r: r.get("it_config", r.get("records", [])[:50]),
    "it_02": lambda r: r.get("records", [])[:50],
    "it_03": lambda r: r.get("records", [])[:50],
    "it_04": lambda r: r.get("records", [])[:50],
    "it_05": lambda r: r.get("records", [])[:50],
    # TA 家族 — engine 期望 dict
    "ta_01": lambda r: {"invoices": r.get("invoices", r.get("records", [])[:50])},
    "ta_02": lambda r: {"invoices": r.get("invoices", r.get("records", [])[:20]), "orders": r.get("records", [])[:20], "receipts": [], "payments": []},
    "ta_03": lambda r: {"invoices": r.get("invoices", r.get("records", [])[:30]), "sales_allocation": {"ratio": 0.5}},
    "ta_04": lambda r: {"enterprise": {"name": "测试企业", "industry": "制造业"}, "comparables": r.get("records", [])[:30]},
    "ta_05": lambda r: {"target_company": {"company_id": "T001", "company_name": "测试企业", "industry": "制造业", "revenue": 1000000}, "candidates": [{"company_id": f"C{i+1:03d}", "company_name": f"可比公司{i+1}", "industry": "制造业", "revenue": 900000+i*100000} for i in range(10)]},
    "ta_06": lambda r: {"entities": r.get("shareholders", []), "transactions": r.get("transactions", [])[:50]},
    # SC 家族
    "sc_01": lambda r: {"suppliers": [{**s, "business": {"type": s.get("business","通用")}, "litigation": {}, "financial": {}, "esg": {}} for s in (r.get("suppliers") or [])[:50]] or [{"supplier_id": f"S{i+1}", "name": f"供应商{i+1}", "risk_score": 0.5, "business": {"type": "通用"}, "litigation": {}, "financial": {}, "esg": {}} for i in range(10)]},
    "sc_02": lambda r: {"suppliers": r.get("suppliers", r.get("shareholders", [])), "relations": r.get("graph", {}).get("edges", [])},
    "sc_03": lambda r: {"suppliers": r.get("suppliers", r.get("shareholders", []))},
    "sc_04": lambda r: {"orders": r.get("records", [])[:50]},
    "sc_05": lambda r: {"price_history": r.get("records", [])[:50], "benchmark_queries": []},
    # ES 家族
    "es_01": lambda r: r.get("records", [])[:50],
    "es_02": lambda r: r.get("records", [])[:50],
    "es_03": lambda r: r.get("records", [])[:50],
    "es_04": lambda r: r.get("records", [])[:50],
    "es_05": lambda r: r.get("records", [])[:50],
    "es_06": lambda r: r.get("records", [])[:50],
    # FI 家族 — engine 期望 dict
    "fi_01": lambda r: {"loans": r.get("loans", r.get("records", [])[:50])},
    "fi_02": lambda r: {"entities": r.get("shareholders", []), "guarantees": r.get("guarantees", r.get("records", [])[:50])},
    "fi_03": lambda r: r.get("records", [])[:50],
    "fi_04": lambda r: {"reports": [{"report_id": f"R{i+1}", "items": rec, "receivables_prev_year": rec.get("amount", 0)} for i, rec in enumerate(r.get("records", [])[:30])]},
    "fi_05": lambda r: {"new_regulations": r.get("records", [])[:30], "current_regulations": r.get("records", [])[:30]},
    # IA 家族
    "ia_01": lambda r: {"action": "score", "entity": {"name": "测试企业", "code": "600001"}, "indicators": {f"K{i+1}": d.get("likelihood", 3) for i, d in enumerate((r.get("risks") or r.get("records") or [])[:10])}},
    "ia_02": lambda r: {"action": "monitor", "events": r.get("records", [])[:30]},
    "ia_03": lambda r: {"auditors": [{"auditor_id": f"A{i+1:03d}", "name": f"审计员{i+1}", "skills": {"financial": 7, "it": 5}} for i in range(10)], "projects": [{"project_id": f"P{i+1:03d}", "name": f"项目{i+1}", "required_skills": {"financial": 1}, "estimated_hours": 200, "priority": i+1} for i in range(8)]},
    "ia_04": lambda r: {"findings": [{"finding_id": f"F{i+1:03d}", "title": f"发现{i+1}", "severity": "high", "impact_amount": 100000*(i+1)} for i in range(10)], "projects": [{"project_id": f"P{i+1:03d}", "name": f"项目{i+1}", "estimated_hours": 200} for i in range(5)], "annual_budget": 20000000, "annual_audit_hours": 10000},
    "ia_05": lambda r: {"finding": r.get("text_corpus", ["审计发现"])[0] if r.get("text_corpus") else "审计发现", "industry": "制造业", "issue_type": "内控缺陷", "severity": "一般"},
    "ia_06": lambda r: r.get("records", [])[:50],
    "ia_07": lambda r: r.get("records", [])[:50],
    "ia_08": lambda r: r.get("records", [])[:50],
    # CB 家族 — engine 期望 dict
    "cb_01": lambda r: r.get("cross_border_data", r.get("records", [])[:50]),
    "cb_02": lambda r: r.get("records", [])[:50],
    "cb_03": lambda r: r.get("records", [])[:50],
    "cb_04": lambda r: {"from_standard": "IFRS", "to_standard": "CN_GAAP", "notes": r.get("text_corpus", ["准则转换"])[0] if r.get("text_corpus") else "准则转换", "financial_statements": {}, "industry": "制造业"},
    "cb_05": lambda r: {"action": "translate", "text": r.get("text_corpus", ["翻译文本"])[0] if r.get("text_corpus") else "翻译文本", "target_lang": "en", "source_lang": "zh"},
    "cb_06": lambda r: {"action": "generate_orders", "subsidiaries": [{"name": "子公司A", "risk_level": "medium"}], "group_name": "测试集团", "audit_period": "2025-Q2"},
}


def adapt_data_for_module(slug: str, limit: int = 100) -> Any:
    """加载模块数据并按接口规范对齐，返回 pipeline.run() 期望的输入。"""
    raw = load_raw_data(slug, limit)
    rule = ADAPT_RULES.get(slug)
    if rule is None:
        # 兜底：传 records 列表
        return raw.get("records", [])
    return rule(raw)


# ======================================================================
# 数据溯源：发现条目 → 原始数据记录 反查
# ======================================================================

# 发现字段 → 原始数据集的精确匹配规则
FINDING_KEY_MAP: dict[str, dict[str, str]] = {
    "fa_12": {
        "dataset": "transactions",
        "finding_key": "tx_id",
        "raw_key": "tx_id",
    },
    "fa_11": {
        "dataset": "transactions",
        "finding_key": "tx_id",
        "raw_key": "tx_id",
    },
    "fa_10": {
        "dataset": "shareholders",
        "finding_key": "name",
        "raw_key": "name",
    },
    "ip_01": {
        "dataset": "records",
        "finding_key": "finding_id",
        "raw_key": "id",
    },
    "ip_03": {
        "dataset": "history_events",
        "finding_key": "event_seq",
        "raw_key": "_row_index",
    },
    "ip_04": {
        "dataset": "records",
        "finding_key": "problem_id",
        "raw_key": "id",
    },
    "co_04": {
        "dataset": "transactions",
        "finding_key": "tx_id",
        "raw_key": "tx_id",
    },
    "co_05": {
        "dataset": "transactions",
        "finding_key": "tx_id",
        "raw_key": "tx_id",
    },
}

# 模块 slug → 默认兜底数据集优先级（按从高到低排列，找不到匹配时返回前 N 条）
FALLBACK_DATASET_ORDER: dict[str, list[str]] = {
    "fa_02": ["records", "transactions", "shareholders"],
    "fa_03": ["records", "transactions", "shareholders"],
    "fa_04": ["records", "transactions", "shareholders"],
    "fa_05": ["records", "transactions", "shareholders"],
    "fa_06": ["records", "transactions", "shareholders"],
    "fa_07": ["records", "transactions", "shareholders"],
    "fa_08": ["records", "text_corpus"],
    "fa_09": ["records", "text_corpus"],
    "fa_10": ["shareholders", "records", "transactions"],
    "fa_11": ["transactions", "records", "shareholders"],
    "fa_12": ["transactions", "records", "shareholders"],
    "co_01": ["regulations", "records", "transactions"],
    "co_02": ["regulations", "text_corpus"],
    "co_03": ["regulations", "text_corpus"],
    "co_04": ["transactions", "records"],
    "co_05": ["transactions", "graph"],
    "co_06": ["transactions", "records"],
    "co_07": ["records"],
    "co_08": ["records"],
    "co_09": ["records", "regulations"],
    "ip_01": ["records", "history_events", "cases"],
    "ip_02": ["records", "cases", "text_corpus"],
    "ip_03": ["history_events", "records", "cases"],
    "ip_04": ["records", "cases", "history_events"],
    "ip_05": ["records", "cases", "text_corpus"],
    "ip_06": ["records", "text_corpus"],
    "cm_01": ["records", "events", "alerts"],
    "cm_02": ["records", "events", "alerts"],
    "cm_03": ["records", "alerts"],
    "cm_04": ["records"],
    "cm_05": ["records", "events"],
    "fo_01": ["transactions", "evidence"],
    "fo_02": ["transactions", "graph", "evidence"],
    "fo_03": ["documents", "evidence"],
    "fo_04": ["evidence", "media_refs"],
    "fo_05": ["documents", "transactions"],
    "fo_06": ["evidence", "graph"],
    "it_01": ["configs", "logs", "code_issues"],
    "it_02": ["configs", "code_issues", "logs"],
    "it_03": ["code_issues", "logs"],
    "it_04": ["logs", "configs"],
    "it_05": ["logs", "configs"],
    "ta_01": ["invoices", "transfer_pricing"],
    "ta_02": ["invoices", "records"],
    "ta_03": ["invoices", "records"],
    "ta_04": ["transfer_pricing", "records"],
    "ta_05": ["transfer_pricing", "invoices"],
    "ta_06": ["transfer_pricing", "invoices"],
    "sc_01": ["suppliers", "procurement"],
    "sc_02": ["suppliers", "procurement", "media_refs"],
    "sc_03": ["suppliers", "procurement"],
    "sc_04": ["procurement", "media_refs"],
    "sc_05": ["procurement", "media_refs"],
    "es_01": ["esg_data", "carbon", "satellite_refs"],
    "es_02": ["esg_data", "carbon"],
    "es_03": ["esg_data", "satellite_refs"],
    "es_04": ["esg_data", "carbon"],
    "es_05": ["esg_data", "text_reports"],
    "es_06": ["esg_data", "text_reports"],
    "fi_01": ["loans", "guarantees"],
    "fi_02": ["guarantees", "loans"],
    "fi_03": ["loans", "guarantees"],
    "fi_04": ["regulatory_reports", "loans"],
    "fi_05": ["regulatory_reports"],
    "ia_01": ["risks", "audit_plans", "remediation"],
    "ia_02": ["risks", "audit_plans", "events"],
    "ia_03": ["audit_plans", "risks"],
    "ia_04": ["audit_plans", "remediation", "risks"],
    "ia_05": ["audit_plans", "text_corpus"],
    "ia_06": ["risks", "remediation"],
    "ia_07": ["remediation", "risks"],
    "ia_08": ["remediation", "risks"],
    "cb_01": ["cross_border_data", "regulations", "text_corpus"],
    "cb_02": ["cross_border_data", "regulations"],
    "cb_03": ["regulations", "cross_border_data", "text_corpus"],
    "cb_04": ["regulations", "cross_border_data", "text_corpus"],
    "cb_05": ["cross_border_data", "regulations", "text_corpus"],
    "cb_06": ["cross_border_data", "regulations"],
}

# 兜底时每个数据集返回的记录数
_FALLBACK_PER_DATASET = 3


def _extract_match_values_from_finding(finding: dict, r_key: str) -> list[str]:
    """从 finding 中尽量多维度提取用于匹配的值。

    匹配优先级（按顺序尝试）：
    1. finding 直接字段 (finding[r_key])
    2. detail 文本中的 ID 正则 (TX-xxxx, SAR-xxxx, HIS-xxxx, CASE-xxxx 等)
    3. finding 中的 counterparty/amount/title 等次要字段
    4. detail 中出现的任何中文/英文关键词
    """
    values: list[str] = []
    if not isinstance(finding, dict):
        return values

    # 1. 直接字段匹配
    direct = finding.get(r_key)
    if direct is not None:
        values.append(str(direct))

    # 补充：finding 中有 tx_id, counterparty, name 等字段也尝试
    for alt_key in ("tx_id", "counterparty", "name", "event_id", "id", "case_id", "alert_id"):
        alt_val = finding.get(alt_key)
        if alt_val is not None and str(alt_val) not in values:
            values.append(str(alt_val))

    # 2. detail 文本正则匹配 ID
    detail = finding.get("detail", "") or ""
    title = finding.get("title", "") or ""
    text_bundle = f"{title} {detail}"
    import re
    patterns = [
        r"TX-\d+", r"SAR-\d+", r"HIS-\d+", r"CASE-\d+",
        r"AL\d+", r"R\d+", r"F\d+", r"IP_\d+-\d+", r"FA_\d+-\d+",
    ]
    for pat in patterns:
        for m in re.findall(pat, text_bundle):
            if m not in values:
                values.append(m)

    return values


def lookup_source_records(slug: str, finding: dict, raw_data_cache: dict | None = None) -> list[dict]:
    """根据发现条目反查对应的原始数据记录。

    三级匹配策略：
    1. 精确匹配：按 FINDING_KEY_MAP 指定的 (finding_key, raw_key)
    2. 次级模糊匹配：从 finding 多字段提取值，在核心数据集上扫描
    3. 兜底策略：按 FALLBACK_DATASET_ORDER 返回数据集前 N 条
    """
    # 加载原始数据
    if raw_data_cache is not None and slug in raw_data_cache:
        raw = raw_data_cache[slug]
    else:
        raw = load_raw_data(slug, limit=500)
        if raw_data_cache is not None:
            raw_data_cache[slug] = raw

    if not raw:
        return []

    map_cfg = FINDING_KEY_MAP.get(slug)
    matched: list[dict] = []

    # ===== 策略 1: 精确匹配 =====
    if map_cfg:
        dataset_name = map_cfg["dataset"]
        r_key = map_cfg["raw_key"]
        records = raw.get(dataset_name, [])
        if records:
            match_values = _extract_match_values_from_finding(finding, r_key)
            if match_values:
                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                    rec_val = rec.get(r_key)
                    if rec_val is None:
                        continue
                    if any(str(rec_val) == mv for mv in match_values):
                        matched.append(rec)
                        if len(matched) >= 10:
                            break

    # ===== 策略 2: 次级模糊匹配（扫描 fallback 数据集上的 counterparty/amount/title 等）=====
    if not matched:
        detail = finding.get("detail", "") or ""
        # 从 finding 中提取金额数字、关联方关键词
        amt_match = None
        import re
        amt_m = re.search(r"金额[：: ]*\s*([0-9]{3,}(?:\.[0-9]+)?)", detail)
        if amt_m:
            try:
                amt_match = float(amt_m.group(1))
            except ValueError:
                amt_match = None

        fallback_order = FALLBACK_DATASET_ORDER.get(slug, [])
        for ds_name in fallback_order:
            records = raw.get(ds_name, [])
            if not isinstance(records, list) or not records:
                continue
            # 模糊匹配：金额相近 / 字段包含关键词
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                good = False
                if amt_match is not None:
                    rv = rec.get("amount")
                    if isinstance(rv, (int, float)) and abs(rv - amt_match) / max(amt_match, 1) < 0.001:
                        good = True
                if not good:
                    for field in ("counterparty", "name", "title", "company_name", "event_type"):
                        rv = rec.get(field)
                        if rv and isinstance(rv, str) and len(rv) >= 2 and rv in detail:
                            good = True
                            break
                if good:
                    matched.append(rec)
                    if len(matched) >= 6:
                        break
            if matched:
                break

    # ===== 策略 3: 兜底数据集（始终返回若干条原始数据，保证 UI 有溯源内容）=====
    if not matched:
        fallback_order = FALLBACK_DATASET_ORDER.get(slug, [])
        for ds_name in fallback_order:
            records = raw.get(ds_name, [])
            if isinstance(records, list) and records and isinstance(records[0], dict):
                for rec in records[:_FALLBACK_PER_DATASET]:
                    matched.append(rec)
                break
        # 如果优先级表都没命中，找第一个 dict 列表类型的数据集兜底
        if not matched:
            for v in raw.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    for rec in v[:_FALLBACK_PER_DATASET]:
                        matched.append(rec)
                    break

    return matched
