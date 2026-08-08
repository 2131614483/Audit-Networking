#!/usr/bin/env python3
"""成品 Demo —— 7 个模块真实算法端到端运行展示。

已实现模块（非 TODO 桩，可直接运行）：
  ┌─────────┬──────────────────────────┬──────────┬────────────────────────┐
  │ 模块     │ 名称                      │ 家族      │ 算法                    │
  ├─────────┼──────────────────────────┼──────────┼────────────────────────┤
  │ FA-02   │ 多源数据自动标准化         │ ml_nlp   │ 同义词映射+相似度匹配    │
  │ FO-01   │ 全量交易智能舞弊扫描       │ ml_nlp   │ Benford定律+Z-Score     │
  │ SC-01   │ 供应商风险智能评分         │ ml_nlp   │ 五维加权评分             │
  │ CM-02   │ 智能预警分级与自动处理     │ rpa      │ 多规则评分+分级路由      │
  │ CO-04   │ AML智能交易监控           │ kg_gnn   │ 五模式可疑交易检测       │
  │ FI-03   │ ML贷款违约预测            │ ml_nlp   │ 逻辑回归(sigmoid)       │
  │ ES-02   │ AI碳排放自动核算          │ ml_nlp   │ 排放因子法(IPCC)        │
  └─────────┴──────────────────────────┴──────────┴────────────────────────┘

运行方式：
  python tools/module-scaffold/demo.py
"""
from __future__ import annotations

import math
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ============================================================
# 模拟数据生成
# ============================================================

def gen_field_data():
    """FA-02: 多源字段映射数据（含名称变体）。"""
    return {
        "source": "ERP_SAP",
        "fields": [
            {"raw_name": "注册资本", "value": 5000, "source": "ERP_SAP"},
            {"raw_name": "注册资金", "value": 3000, "source": "Bank_ICBC"},
            {"raw_name": "注册资本金", "value": 2000, "source": "SRM"},
            {"raw_name": "营业收入", "value": 12000, "source": "ERP_SAP"},
            {"raw_name": "营收", "value": 8000, "source": "Bank_ICBC"},
            {"raw_name": "净利润", "value": 3500, "source": "ERP_SAP"},
            {"raw_name": "纯利润", "value": 1500, "source": "SRM"},
            {"raw_name": "资产负债率", "value": 0.45, "source": "ERP_SAP"},
            {"raw_name": "负债率", "value": 0.12, "source": "Bank_ICBC"},
            {"raw_name": "流动比率", "value": 2.1, "source": "ERP_SAP"},
            {"raw_name": "current_ratio", "value": 1.8, "source": "SRM"},
        ],
    }


def gen_transactions(n=2000, seed=42):
    """FO-01: 交易流水（Benford 分布 + 注入异常）。"""
    rng = random.Random(seed)
    cps = [f"CP{i:04d}" for i in range(200)]
    cats = ["采购", "销售", "费用", "薪酬", "税费"]
    txs = []
    for i in range(n):
        amt = round(10 ** rng.uniform(1.0, 7.0), 2)
        txs.append({"tx_id": f"TX{i:06d}", "amount": amt,
                     "counterparty": rng.choice(cps), "category": rng.choice(cats),
                     "date": f"2025-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}"})
    for i in range(0, n, 50):   # 大额异常
        txs[i]["amount"] = round(rng.uniform(5e6, 1e7), 2)
    for i in range(10, n, 80):  # 整数金额
        txs[i]["amount"] = float(rng.randint(50, 500) * 10000)
    for i in range(5, n, 200):  # 大额整数（双重异常：Z>3 + 整数）
        txs[i]["amount"] = float(rng.randint(700, 999) * 10000)
    return txs


def gen_suppliers(n=150, seed=7):
    """SC-01: 供应商数据（五维风险特征 + 15% 高风险）。"""
    rng = random.Random(seed)
    suppliers = []
    for i in range(n):
        hi = rng.random() < 0.15
        if hi:
            s = {"supplier_id": f"SUP{i:04d}", "name": f"高风险供应商{i:03d}号",
                 "registered_capital": rng.uniform(10, 100), "establishment_years": rng.uniform(0.5, 2),
                 "litigation_count": rng.randint(5, 20), "executed_count": rng.randint(2, 8),
                 "debt_ratio": rng.uniform(0.75, 0.95), "current_ratio": rng.uniform(0.5, 0.9),
                 "esg_penalty": rng.randint(2, 6), "carbon_intensity": rng.uniform(80, 150),
                 "negative_news": rng.randint(10, 30), "sentiment_score": rng.uniform(-0.8, -0.3)}
        else:
            s = {"supplier_id": f"SUP{i:04d}", "name": f"供应商{i:03d}号",
                 "registered_capital": rng.uniform(500, 5000), "establishment_years": rng.uniform(5, 20),
                 "litigation_count": rng.randint(0, 2), "executed_count": 0,
                 "debt_ratio": rng.uniform(0.2, 0.55), "current_ratio": rng.uniform(1.5, 3.0),
                 "esg_penalty": rng.randint(0, 1), "carbon_intensity": rng.uniform(10, 50),
                 "negative_news": rng.randint(0, 3), "sentiment_score": rng.uniform(0.2, 0.8)}
        suppliers.append(s)
    rng.shuffle(suppliers)
    return suppliers


def gen_alerts(n=100, seed=99):
    """CM-02: 告警事件（多维度属性）。"""
    rng = random.Random(seed)
    cats = ["fraud", "aml", "sanction", "normal", "compliance", "operational"]
    sources = ["交易系统", "风控引擎", "合规检查", "行为分析"]
    alerts = []
    for i in range(n):
        hi = rng.random() < 0.2
        a = {
            "alert_id": f"ALT{i:05d}",
            "source": rng.choice(sources),
            "category": rng.choice(cats),
            "amount": rng.uniform(2e6, 8e6) if hi else rng.uniform(1e4, 5e5),
            "frequency": rng.randint(15, 30) if hi else rng.randint(1, 8),
            "after_hours": rng.random() < 0.3,
            "repeat_count": rng.randint(5, 10) if hi else rng.randint(0, 2),
        }
        alerts.append(a)
    return alerts


def gen_aml_transactions(n=500, seed=123):
    """CO-04: AML 交易数据（含可疑模式）。"""
    rng = random.Random(seed)
    txs = []
    # 正常交易
    for i in range(n):
        txs.append({
            "tx_id": f"AML{i:06d}", "customer_id": f"C{rng.randint(1,100):03d}",
            "counterparty": f"C{rng.randint(1,100):03d}", "amount": round(rng.uniform(1000, 40000), 2),
            "channel": rng.choice(["transfer", "cash", "transfer", "transfer"]),
            "jurisdiction": "CN", "hour": rng.randint(8, 20),
        })
    # 注入结构化交易（Smurfing）：3笔 45000 元
    for i in range(3):
        txs.append({"tx_id": f"SMURF{i}", "customer_id": "C200", "counterparty": "C201",
                     "amount": 46000.0, "channel": "transfer", "jurisdiction": "CN", "hour": 10})
    # 注入高风险地区交易
    txs.append({"tx_id": "HRISK0", "customer_id": "C300", "counterparty": "C301",
                "amount": 500000.0, "channel": "transfer", "jurisdiction": "IRAN", "hour": 14})
    # 注入大额现金
    txs.append({"tx_id": "CASH00", "customer_id": "C400", "counterparty": "C401",
                "amount": 250000.0, "channel": "cash", "jurisdiction": "CN", "hour": 11})
    # 注入夜间密集交易
    for i in range(6):
        txs.append({"tx_id": f"NIGHT{i}", "customer_id": "C500", "counterparty": f"C{600+i}",
                     "amount": round(rng.uniform(5000, 20000), 2), "channel": "transfer",
                     "jurisdiction": "CN", "hour": rng.randint(1, 5)})
    # 注入快速往返
    txs.append({"tx_id": "RT_OUT", "customer_id": "C700", "counterparty": "C701",
                "amount": 300000.0, "channel": "transfer", "jurisdiction": "CN", "hour": 9})
    txs.append({"tx_id": "RT_BACK", "customer_id": "C701", "counterparty": "C700",
                "amount": 280000.0, "channel": "transfer", "jurisdiction": "CN", "hour": 10})
    return txs


def gen_applicants(n=50, seed=55):
    """FI-03: 贷款申请人数据。"""
    rng = random.Random(seed)
    applicants = []
    for i in range(n):
        hi = rng.random() < 0.25
        if hi:
            a = {"applicant_id": f"A{i:04d}", "name": f"高风险申请人{i:03d}",
                 "credit_score": rng.randint(450, 580), "dti_ratio": rng.uniform(0.45, 0.65),
                 "ltv_ratio": rng.uniform(0.85, 0.98), "employment_years": rng.uniform(0.5, 3),
                 "default_history": rng.randint(1, 3), "loan_amount": rng.uniform(300000, 800000)}
        else:
            a = {"applicant_id": f"A{i:04d}", "name": f"申请人{i:03d}",
                 "credit_score": rng.randint(650, 800), "dti_ratio": rng.uniform(0.15, 0.35),
                 "ltv_ratio": rng.uniform(0.50, 0.75), "employment_years": rng.uniform(5, 15),
                 "default_history": 0, "loan_amount": rng.uniform(100000, 400000)}
        applicants.append(a)
    rng.shuffle(applicants)
    return applicants


def gen_activities():
    """ES-02: 碳排放活动数据（企业年度消耗）。"""
    return [
        {"id": "ACT001", "type": "natural_gas", "amount": 50000, "unit": "m³"},
        {"id": "ACT002", "type": "diesel", "amount": 8000, "unit": "L"},
        {"id": "ACT003", "type": "coal", "amount": 2000, "unit": "kg"},
        {"id": "ACT004", "type": "gasoline", "amount": 15000, "unit": "L"},
        {"id": "ACT005", "type": "refrigerant_r410a", "amount": 50, "unit": "kg"},
        {"id": "ACT006", "type": "electricity", "amount": 1200000, "unit": "kWh"},
        {"id": "ACT007", "type": "steam", "amount": 500000, "unit": "MJ"},
        {"id": "ACT008", "type": "air_travel", "amount": 800000, "unit": "passenger-km"},
        {"id": "ACT009", "type": "commute_bus", "amount": 1500000, "unit": "passenger-km"},
    ]


# ============================================================
# 模块运行 + 结果展示
# ============================================================

_sep = "─" * 72

def _header(title):
    print(f"\n{_sep}")
    print(f"  {title}")
    print(_sep)


def run_fa_02():
    _header("FA-02 多源数据自动标准化")
    from modules.fa_02.pipeline import Pipeline
    pipe = Pipeline()
    result = pipe.run(gen_field_data())
    stats = result.get("statistics", {})
    fields = result.get("standardized_fields", [])
    print(f"  输入: {stats.get('total', len(fields))} 个原始字段（来自 ERP/银行/SRM 多系统）")
    print(f"  匹配: {stats.get('mapped', 0)} 个成功标准化  需复核: {stats.get('need_review', 0)}  未匹配: {stats.get('unmapped', 0)}")
    print(f"  {'原始字段名':<16} {'标准字段名':<24} {'置信度':<8} {'科目代码':<10} {'需复核'}")
    for f in fields:
        std = f.get("standard_name") or "—"
        conf = f.get("confidence", 0)
        sub = f.get("subject_code") or "—"
        rev = "✗" if f.get("need_review") else "✓"
        print(f"  {f['raw_name']:<16} {std:<24} {conf:<8.2f} {sub:<10} {rev}")


def run_fo_01():
    _header("FO-01 全量交易智能舞弊扫描")
    from modules.fo_01.pipeline import Pipeline
    pipe = Pipeline()
    txs = gen_transactions(2000)
    result = pipe.run({"transactions": txs})
    s = result["risk_summary"]
    print(f"  扫描 {result['total_transactions']} 笔交易")
    print(f"  Benford 卡方={result['benford_chi_square']}  偏差={result['benford_deviation']}")
    print(f"  检出异常: {result['flagged_count']} 笔  (红={s['high_risk']} 橙={s['medium_risk']} 黄={s['low_risk']})")
    print(f"  金额统计: 均值={result['amount_stats']['mean']:,.0f}  标准差={result['amount_stats']['std']:,.0f}")
    print(f"\n  Top-5 异常交易:")
    print(f"  {'交易ID':<12} {'金额':>14} {'风险分':>6} {'Z值':>7}  原因")
    for f in result["flagged_transactions"][:5]:
        print(f"  {f['tx_id']:<12} {f['amount']:>14,.2f} {f['risk_score']:>6} {f['z_score']:>7.2f}  {', '.join(f['reasons'])}")


def run_sc_01():
    _header("SC-01 供应商风险智能评分")
    from modules.sc_01.pipeline import Pipeline
    pipe = Pipeline()
    result = pipe.run({"suppliers": gen_suppliers(150)})
    s = result["summary"]
    print(f"  评估 {s['total']} 家供应商")
    print(f"  风险分级: 红={s['red']}  橙={s['orange']}  黄={s['yellow']}  绿={s['green']}")
    print(f"\n  Top-5 高风险供应商:")
    print(f"  {'ID':<10} {'名称':<20} {'总分':>5} {'等级':<4} {'工商':>4} {'司法':>4} {'财务':>4} {'ESG':>4} {'舆情':>4}")
    for r in result["suppliers"][:5]:
        sub = r["sub_scores"]
        print(f"  {r['supplier_id']:<10} {r['name']:<20} {r['risk_score']:>5.1f} {r['level']:<4} "
              f"{sub['business']:>4.0f} {sub['litigation']:>4.0f} {sub['financial']:>4.0f} "
              f"{sub['esg']:>4.0f} {sub['sentiment']:>4.0f}")


def run_cm_02():
    _header("CM-02 智能预警分级与自动处理")
    from modules.cm_02.pipeline import Pipeline
    pipe = Pipeline()
    result = pipe.run({"alerts": gen_alerts(100)})
    s = result["summary"]
    print(f"  处理 {s['total']} 条告警")
    print(f"  分级: P0(立即处置)={s['P0']}  P1(专项审查)={s['P1']}  P2(监控)={s['P2']}  P3(归档)={s['P3']}")
    print(f"  自动关闭: {s['auto_closed']} 条")
    print(f"\n  Top-5 高优先级告警:")
    print(f"  {'告警ID':<10} {'来源':<10} {'类别':<12} {'分数':>4} {'等级':<4} {'处置'}")
    for r in result["alerts"][:5]:
        print(f"  {r['alert_id']:<10} {r['source']:<10} {r['category']:<12} "
              f"{r['severity_score']:>4} {r['priority']:<4} {r['action_desc']}")


def run_co_04():
    _header("CO-04 AML 智能交易监控")
    from modules.co_04.pipeline import Pipeline
    pipe = Pipeline()
    txs = gen_aml_transactions(500)
    result = pipe.run({"transactions": txs})
    s = result["summary"]
    print(f"  监控 {result['total_transactions']} 笔交易")
    print(f"  生成 SAR: {s['total_sars']} 份  (高风险={s['high_risk']} 中风险={s['medium_risk']} 低风险={s['low_risk']})")
    print(f"  检出模式: {', '.join(s['patterns'])}")
    print(f"\n  Top-5 可疑活动报告 (SAR):")
    print(f"  {'SAR ID':<20} {'模式':<24} {'风险分':>5} {'涉及交易'}")
    for sar in result["sars"][:5]:
        txs_short = ",".join(str(t) for t in sar.get("transactions", [])[:3])
        print(f"  {sar['sar_id']:<20} {sar['pattern']:<24} {sar['risk_score']:>5} {txs_short}")


def run_fi_03():
    _header("FI-03 ML 贷款违约预测")
    from modules.fi_03.pipeline import Pipeline
    pipe = Pipeline()
    result = pipe.run({"applicants": gen_applicants(50)})
    s = result["summary"]
    print(f"  评估 {s['total']} 位申请人")
    print(f"  审批结果: 通过={s['approved']}  人工复核={s['review']}  拒绝={s['rejected']}")
    print(f"  平均违约概率: {s['avg_probability']:.2%}")
    print(f"\n  Top-5 高风险申请人:")
    print(f"  {'ID':<8} {'名称':<16} {'违约概率':>8} {'评级':<4} {'决策':<8} {'信用分':>5} {'负债率':>6}")
    for r in result["applicants"][:5]:
        f = r["features"]
        print(f"  {r['applicant_id']:<8} {r['name']:<16} {r['default_probability']:>8.2%} "
              f"{r['rating']:<4} {r['decision']:<8} {f.get('credit_score',0):>5} {f.get('dti_ratio',0):>6.2f}")


def run_es_02():
    _header("ES-02 AI 碳排放自动核算")
    from modules.es_02.pipeline import Pipeline
    pipe = Pipeline()
    result = pipe.run({"activities": gen_activities()})
    s = result["summary"]
    print(f"  核算 {s['activity_count']} 项活动数据")
    print(f"  总排放量: {s['total_emission_tons']:.2f} 吨 CO₂e")
    print(f"  Scope 1 (直接排放):     {s['scope_1_tons']:>10.2f} 吨")
    print(f"  Scope 2 (电力间接):     {s['scope_2_tons']:>10.2f} 吨")
    print(f"  Scope 3 (其他间接):     {s['scope_3_tons']:>10.2f} 吨")
    print(f"\n  活动明细:")
    print(f"  {'ID':<8} {'类型':<22} {'范围':<10} {'消耗量':>12} {'排放(吨)':>10}")
    for a in result["activities"]:
        print(f"  {a['activity_id']:<8} {a['type']:<22} {a['scope']:<10} "
              f"{a['amount']:>12,.0f} {a['emission_tons']:>10.4f}")


# ============================================================
# 主入口
# ============================================================

def main():
    print("=" * 72)
    print("  预制菜模块成品 Demo —— 7 个模块真实算法端到端运行")
    print("  数据来源：模拟生成（含注入异常，覆盖各模块检测场景）")
    print("=" * 72)

    runners = [
        ("FA-02 多源数据自动标准化", run_fa_02),
        ("FO-01 全量交易智能舞弊扫描", run_fo_01),
        ("SC-01 供应商风险智能评分",   run_sc_01),
        ("CM-02 智能预警分级",         run_cm_02),
        ("CO-04 AML交易监控",          run_co_04),
        ("FI-03 贷款违约预测",         run_fi_03),
        ("ES-02 碳排放核算",           run_es_02),
    ]

    ok, fail = 0, 0
    for name, runner in runners:
        try:
            runner()
            ok += 1
        except Exception as e:
            print(f"\n{_sep}")
            print(f"  {name}  →  运行失败: {e}")
            print(_sep)
            import traceback
            traceback.print_exc()
            fail += 1

    print(f"\n{'=' * 72}")
    print(f"  Demo 完成：{ok + fail} 个模块  →  成功 {ok}  /  失败 {fail}")
    if fail == 0:
        print("  ✅ 全部模块算法真实可用，端到端跑通")
    print(f"{'=' * 72}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
