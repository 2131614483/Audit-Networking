"""审计案例测试数据 —— 基于真实审计案例构造的演示数据。

案例1：关联交易公允性审计（参考卓郎智能/金徽矿业案例）
案例2：反洗钱可疑交易审计（参考兴业银行AML案例）
案例3：IPO财务规范性审计（参考监管问询案例）
"""
from __future__ import annotations


# ======================================================================
# 案例1：关联交易公允性审计
# 参考卓郎智能、金徽矿业等关联交易违规案例
# ======================================================================

CASE_RELATED_PARTY = {
    "title": "关联交易公允性审计",
    "requirement": "审计公司与关联方之间的交易，检查关联方披露完整性、交易定价公允性",
    "expected_modules": ["fa_02", "fa_03", "fa_10", "fa_11", "fa_12"],
    "input_data": {
        # 多源原始数据：ERP系统、银行流水、合同系统
        "records": [
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6001", "period": "2025-06", "amount": 5800000, "counterparty": "卓郎科技", "description": "关联采购-原材料"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6601", "period": "2025-06", "amount": 320000, "counterparty": "实控人王某", "description": "担保费支出"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6001", "period": "2025-06", "amount": 2300000, "counterparty": "卓郎科技", "description": "原材料采购第二批"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6601", "period": "2025-06", "amount": 850000, "counterparty": "懋达实业", "description": "技术服务费"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6001", "period": "2025-06", "amount": 1200000, "counterparty": "华信投资", "description": "设备采购"}},
            {"source": "银行", "source_type": "csv", "raw_data": {"company_code": "600001", "account_code": "1002", "period": "2025-06", "amount": -1500000, "counterparty": "懋达实业", "description": "关联采购付款"}},
            {"source": "银行", "source_type": "csv", "raw_data": {"company_code": "600001", "account_code": "1002", "period": "2025-06", "amount": -5800000, "counterparty": "卓郎科技", "description": "原材料采购付款"}},
            {"source": "银行", "source_type": "csv", "raw_data": {"company_code": "600001", "account_code": "1002", "period": "2025-06", "amount": -320000, "counterparty": "实控人王某", "description": "担保费支付"}},
            {"source": "银行", "source_type": "csv", "raw_data": {"company_code": "600001", "account_code": "1002", "period": "2025-06", "amount": -850000, "counterparty": "懋达实业", "description": "技术服务费支付"}},
            {"source": "合同", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "1401", "period": "2025-06", "amount": 2300000, "counterparty": "卓郎科技", "description": "原材料采购合同"}},
            {"source": "合同", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "1401", "period": "2025-06", "amount": 1200000, "counterparty": "华信投资", "description": "设备采购合同"}},
            {"source": "合同", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "1401", "period": "2025-06", "amount": 850000, "counterparty": "懋达实业", "description": "技术服务协议"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6601", "period": "2025-06", "amount": 450000, "counterparty": "卓郎科技", "description": "仓储租赁费"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6601", "period": "2025-06", "amount": 680000, "counterparty": "华信投资", "description": "资金占用费"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6001", "period": "2025-06", "amount": 3200000, "counterparty": "懋达实业", "description": "关联采购-辅料"}},
            {"source": "银行", "source_type": "csv", "raw_data": {"company_code": "600001", "account_code": "1002", "period": "2025-06", "amount": -3200000, "counterparty": "懋达实业", "description": "辅料采购付款"}},
            {"source": "合同", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "1401", "period": "2025-06", "amount": 3200000, "counterparty": "懋达实业", "description": "辅料采购合同"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6601", "period": "2025-06", "amount": 150000, "counterparty": "实控人王某", "description": "咨询费"}},
            {"source": "银行", "source_type": "csv", "raw_data": {"company_code": "600001", "account_code": "1002", "period": "2025-06", "amount": -680000, "counterparty": "华信投资", "description": "资金占用费支付"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "600001", "account_code": "6601", "period": "2025-06", "amount": 950000, "counterparty": "卓郎科技", "description": "商标使用许可费"}},
        ],
        # 股东及关联方信息
        "shareholders": [
            {"name": "王某", "role": "实际控制人", "share_pct": 35.2, "related_entities": ["卓郎科技", "懋达实业"]},
            {"name": "李某", "role": "持股5%以上股东", "share_pct": 8.5, "related_entities": ["华信投资"]},
            {"name": "张某", "role": "董事", "share_pct": 3.1, "related_entities": ["张某配偶赵某"]},
        ],
        # 关联交易明细（含定价与市场价对比）
        "transactions": [
            {"id": "T001", "counterparty": "卓郎科技", "type": "采购", "amount": 5800000, "pricing": "协议价", "market_price": 5200000, "deviation": 11.5},
            {"id": "T002", "counterparty": "实控人王某", "type": "担保费", "amount": 320000, "pricing": "协议价", "market_price": 150000, "deviation": 113.3},
            {"id": "T003", "counterparty": "卓郎科技", "type": "采购", "amount": 2300000, "pricing": "协议价", "market_price": 2100000, "deviation": 9.5},
            {"id": "T004", "counterparty": "懋达实业", "type": "技术服务", "amount": 850000, "pricing": "协议价", "market_price": 400000, "deviation": 112.5},
            {"id": "T005", "counterparty": "华信投资", "type": "设备采购", "amount": 1200000, "pricing": "协议价", "market_price": 1150000, "deviation": 4.3},
            {"id": "T006", "counterparty": "卓郎科技", "type": "仓储租赁", "amount": 450000, "pricing": "协议价", "market_price": 280000, "deviation": 60.7},
            {"id": "T007", "counterparty": "华信投资", "type": "资金占用费", "amount": 680000, "pricing": "协议价", "market_price": 350000, "deviation": 94.3},
            {"id": "T008", "counterparty": "懋达实业", "type": "采购", "amount": 3200000, "pricing": "协议价", "market_price": 3000000, "deviation": 6.7},
            {"id": "T009", "counterparty": "实控人王某", "type": "咨询费", "amount": 150000, "pricing": "协议价", "market_price": 80000, "deviation": 87.5},
            {"id": "T010", "counterparty": "卓郎科技", "type": "商标许可", "amount": 950000, "pricing": "协议价", "market_price": 500000, "deviation": 90.0},
        ],
        # 已披露的关联交易（用于 fa_12 披露完整性检查）
        "disclosures": [
            {"counterparty": "卓郎科技", "disclosed_amount": 5800000, "disclosure_item": "原材料采购"},
            {"counterparty": "卓郎科技", "disclosed_amount": 2300000, "disclosure_item": "原材料采购第二批"},
            {"counterparty": "华信投资", "disclosed_amount": 1200000, "disclosure_item": "设备采购"},
        ],
    },
}


# ======================================================================
# 案例2：反洗钱可疑交易审计
# 参考兴业银行AML案例、各类洗钱可疑模式
# ======================================================================

CASE_AML = {
    "title": "反洗钱可疑交易审计",
    "requirement": "对银行客户交易进行反洗钱监控，发现可疑交易网络并生成可疑交易报告",
    "expected_modules": ["co_04", "co_05", "co_06"],
    "input_data": {
        # 交易数据：包含资金闭环、拆分交易、快进快出等可疑模式
        "transactions": [
            # 资金闭环：A→B→C→A
            {"tx_id": "TX001", "from_account": "A001", "to_account": "B002", "amount": 480000, "date": "2025-06-01", "purpose": "货款"},
            {"tx_id": "TX002", "from_account": "B002", "to_account": "C003", "amount": 475000, "date": "2025-06-02", "purpose": "咨询费"},
            {"tx_id": "TX003", "from_account": "C003", "to_account": "A001", "amount": 470000, "date": "2025-06-03", "purpose": "退货"},
            # 拆分交易：单笔大额拆分为多笔小额（规避5万报告线）
            {"tx_id": "TX004", "from_account": "D004", "to_account": "E005", "amount": 49000, "date": "2025-06-05", "purpose": "借款"},
            {"tx_id": "TX005", "from_account": "D004", "to_account": "E005", "amount": 49000, "date": "2025-06-05", "purpose": "借款"},
            {"tx_id": "TX006", "from_account": "D004", "to_account": "E005", "amount": 49000, "date": "2025-06-05", "purpose": "借款"},
            {"tx_id": "TX007", "from_account": "D004", "to_account": "E005", "amount": 49000, "date": "2025-06-06", "purpose": "借款"},
            {"tx_id": "TX008", "from_account": "D004", "to_account": "E005", "amount": 49000, "date": "2025-06-06", "purpose": "借款"},
            # 快进快出：资金到账后立即转出
            {"tx_id": "TX009", "from_account": "F006", "to_account": "G007", "amount": 500000, "date": "2025-06-10T09:30:00", "purpose": "投资款"},
            {"tx_id": "TX010", "from_account": "G007", "to_account": "H008", "amount": 498000, "date": "2025-06-10T09:45:00", "purpose": "货款"},
            # 多层跳转：A→B→C→D→E
            {"tx_id": "TX011", "from_account": "I009", "to_account": "J010", "amount": 600000, "date": "2025-06-12", "purpose": "服务费"},
            {"tx_id": "TX012", "from_account": "J010", "to_account": "K011", "amount": 595000, "date": "2025-06-13", "purpose": "材料款"},
            {"tx_id": "TX013", "from_account": "K011", "to_account": "L012", "amount": 590000, "date": "2025-06-14", "purpose": "佣金"},
            {"tx_id": "TX014", "from_account": "L012", "to_account": "M013", "amount": 585000, "date": "2025-06-15", "purpose": "咨询费"},
            # 对公转个人（大额）
            {"tx_id": "TX015", "from_account": "N014", "to_account": "O015", "amount": 850000, "date": "2025-06-18", "purpose": "个人借款"},
            {"tx_id": "TX016", "from_account": "N014", "to_account": "O015", "amount": 720000, "date": "2025-06-19", "purpose": "个人借款"},
            # 资金闭环2：D→E→F→D
            {"tx_id": "TX017", "from_account": "P016", "to_account": "Q017", "amount": 300000, "date": "2025-06-20", "purpose": "预付款"},
            {"tx_id": "TX018", "from_account": "Q017", "to_account": "R018", "amount": 295000, "date": "2025-06-21", "purpose": "退款"},
            {"tx_id": "TX019", "from_account": "R018", "to_account": "P016", "amount": 290000, "date": "2025-06-22", "purpose": "还款"},
            # 大额现金存取
            {"tx_id": "TX020", "from_account": "S019", "to_account": "T020", "amount": 950000, "date": "2025-06-25", "purpose": "现金存入"},
        ],
        # 客户信息
        "customers": [
            {"account": "A001", "name": "甲公司", "risk_level": "中", "kyc": "正常"},
            {"account": "B002", "name": "乙个体户", "risk_level": "高", "kyc": "信息不全"},
            {"account": "C003", "name": "丙商贸", "risk_level": "中", "kyc": "正常"},
            {"account": "D004", "name": "丁投资", "risk_level": "高", "kyc": "存疑"},
            {"account": "E005", "name": "戊贸易", "risk_level": "高", "kyc": "信息不全"},
            {"account": "F006", "name": "己科技", "risk_level": "低", "kyc": "正常"},
            {"account": "G007", "name": "庚咨询", "risk_level": "中", "kyc": "正常"},
            {"account": "H008", "name": "辛实业", "risk_level": "低", "kyc": "正常"},
            {"account": "N014", "name": "壬集团", "risk_level": "中", "kyc": "正常"},
            {"account": "O015", "name": "癸个人", "risk_level": "高", "kyc": "信息不全"},
        ],
    },
}


# ======================================================================
# 案例3：IPO财务规范性审计
# 参考监管问询案例：关联方关系与历史沿革合规性
# ======================================================================

CASE_IPO = {
    "title": "IPO财务规范性审计",
    "requirement": "IPO前财务规范性诊断，检查关联方关系和历史沿革合规性",
    "expected_modules": ["fa_03", "fa_10", "co_01", "ip_01"],
    "input_data": {
        # 财务数据（申报期）
        "records": [
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1122", "period": "2023", "amount": 15800000, "counterparty": "前五大客户A", "description": "应收账款"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1122", "period": "2023", "amount": 12300000, "counterparty": "前五大客户B", "description": "应收账款"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1122", "period": "2023", "amount": 9800000, "counterparty": "关联方甲", "description": "应收账款-关联方"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "2202", "period": "2023", "amount": 8500000, "counterparty": "前五大供应商A", "description": "应付账款"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "2202", "period": "2023", "amount": 6200000, "counterparty": "关联方乙", "description": "应付账款-关联方"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "6001", "period": "2023", "amount": 45000000, "counterparty": "", "description": "营业收入"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "6401", "period": "2023", "amount": 32000000, "counterparty": "", "description": "营业成本"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "6601", "period": "2023", "amount": 2800000, "counterparty": "关联方甲", "description": "销售费用-关联方服务"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "6601", "period": "2023", "amount": 1500000, "counterparty": "关联方乙", "description": "管理费用-关联方租赁"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1122", "period": "2022", "amount": 12800000, "counterparty": "前五大客户A", "description": "应收账款"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1122", "period": "2022", "amount": 7500000, "counterparty": "关联方甲", "description": "应收账款-关联方"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "6001", "period": "2022", "amount": 38000000, "counterparty": "", "description": "营业收入"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "6401", "period": "2022", "amount": 27000000, "counterparty": "", "description": "营业成本"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1221", "period": "2023", "amount": 5200000, "counterparty": "关联方甲", "description": "其他应收款-关联方资金往来"}},
            {"source": "ERP", "source_type": "api", "raw_data": {"company_code": "IPO001", "account_code": "1221", "period": "2022", "amount": 3800000, "counterparty": "关联方甲", "description": "其他应收款-关联方资金往来"}},
        ],
        # 股东及关联方
        "shareholders": [
            {"name": "张某", "role": "控股股东", "share_pct": 45.8, "related_entities": ["关联方甲", "关联方乙"]},
            {"name": "李某", "role": "实际控制人", "share_pct": 45.8, "related_entities": ["关联方甲", "关联方乙"]},
            {"name": "机构投资者A", "role": "财务投资者", "share_pct": 12.3, "related_entities": []},
            {"name": "机构投资者B", "role": "财务投资者", "share_pct": 8.5, "related_entities": []},
        ],
        # 相关法规
        "regulations": [
            {"id": "REG001", "title": "首次公开发行股票注册管理办法", "jurisdiction": "CN", "effective_date": "2023-02-17", "impact_level": "高", "change_summary": "全面注册制下IPO条件与审核流程调整"},
            {"id": "REG002", "title": "公开发行证券的公司信息披露内容与格式准则第57号", "jurisdiction": "CN", "effective_date": "2023-02-17", "impact_level": "高", "change_summary": "招股说明书关联交易披露要求更新"},
            {"id": "REG003", "title": "企业会计准则第36号——关联方披露", "jurisdiction": "CN", "effective_date": "2006-12-31", "impact_level": "中", "change_summary": "关联方关系认定标准与披露规范"},
            {"id": "REG004", "title": "上市公司关联交易管理办法", "jurisdiction": "CN", "effective_date": "2022-01-01", "impact_level": "高", "change_summary": "关联交易审议与披露程序要求"},
        ],
    },
}


# 案例注册表
ALL_CASES: dict[str, dict] = {
    "related_party": CASE_RELATED_PARTY,
    "aml": CASE_AML,
    "ipo": CASE_IPO,
}


def get_case(key: str) -> dict | None:
    """按 key 获取案例数据。"""
    return ALL_CASES.get(key)


def list_cases() -> list[tuple[str, str]]:
    """返回 (key, title) 列表。"""
    return [(k, v["title"]) for k, v in ALL_CASES.items()]
