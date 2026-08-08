"""多模态模拟数据生成器 —— 为78个审计模块生成≥1GB真实结构数据。

数据模态覆盖：
  - tabular: 结构化表格(JSONL) - ERP明细/台账/交易流水
  - text: 文本语料(TXT) - 财报/舆情/合同/公告
  - image_ref: 图片引用(JSONL) - 票据/扫描件/卫星图(uri+hash+mime)
  - video_ref: 视频引用(JSONL) - 会议录像/监控
  - timeseries: 时序数据(JSONL) - 行情/流水/传感器
  - graph: 图结构(JSON) - 知识图谱节点/边

输出：demo/synthetic_data/<slug>/ 下每模块独立目录
"""
from __future__ import annotations
import json, random, hashlib, string, time, os
from datetime import datetime, timedelta
from pathlib import Path

OUT_ROOT = Path(__file__).parent / "synthetic_data"

# ====================== 共享数据池 ======================
COMPANIES = [
    ("600001","卓郎智能机械股份有限公司","91110000MA0ABC12X1"),
    ("600002","华信投资管理集团","91310000MA1DEF34X5"),
    ("600003","懋达实业发展有限公司","91440300MA2GHI56X7"),
    ("600004","金徽矿业科技股份有限公司","91620000MA3JKL78X9"),
    ("600005","中天科技控股集团","91320000MA4MNO90X1"),
    ("600006","瑞达期货股份有限公司","91370000MA5PQR12X3"),
    ("600007","兴业银行股份有限公司","91350000MA6STU34X5"),
    ("600008","北方华创科技集团","91110000MA7VWX56X7"),
    ("600009","海尔智家股份有限公司","91370000MA8YZA78X9"),
    ("600010","宁德时代新能源科技","91350000MA9BCD01X2"),
]
PERSONS = ["王某","李某","张某","刘某","陈某","杨某","赵某","黄某","周某","吴某",
           "郑某","孙某","马某","朱某","胡某","郭某","何某","高某","林某","罗某"]
ACCOUNTS = [
    ("1001","库存现金"),("1002","银行存款"),("1122","应收账款"),("1123","预付账款"),
    ("1401","原材料"),("1405","库存商品"),("2202","应付账款"),("2203","预收账款"),
    ("6001","主营业务收入"),("6601","销售费用"),("6602","管理费用"),("6603","财务费用"),
    ("6701","资产减值损失"),("6711","营业外支出"),("6111","投资收益"),("1601","固定资产"),
]
COUNTERPARTIES = ["卓郎科技","实控人王某","懋达实业","华信投资","中天科技","金徽矿业",
                  "瑞达期货","兴业银行","北方华创","海尔智家","宁德时代","供应商A",
                  "供应商B","客户C","客户D","关联方E","分包商F","代理商G"]
SOURCES = ["ERP","银行","合同","税务","工商","舆情","年报","公告","卫星","监控","会议","邮件"]
CURRENCIES = ["CNY","USD","EUR","HKD","JPY"]
EVENT_TYPES = ["采购","销售","付款","收款","担保","投资","分红","借款","还款","费用","转账","结算"]
SENTIMENT_WORDS = ["涉嫌舞弊","关联交易异常","信披违规","内控缺陷","业绩变脸","证监会问询",
                   "立案调查","财务造假","资金占用","违规担保","利润操纵","审计非标",
                   "积极增长","合规经营","治理完善","风险可控","稳健发展","透明披露"]

# 文本语料模板
TEXT_TEMPLATES = [
    "{company}于{date}发布{period}年度报告，报告期内实现营业收入{revenue}亿元，同比增长{growth}%。"
    "公司主营业务包括{business}。报告期内，公司与{counterparty}发生关联交易{amount}万元，"
    "定价方式为{pricing}。审计机构指出{risk_signal}，建议关注{focus}。",
    "{company}公告称，收到证监会{inquiry_type}，要求就{topic}进行说明。"
    "事项涉及{counterparty}及相关交易，金额约{amount}万元。公司表示{response}。"
    "市场分析认为{analysis}，投资者需关注{focus}。",
    "根据工商信息，{company}股东{person}持股{pct}%，其关联实体包括{counterparty}。"
    "股权结构显示{structure}，实际控制人为{person2}。"
    "历史变更记录：{date}发生{change_type}，{change_detail}。",
    "舆情监测显示，{company}近期出现{sentiment}相关报道。{counterparty}被指{allegation}。"
    "社交媒体讨论热度{heat}，负面情绪占比{neg_pct}%。建议审计关注{focus}。",
    "{company}{period}财务报表分析：应收账款{ar}亿元，存货{inv}亿元，商誉{gw}亿元。"
    "经营性现金流{ocf}亿元，净利润{ni}亿元。资产负债率{debt_ratio}%，毛利率{gm}%。"
    "审计风险信号：{risk_signal}。",
]

# 法规模板
REG_TITLES = ["企业会计准则第{}号——{}", "公司法修订草案({}版)", "证券法实施条例第{}条",
              "反洗钱法({}修订)", "上市公司信息披露管理办法({}版)", "企业所得税法实施条例第{}条"]
REG_TOPICS = ["收入确认","关联交易披露","金融工具","租赁","收入","政府补助","持有待售",
              "企业合并","财务报表列报","现金流量表","每股收益","分部报告"]

# ====================== 工具函数 ======================
def rand_amount(): return round(random.uniform(10000, 50000000), 2)
def rand_date(start="2023-01-01", end="2026-06-30"):
    s = datetime.strptime(start,"%Y-%m-%d"); e = datetime.strptime(end,"%Y-%m-%d")
    return (s + timedelta(days=random.randint(0,(e-s).days))).strftime("%Y-%m-%d")
def rand_period():
    y = random.choice([2023,2024,2025,2026]); m = random.randint(1,12)
    return f"{y}-{m:02d}"
def rand_hash(): return hashlib.md5(str(random.random()).encode()).hexdigest()
def rand_uscc():
    base = "".join(random.choices("0123456789ABCDEFGHJKLMNPQRTUWXY",k=17))
    return base + random.choice("0123456789ABCDEFGHJKLMNPQRTUWXY")
def rand_event_time(period=None):
    if period: return f"{period}-15T{random.randint(8,18):02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}"
    return rand_date()+"T10:00:00"
def rand_media_uri(modality):
    ext = {"image":"jpg","video":"mp4","audio":"wav"}[modality]
    return f"s3://audit-data/{modality}/{rand_hash()[:8]}.{ext}"

# 批量写入 JSONL
def write_jsonl(path, records):
    with open(path,"w",encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r,ensure_ascii=False)+"\n")

def write_text(path, lines):
    with open(path,"w",encoding="utf-8") as f:
        f.write("\n".join(lines))

def write_json(path, obj):
    with open(path,"w",encoding="utf-8") as f:
        json.dump(obj,f,ensure_ascii=False,indent=2)

def write_media_refs(path, count, modalities=("image","video")):
    refs = []
    for _ in range(count):
        mod = random.choice(modalities)
        refs.append({
            "uri": rand_media_uri(mod), "hash": rand_hash(),
            "mime": {"image":"image/jpeg","video":"video/mp4","audio":"audio/wav"}[mod],
            "modality": mod, "size_bytes": random.randint(50000,50000000),
            "captured_at": rand_event_time(),
            "description": random.choice(["票据扫描件","合同扫描页","会议录像片段","监控截图","银行回单","发票照片"]),
        })
    write_jsonl(path, refs)

# ====================== 通用记录生成 ======================
def gen_tabular_records(count, slug, family, extra_fields=None):
    """生成结构化表格记录。"""
    recs = []
    for i in range(count):
        comp = random.choice(COMPANIES)
        acct = random.choice(ACCOUNTS)
        cp = random.choice(COUNTERPARTIES)
        rec = {
            "id": f"{slug.upper()}-{i+1:06d}",
            "batch_id": f"BATCH-{slug.upper()}",
            "company_code": comp[0], "company_name": comp[1], "uscc": comp[2],
            "source": random.choice(SOURCES), "source_type": random.choice(["api","csv","pdf","ocr","stream"]),
            "account_code": acct[0], "account_name": acct[1],
            "period": rand_period(), "event_time": rand_event_time(),
            "amount": rand_amount(), "currency": random.choice(CURRENCIES),
            "voucher_no": f"V{random.randint(100000,999999)}",
            "counterparty": cp, "counterparty_uscc": rand_uscc(),
            "description": random.choice(EVENT_TYPES)+random.choice(["-常规","-异常","-关联","-大额"]),
            "quality_flags": random.sample(["null_field","type_converted","dedup","cross_source"],k=random.randint(0,2)),
        }
        if extra_fields:
            for k,vfn in extra_fields.items():
                rec[k] = vfn()
        recs.append(rec)
    return recs

def gen_text_corpus(count, slug):
    """生成文本语料。"""
    docs = []
    for i in range(count):
        tpl = random.choice(TEXT_TEMPLATES)
        text = tpl.format(
            company=random.choice(COMPANIES)[1], date=rand_date(), period=rand_period(),
            revenue=round(random.uniform(1,100),1), growth=random.randint(-30,50),
            business=random.choice(["智能制造","矿业开发","金融投资","新能源","房地产开发","贸易"]),
            counterparty=random.choice(COUNTERPARTIES), amount=random.randint(100,50000),
            pricing=random.choice(["协议价","市场价","成本加成","拍卖价"]),
            risk_signal=random.choice(SENTIMENT_WORDS), focus=random.choice(["关联交易公允性","资金占用","信息披露合规","内控有效性"]),
            inquiry_type=random.choice(["问询函","关注函","立案通知","行政处罚决定书"]),
            topic=random.choice(REG_TOPICS), response=random.choice(["将积极配合调查","不存在违规情形","已进行整改","无法发表意见"]),
            analysis=random.choice(["短期影响有限","需持续观察","存在退市风险","利好基本面"]),
            person=random.choice(PERSONS), person2=random.choice(PERSONS),
            pct=round(random.uniform(5,40),1),
            structure=random.choice(["金字塔持股","交叉持股","一致行动人协议","股权代持"]),
            change_type=random.choice(["股权转让","增资扩股","减资","股东变更","法定代表人变更"]),
            change_detail=random.choice(["持股比例由20%变更为35%","新增股东卓郎科技","实控人变更为王某"]),
            sentiment=random.choice(SENTIMENT_WORDS), allegation=random.choice(["利益输送","资金占用","虚假陈述","违规担保"]),
            heat=random.choice(["高","中","低"]), neg_pct=random.randint(20,80),
            ar=round(random.uniform(0.5,20),1), inv=round(random.uniform(0.5,15),1), gw=round(random.uniform(0,10),1),
            ocf=round(random.uniform(-5,10),1), ni=round(random.uniform(-3,8),1),
            debt_ratio=random.randint(30,80), gm=random.randint(10,50),
        )
        docs.append(f"=== DOC-{slug.upper()}-{i+1:05d} | {rand_date()} | {random.choice(SOURCES)} ===\n{text}\n")
    return docs

def gen_timeseries(count, slug):
    """生成时序数据。"""
    recs = []
    base_ts = datetime(2025,1,1)
    for i in range(count):
        ts = base_ts + timedelta(hours=i)
        recs.append({
            "id": f"TS-{slug.upper()}-{i+1:06d}",
            "event_time": ts.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "company_code": random.choice(COMPANIES)[0],
            "metric": random.choice(["股价","成交量","资金净流入","交易金额","风险评分","预警等级"]),
            "value": round(random.uniform(-100,1000),4),
            "source_system": random.choice(SOURCES),
        })
    return recs

def gen_graph(slug, node_count=200, edge_count=500):
    """生成图结构数据。"""
    nodes = [{"id":f"N{i+1:04d}","label":random.choice(COMPANIES)[1] if i<10 else random.choice(COUNTERPARTIES),
              "type":random.choice(["company","person","account","transaction"]),"uscc":rand_uscc()} for i in range(node_count)]
    edges = [{"source":random.choice(nodes)["id"],"target":random.choice(nodes)["id"],
              "relation":random.choice(["持股","交易","担保","关联","控制","投资"]),"weight":round(random.random(),3)}
             for _ in range(edge_count)]
    return {"nodes":nodes,"edges":edges}

# ====================== 家族特化生成器 ======================
# 每个家族返回 dict: {filename: (writer_fn, args)}

def gen_fa(slug, size_mb):
    """财务审计家族。"""
    n = int(size_mb*1000/0.5)  # 每条约0.5KB
    return {
        "records.jsonl": (write_jsonl, gen_tabular_records(n, slug, "FA")),
        "text_corpus.txt": (write_text, gen_text_corpus(n//10, slug)),
        "media_refs.jsonl": (write_media_refs, ("media_refs.jsonl", n//50, ("image","video"))),
        "transactions.jsonl": (write_jsonl, [{"tx_id":f"TX-{i+1:06d}","counterparty":random.choice(COUNTERPARTIES),
            "amount":rand_amount(),"market_price":rand_amount(),"deviation":round(random.uniform(-20,120),1),
            "pricing":random.choice(["协议价","市场价"]),"period":rand_period()} for i in range(n//5)]),
        "shareholders.jsonl": (write_jsonl, [{"name":random.choice(PERSONS),"role":random.choice(["实际控制人","董事","监事","高管"]),
            "share_pct":round(random.uniform(1,40),1),"uscc":rand_uscc(),
            "related_entities":random.sample(COUNTERPARTIES,k=random.randint(1,3))} for _ in range(200)]),
    }

def gen_co(slug, size_mb):
    """合规审计家族。"""
    n = int(size_mb*1000/0.5)
    regs = [{"reg_id":f"REG-{i+1:05d}","title":random.choice(REG_TITLES).format(random.randint(1,42),random.choice(REG_TOPICS)),
             "issuer":random.choice(["证监会","财政部","央行","税务总局","银保监会"]),"publish_date":rand_date(),
             "effective_date":rand_date(),"risk_level":random.choice(["高","中","低"]),
             "summary":f"本法规涉及{random.choice(REG_TOPICS)}相关要求，要求企业{random.choice(['规范披露','加强内控','合规经营'])}。"} for i in range(n//3)]
    return {
        "regulations.jsonl": (write_jsonl, regs),
        "transactions.jsonl": (write_jsonl, [{"tx_id":f"AML-{i+1:06d}","customer":random.choice(PERSONS),
            "amount":rand_amount(),"event_time":rand_event_time(),"risk_score":round(random.random(),3),
            "alert_type":random.choice(["大额现金","拆分交易","快进快出","跨境","关联"])} for i in range(n)]),
        "text_corpus.txt": (write_text, gen_text_corpus(n//8, slug)),
        "media_refs.jsonl": (write_media_refs, ("media_refs.jsonl", n//80, ("image",))),
        "graph.json": (write_json, gen_graph(slug, 300, 800)),
    }

def gen_ip(slug, size_mb):
    """IPO审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "history_events.jsonl": (write_jsonl, [{"event_id":f"HIS-{i+1:05d}","company_code":random.choice(COMPANIES)[0],
            "event_date":rand_date("2015-01-01","2026-06-30"),"event_type":random.choice(["设立","增资","股权转让","上市","并购","重组"]),
            "description":f"公司发生{random.choice(['股权变更','资产重组','业务调整'])}","amount":rand_amount()} for i in range(n//3)]),
        "cases.jsonl": (write_jsonl, [{"case_id":f"CASE-{i+1:04d}","company":random.choice(COMPANIES)[1],
            "issue":random.choice(REG_TOPICS),"penalty":random.choice(["警告","罚款","责令改正","市场禁入"]),
            "amount":rand_amount(),"date":rand_date()} for i in range(n//4)]),
        "records.jsonl": (write_jsonl, gen_tabular_records(n, slug, "IP")),
        "text_corpus.txt": (write_text, gen_text_corpus(n//8, slug)),
    }

def gen_cm(slug, size_mb):
    """持续审计家族。"""
    n = int(size_mb*1000/0.4)
    return {
        "events.jsonl": (write_jsonl, gen_timeseries(n, slug)),
        "alerts.jsonl": (write_jsonl, [{"alert_id":f"ALT-{i+1:06d}","level":random.choice(["P0","P1","P2","P3"]),
            "module":slug,"event_time":rand_event_time(),"company_code":random.choice(COMPANIES)[0],
            "description":random.choice(SENTIMENT_WORDS),"status":random.choice(["待处理","处理中","已闭环"])} for i in range(n//5)]),
        "records.jsonl": (write_jsonl, gen_tabular_records(n//3, slug, "CM")),
    }

def gen_fo(slug, size_mb):
    """舞弊审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "transactions.jsonl": (write_jsonl, [{"tx_id":f"FRD-{i+1:06d}","fraud_type":random.choice(["关联交易","资金占用","虚增收入","虚增资产","隐瞒负债"]),
            "amount":rand_amount(),"event_time":rand_event_time(),"risk_score":round(random.random(),3),
            "signals":random.sample(SENTIMENT_WORDS,k=random.randint(1,3))} for i in range(n)]),
        "documents.txt": (write_text, gen_text_corpus(n//6, slug)),
        "media_refs.jsonl": (write_media_refs, ("media_refs.jsonl", n//40, ("image","video"))),
        "evidence.jsonl": (write_jsonl, [{"evidence_id":f"EV-{i+1:05d}","type":random.choice(["邮件","合同","转账记录","录音","视频"]),
            "hash":rand_hash(),"collected_at":rand_event_time(),"chain_of_custody":random.choice(PERSONS)} for i in range(n//4)]),
        "graph.json": (write_json, gen_graph(slug, 400, 1000)),
    }

def gen_it(slug, size_mb):
    """IT审计家族。"""
    n = int(size_mb*1000/0.4)
    return {
        "configs.jsonl": (write_jsonl, [{"config_id":f"CFG-{i+1:05d}","system":random.choice(["ERP","OA","财务系统","网银"]),
            "item":random.choice(["权限配置","密码策略","日志保留","备份策略"]),"compliant":random.choice([True,False]),
            "risk":random.choice(["高","中","低"])} for i in range(n//2)]),
        "logs.jsonl": (write_jsonl, gen_timeseries(n, slug)),
        "code_issues.jsonl": (write_jsonl, [{"issue_id":f"COD-{i+1:05d}","file":f"src/module_{random.randint(1,50)}.py",
            "line":random.randint(1,500),"severity":random.choice(["critical","high","medium","low"]),
            "type":random.choice(["SQL注入","硬编码密码","权限绕过","日志泄露"])} for i in range(n//3)]),
    }

def gen_ta(slug, size_mb):
    """税务审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "invoices.jsonl": (write_jsonl, [{"invoice_no":f"INV-{i+1:07d}","type":random.choice(["专票","普票","电子"]),
            "buyer":random.choice(COMPANIES)[1],"seller":random.choice(COUNTERPARTIES),
            "amount":rand_amount(),"tax":round(rand_amount()*0.13,2),"date":rand_date(),
            "items":random.randint(1,10)} for i in range(n)]),
        "transfer_pricing.jsonl": (write_jsonl, [{"tp_id":f"TP-{i+1:05d}","counterparty":random.choice(COUNTERPARTIES),
            "amount":rand_amount(),"market_range":[rand_amount(),rand_amount()],"deviation":round(random.uniform(-30,50),1)} for i in range(n//4)]),
        "media_refs.jsonl": (write_media_refs, ("media_refs.jsonl", n//60, ("image",))),
    }

def gen_sc(slug, size_mb):
    """供应链审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "suppliers.jsonl": (write_jsonl, [{"supplier_id":f"SUP-{i+1:05d}","name":random.choice(COUNTERPARTIES),
            "uscc":rand_uscc(),"risk_score":round(random.random(),3),"risk_level":random.choice(["高","中","低"]),
            "business":random.choice(["原材料","设备","服务","物流"]),"amount":rand_amount()} for i in range(n//2)]),
        "procurement.jsonl": (write_jsonl, [{"po_id":f"PO-{i+1:06d}","supplier":random.choice(COUNTERPARTIES),
            "item":random.choice(["钢材","芯片","软件","服务"]),"quantity":random.randint(1,1000),
            "unit_price":round(random.uniform(100,50000),2),"amount":rand_amount(),"date":rand_date()} for i in range(n)]),
        "media_refs.jsonl": (write_media_refs, ("media_refs.jsonl", n//80, ("image","video"))),
    }

def gen_es(slug, size_mb):
    """ESG审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "esg_data.jsonl": (write_jsonl, [{"company_code":random.choice(COMPANIES)[0],"period":rand_period(),
            "e_score":round(random.uniform(0,100),1),"s_score":round(random.uniform(0,100),1),
            "g_score":round(random.uniform(0,100),1),"carbon_emission":round(random.uniform(1000,50000),1),
            "water_usage":round(random.uniform(100,10000),1),"waste":round(random.uniform(10,1000),1)} for i in range(n//3)]),
        "satellite_refs.jsonl": (write_media_refs, ("satellite_refs.jsonl", n//50, ("image",))),
        "text_reports.txt": (write_text, gen_text_corpus(n//6, slug)),
        "carbon.jsonl": (write_jsonl, gen_timeseries(n, slug)),
    }

def gen_fi(slug, size_mb):
    """金融审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "loans.jsonl": (write_jsonl, [{"loan_id":f"LN-{i+1:06d}","borrower":random.choice(COMPANIES)[1],
            "amount":rand_amount(),"rate":round(random.uniform(3,8),2),"term":random.randint(1,60),
            "status":random.choice(["正常","关注","次级","可疑","损失"]),"event_time":rand_event_time()} for i in range(n)]),
        "guarantees.jsonl": (write_jsonl, [{"guar_id":f"GR-{i+1:05d}","guarantor":random.choice(COMPANIES)[1],
            "beneficiary":random.choice(COUNTERPARTIES),"amount":rand_amount(),"type":random.choice(["一般保证","连带责任"])} for i in range(n//3)]),
        "regulatory_reports.jsonl": (write_jsonl, [{"report_id":f"RPT-{i+1:05d}","type":random.choice(["1104","EAST","人行统计"]),
            "period":rand_period(),"items":random.randint(50,500),"discrepancies":random.randint(0,20)} for i in range(n//4)]),
    }

def gen_ia(slug, size_mb):
    """内部审计家族。"""
    n = int(size_mb*1000/0.4)
    return {
        "risks.jsonl": (write_jsonl, [{"risk_id":f"RSK-{i+1:05d}","category":random.choice(["财务","运营","合规","战略","IT"]),
            "description":random.choice(SENTIMENT_WORDS),"likelihood":random.randint(1,5),"impact":random.randint(1,5),
            "owner":random.choice(PERSONS),"status":random.choice(["开放","缓解","关闭"])} for i in range(n//2)]),
        "remediation.jsonl": (write_jsonl, [{"rem_id":f"REM-{i+1:05d}","finding":random.choice(SENTIMENT_WORDS),
            "owner":random.choice(PERSONS),"due_date":rand_date(),"status":random.choice(["未开始","进行中","已完成","逾期"]),
            "progress":random.randint(0,100)} for i in range(n//3)]),
        "audit_plans.jsonl": (write_jsonl, [{"plan_id":f"PLN-{i+1:04d}","area":random.choice(REG_TOPICS),
            "period":rand_period(),"budget":rand_amount(),"auditor":random.choice(PERSONS)} for i in range(n//5)]),
    }

def gen_cb(slug, size_mb):
    """跨境审计家族。"""
    n = int(size_mb*1000/0.5)
    return {
        "cross_border.jsonl": (write_jsonl, [{"tx_id":f"CB-{i+1:06d}","jurisdiction":random.choice(["中国","美国","欧盟","新加坡","开曼"]),
            "counterparty":random.choice(COUNTERPARTIES),"amount":rand_amount(),"currency":random.choice(CURRENCIES),
            "transfer_type":random.choice(["股息","服务费","特许权","贷款"]),"event_time":rand_event_time()} for i in range(n)]),
        "regulations.jsonl": (write_jsonl, [{"reg_id":f"CBR-{i+1:05d}","jurisdiction":random.choice(["美国","欧盟","新加坡","香港"]),
            "title":random.choice(REG_TITLES).format(random.randint(1,30),random.choice(REG_TOPICS)),
            "impact":random.choice(["高","中","低"])} for i in range(n//4)]),
        "text_corpus.txt": (write_text, gen_text_corpus(n//8, slug)),
    }

# ====================== 模块→家族映射 ======================
FAMILY_GEN = {
    "fa": gen_fa, "co": gen_co, "ip": gen_ip, "cm": gen_cm, "fo": gen_fo,
    "it": gen_it, "ta": gen_ta, "sc": gen_sc, "es": gen_es, "fi": gen_fi,
    "ia": gen_ia, "cb": gen_cb,
}

# 每模块目标大小(MB)，总和>1024（实际产出受记录密度影响，配SIZE_BOOST确保达标）
SIZE_BOOST = 1.55  # 数据量倍率：实测1.0x产出708MB，1.55x≈1098MB > 1GB
MODULE_SIZES = {
    "fa_02":18,"fa_03":18,"fa_04":12,"fa_05":10,"fa_06":12,"fa_07":15,"fa_08":12,"fa_09":12,"fa_10":15,"fa_11":14,"fa_12":12,
    "co_01":16,"co_02":14,"co_03":12,"co_04":18,"co_05":15,"co_06":14,"co_07":12,"co_08":12,"co_09":12,
    "ip_01":16,"ip_02":12,"ip_03":14,"ip_04":14,"ip_05":14,"ip_06":12,
    "cm_01":16,"cm_02":14,"cm_03":10,"cm_04":12,"cm_05":12,
    "fo_01":18,"fo_02":15,"fo_03":16,"fo_04":14,"fo_05":12,"fo_06":14,
    "it_01":14,"it_02":12,"it_03":14,"it_04":14,"it_05":12,
    "ta_01":16,"ta_02":15,"ta_03":12,"ta_04":14,"ta_05":12,"ta_06":14,
    "sc_01":15,"sc_02":14,"sc_03":14,"sc_04":14,"sc_05":12,
    "es_01":16,"es_02":14,"es_03":14,"es_04":14,"es_05":14,"es_06":12,
    "fi_01":16,"fi_02":15,"fi_03":14,"fi_04":14,"fi_05":12,
    "ia_01":14,"ia_02":14,"ia_03":12,"ia_04":12,"ia_05":12,"ia_06":10,"ia_07":12,"ia_08":12,
    "cb_01":16,"cb_02":14,"cb_03":14,"cb_04":14,"cb_05":12,"cb_06":14,
}

# ====================== 主流程 ======================
def main():
    t0 = time.time()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    manifest = []

    for slug, size_mb in MODULE_SIZES.items():
        size_mb = size_mb * SIZE_BOOST
        family = slug.split("_")[0]
        gen_fn = FAMILY_GEN[family]
        mod_dir = OUT_ROOT / slug
        mod_dir.mkdir(parents=True, exist_ok=True)

        files_spec = gen_fn(slug, size_mb)
        mod_bytes = 0
        mod_files = []

        for filename, spec in files_spec.items():
            fpath = mod_dir / filename
            writer_fn, data = spec
            if writer_fn is write_media_refs:
                # data = (count, modalities) 或 ("filename", count, modalities)
                args = data[1:] if isinstance(data, tuple) and isinstance(data[0], str) else (data if not isinstance(data, tuple) else data)
                if isinstance(args, tuple) and len(args)==2:
                    write_media_refs(fpath, args[0], args[1])
                elif isinstance(args, tuple):
                    write_media_refs(fpath, *args)
                else:
                    write_media_refs(fpath, args)
            elif callable(writer_fn):
                writer_fn(fpath, data)
            mod_bytes += fpath.stat().st_size
            mod_files.append({"file":filename,"bytes":fpath.stat().st_size})

        # 元数据
        meta = {
            "slug": slug, "family": family, "module_name": "",
            "total_bytes": mod_bytes, "total_mb": round(mod_bytes/1048576,2),
            "files": mod_files, "modalities": list(set(f.split(".")[0] for f,_ in files_spec.items())),
            "generated_at": datetime.now().isoformat(),
        }
        write_json(mod_dir/"meta.json", meta)
        manifest.append(meta)
        total_bytes += mod_bytes
        print(f"  {slug}: {mod_bytes/1048576:.2f} MB")

    write_json(OUT_ROOT/"manifest.json", {
        "total_bytes": total_bytes, "total_mb": round(total_bytes/1048576,2),
        "total_gb": round(total_bytes/1073741824,3),
        "module_count": len(MODULE_SIZES),
        "generated_at": datetime.now().isoformat(),
        "modules": manifest,
    })
    elapsed = time.time()-t0
    print(f"\n=== 生成完成 ===")
    print(f"模块数: {len(MODULE_SIZES)}")
    print(f"总数据量: {total_bytes/1073741824:.3f} GB ({total_bytes/1048576:.2f} MB)")
    print(f"耗时: {elapsed:.1f}s")

if __name__ == "__main__":
    main()
