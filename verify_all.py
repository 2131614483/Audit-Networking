"""验证所有 engine.py 模块可加载和执行。"""
import sys

modules_to_test = [
    ("modules.sc_02.engine", "KGEngine",
     {"entities": [{"entity_id": "A", "name": "供应商A"}, {"entity_id": "B", "name": "公司B"}],
      "transactions": [{"from": "A", "to": "B", "amount": 1000, "year": 2024}]}),
    ("modules.sc_03.engine", "MLEngine",
     {"suppliers": [{"supplier_id": "S1", "name": "供应商1", "quality_score": 0.9,
                     "delivery_rate": 0.95, "claim_count": 0, "months": 24}]}),
    ("modules.sc_04.engine", "MLEngine",
     {"prices": [{"item_code": "P001", "item_name": "零件1", "price": 100.0, "qty": 100},
                 {"item_code": "P001", "item_name": "零件1", "price": 102.0, "qty": 200},
                 {"item_code": "P001", "item_name": "零件1", "price": 98.0, "qty": 150}]}),
    ("modules.sc_05.engine", "MLEngine",
     {"items": [{"item_code": "I1", "category": "电子", "price": 50, "spec": "A"},
                {"item_code": "I1", "category": "电子", "price": 52, "spec": "A"},
                {"item_code": "I1", "category": "电子", "price": 48, "spec": "A"}]}),
    ("modules.ta_01.engine", "CVEngine",
     {"invoices": [{"invoice_no": "INV001", "seller": "公司A", "buyer": "公司B",
                    "amount": 11300, "tax_rate": 0.13,
                    "items": [{"name": "商品", "price": 10000, "tax": 1300}],
                    "date": "2024-01-15"}]}),
    ("modules.ta_02.engine", "MLEngine",
     {"documents": {"invoice": {"no": "INV001", "seller": "A公司", "amount": 10000},
                    "contract": {"no": "CT001", "party": "A公司", "amount": 10000},
                    "delivery": {"no": "DL001", "receiver": "A公司", "amount": 10000},
                    "payment": {"no": "PM001", "payee": "A公司", "amount": 10000}}}),
    ("modules.ta_03.engine", "LLMEngine",
     {"invoices": [{"invoice_no": "INV001",
                    "items": [{"name": "办公福利", "amount": 1000, "tax": 130}],
                    "total_tax": 130}]}),
    ("modules.ta_04.engine", "LLMEngine",
     {"enterprise": {"name": "测试公司", "operating_margin": 0.15},
      "comparables": [{"company_id": "C1", "company_name": "可比1",
                       "operating_margin": 0.12, "full_cost_plus_markup": 0.15, "roa": 0.08},
                      {"company_id": "C2", "company_name": "可比2",
                       "operating_margin": 0.14, "full_cost_plus_markup": 0.16, "roa": 0.09},
                      {"company_id": "C3", "company_name": "可比3",
                       "operating_margin": 0.11, "full_cost_plus_markup": 0.13, "roa": 0.07}]}),
    ("modules.ta_05.engine", "MLEngine",
     {"target_company": {"name": "目标公司", "industry": "制造业",
                         "leverage": 0.5, "operating_margin": 0.15},
      "candidates": [{"company_id": "C1", "company_name": "候选1",
                       "industry": "制造业", "leverage": 0.48, "operating_margin": 0.14},
                      {"company_id": "C2", "company_name": "候选2",
                       "industry": "制造业", "leverage": 0.52, "operating_margin": 0.16}]}),
    ("modules.ta_06.engine", "KGEngine",
     {"entities": [{"entity_id": "E1", "name": "企业1", "country": "中国",
                    "ultimate_parent": "PG", "has_operations": True},
                   {"entity_id": "E2", "name": "控股投资公司", "country": "开曼",
                    "ultimate_parent": "PG", "has_operations": False}],
      "transactions": [{"from": "E1", "to": "E2", "amount": 5000000, "year": 2024},
                       {"from": "E2", "to": "E1", "amount": 5000000, "year": 2023}]}),
    ("modules.fi_01.engine", "MLEngine",
     {"loans": [{"asset_id": "L1", "borrower": "企业A", "amount": 1000000,
                 "industry": "制造业", "collateral_type": "房产", "term_months": 12,
                 "debt_ratio": 0.45, "current_ratio": 1.5, "operating_margin": 0.08,
                 "cashflow_coverage": 1.3, "payment_history": 12}]}),
    ("modules.fi_02.engine", "KGEngine",
     {"entities": [{"entity_id": "G1", "name": "担保人A", "leverage": 0.4,
                    "current_ratio": 1.8, "total_assets": 10000000},
                   {"entity_id": "G2", "name": "借款人B", "leverage": 0.6,
                    "current_ratio": 1.2, "total_assets": 5000000}],
      "guarantees": [{"guarantor": "G1", "borrower": "G2", "amount": 3000000}]}),
    ("modules.fi_04.engine", "LLMEngine",
     {"reports": [{"report_id": "R1", "report_type": "资产负债表", "period": "2024Q1",
                   "items": {"资产总计": 1000, "负债总计": 400, "所有者权益总计": 600,
                             "流动资产合计": 500, "货币资金": 200},
                   "receivables_prev_year": 80, "inventory_prev_year": 50,
                   "pl_net_profit": 100, "cf_net": 80}]}),
    ("modules.fi_05.engine", "LLMEngine",
     {"new_regulations": [{"reg_id": "NR1", "title": "企业会计准则第14号",
                           "content": "一、收入确认条件，满足下列条件的才能予以确认"}],
      "current_regulations": [{"reg_id": "OR1", "title": "企业会计准则第14号（旧）",
                               "content": "一、收入确认，收入是指企业在日常活动中形成的"}]}),
    ("modules.fo_02.engine", "KGEngine",
     {"entities": [{"entity_id": "F1", "name": "公司A"}, {"entity_id": "F2", "name": "公司B"},
                   {"entity_id": "F3", "name": "公司C"}],
      "transactions": [{"from": "F1", "to": "F2", "amount": 500000, "time": "2024-01-01"},
                       {"from": "F2", "to": "F3", "amount": 450000, "time": "2024-01-02"},
                       {"from": "F3", "to": "F1", "amount": 480000, "time": "2024-01-03"}]}),
    ("modules.fo_03.engine", "LLMEngine",
     {"documents": [{"doc_id": "D1", "title": "财务报告",
                     "content": "本公司不存在隐瞒收入、虚列支出的情况，保证所有数据真实可靠。"},
                    {"doc_id": "D2", "title": "内部文件",
                     "content": "关于资金挪用问题可能需要进一步调查，或许涉及利益输送"}]}),
    ("modules.fo_04.engine", "CVEngine",
     {"evidence_items": [{"evidence_id": "E1", "filename": "report.pdf", "size": 1024,
                           "content": "这是一份财务报告的内容摘要...", "timestamp": "2024-01-15T10:00:00",
                           "author": "张三", "source": "邮件附件"},
                         {"evidence_id": "E2", "filename": "email.eml", "size": 2048,
                           "content": "关于合同事宜的讨论邮件内容...", "timestamp": "2024-01-16T14:30:00",
                           "author": "李四", "source": "邮箱导出"}]}),
    ("modules.fo_05.engine", "LLMEngine",
     {"texts": [{"text_id": "T1",
                 "content": "本合同由甲方Party A与乙方Party B签订，适用法律为中华人民共和国法律。",
                 "source_lang": "", "target_lang": "zh"},
                {"text_id": "T2",
                 "content": "This agreement shall be governed by the laws of the PRC."}]}),
    ("modules.fo_06.engine", "LLMEngine",
     {"evidence": [{"evidence_id": "E1", "case_id": "CASE001",
                    "content": "2024年1月15日张三先生代表北京科技有限公司签订合同，金额为人民币500万元",
                    "timestamp": "2024-01-15", "source": "合同文件"},
                   {"evidence_id": "E2", "case_id": "CASE001",
                    "content": "2024年1月16日从北京科技有限公司转账500万元到上海贸易公司",
                    "timestamp": "2024-01-16", "source": "银行记录"},
                   {"evidence_id": "E3", "case_id": "CASE001",
                    "content": "2024年1月17日李四女士确认收到上海贸易公司货物，金额500万元",
                    "timestamp": "2024-01-17", "source": "收货单"}],
      "cases": [{"case_id": "CASE001", "case_name": "合同纠纷案"}]}),
]

print("=" * 70)
print(" Module Load & Execute Verification")
print("=" * 70)

results = []
for mod_path, cls_name, test_input in modules_to_test:
    short = mod_path.split(".")[1]
    try:
        mod = __import__(mod_path, fromlist=[cls_name])
        cls = getattr(mod, cls_name)
        inst = cls()
        inst.execute(test_input)
        inst.close()
        results.append((short, "PASS", ""))
        print(f"  [OK]   {short:8s} {cls_name:12s}")
    except Exception as e:
        err = str(e)[:120]
        results.append((short, "FAIL", err))
        print(f"  [FAIL] {short:8s} {cls_name:12s} -> {err}")

print()
pass_count = sum(1 for _, s, _ in results if s == "PASS")
fail_count = sum(1 for _, s, _ in results if s == "FAIL")
print(f"Total: {len(results)} modules, {pass_count} passed, {fail_count} failed")
if fail_count > 0:
    print()
    print("Failures:")
    for short, status, err in results:
        if status == "FAIL":
            print(f"  {short}: {err}")
sys.exit(0 if fail_count == 0 else 1)
