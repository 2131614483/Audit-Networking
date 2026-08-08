#!/usr/bin/env python3
"""端到端验证：模拟审计数据 → 注入真实算法 → 验证全链路。

验证内容：
  1. 导入链：modules.shared → modules.fa_02 / fo_01 / sc_01 全部可导入
  2. 配置链：三级配置加载（default.yaml ← custom.yaml ← 运行时覆盖）
  3. 管道链：Pipeline.run() 端到端执行（engine.execute + custom_rules + thresholds + formatter）
  4. HTTP链：uvicorn 后台线程启动 + urllib 请求 /health /info /execute

数据来源（模拟生成，非真实爬取）：
  - 2000+ 笔交易（Benford 对数分布 + 注入异常：大额/高频/整数金额）
  - 150+ 家供应商（五维风险特征 + 注入高风险样本）
  - 字段映射数据（含名称变体：注册资本/注册资金/注册资本金 → registered_capital）

算法注入（运行时 monkey-patch，不改原文件）：
  - FA-02 字段标准化：raw_name → standard_name 映射 + 同名字段聚合
  - FO-01 舞弊检测：Benford 定律卡方检验 + Z-Score 异常检测 + 风险评分
  - SC-01 供应商评分：五维加权（工商15% + 司法25% + 财务30% + ESG15% + 舆情15%）

零额外依赖：纯 stdlib + 已安装的 fastapi/uvicorn/yaml。
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import threading
import time
import urllib.request
import urllib.error

# 确保仓库根目录在 sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# ============================================================
# Part 1：模拟审计数据生成器
# ============================================================

def generate_transactions(n: int = 2000, seed: int = 42) -> list:
    """生成模拟交易流水。

    大部分交易金额服从 Benford 定律（对数分布），注入 3 类异常：
      - 大额异常：金额远超均值（|Z| > 3）
      - 整数金额：精确到万元的整数（人为操纵信号）
      - 高频交易：同一对手方短时间内密集交易
    """
    rng = random.Random(seed)
    counterparties = [f"CP{i:04d}" for i in range(200)]
    categories = ["采购", "销售", "费用", "薪酬", "税费", "其他"]
    transactions = []

    for i in range(n):
        # Benford 对数分布：10^(uniform(1, 7)) 产生 10-1000万区间金额
        amount = round(10 ** rng.uniform(1.0, 7.0), 2)
        tx = {
            "tx_id": f"TX{i:06d}",
            "date": f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "amount": amount,
            "counterparty": rng.choice(counterparties),
            "category": rng.choice(categories),
            "description": f"交易-{categories[rng.randint(0, 5)]}-{i}",
        }
        transactions.append(tx)

    # 注入异常 1：大额交易（|Z| > 3）
    for i in range(0, n, 50):
        transactions[i]["amount"] = round(rng.uniform(5_000_000, 10_000_000), 2)

    # 注入异常 2：整数万元金额（人为操纵信号）
    for i in range(10, n, 80):
        transactions[i]["amount"] = float(rng.randint(50, 500) * 10000)

    # 注入异常 3：同一对手方高频交易
    hot_cp = "CP0042"
    for i in range(50):
        idx = n - 1 - i
        transactions[idx]["counterparty"] = hot_cp
        transactions[idx]["amount"] = round(rng.uniform(10000, 50000), 2)
        transactions[idx]["date"] = "2025-06-15"

    return transactions


def generate_suppliers(n: int = 150, seed: int = 7) -> list:
    """生成模拟供应商数据（五维风险特征）。

    维度：
      - 工商：注册资本、成立年限
      - 司法：涉诉次数、被执行记录
      - 财务：资产负债率、流动比率
      - ESG：环保处罚、碳排放强度
      - 舆情：负面舆情频次、情感得分
    """
    rng = random.Random(seed)
    suppliers = []
    for i in range(n):
        # 大部分供应商风险正常，注入约 15% 高风险
        is_high_risk = rng.random() < 0.15
        if is_high_risk:
            s = {
                "supplier_id": f"SUP{i:04d}",
                "name": f"高风险供应商{i:03d}号",
                "registered_capital": rng.uniform(10, 100),          # 低注册资本（万）
                "establishment_years": rng.uniform(0.5, 2),           # 短年限
                "litigation_count": rng.randint(5, 20),               # 高涉诉
                "executed_count": rng.randint(2, 8),                  # 多次被执行
                "debt_ratio": rng.uniform(0.75, 0.95),                # 高负债率
                "current_ratio": rng.uniform(0.5, 0.9),               # 低流动比率
                "esg_penalty": rng.randint(2, 6),                     # 多次环保处罚
                "carbon_intensity": rng.uniform(80, 150),             # 高碳排放
                "negative_news": rng.randint(10, 30),                 # 高负面舆情
                "sentiment_score": rng.uniform(-0.8, -0.3),           # 负面情感
            }
        else:
            s = {
                "supplier_id": f"SUP{i:04d}",
                "name": f"供应商{i:03d}号",
                "registered_capital": rng.uniform(500, 5000),
                "establishment_years": rng.uniform(5, 20),
                "litigation_count": rng.randint(0, 2),
                "executed_count": 0,
                "debt_ratio": rng.uniform(0.2, 0.55),
                "current_ratio": rng.uniform(1.5, 3.0),
                "esg_penalty": rng.randint(0, 1),
                "carbon_intensity": rng.uniform(10, 50),
                "negative_news": rng.randint(0, 3),
                "sentiment_score": rng.uniform(0.2, 0.8),
            }
        suppliers.append(s)
    rng.shuffle(suppliers)
    return suppliers


def generate_field_data() -> dict:
    """生成多源字段映射数据（含名称变体）。

    模拟多个业务系统（ERP/银行/采购）的同义字段，用于验证字段标准化。
    """
    return {
        "source_systems": ["ERP_SAP", "Bank_ICBC", "SRM_Procurement"],
        "fields": [
            {"raw_name": "注册资本", "value": 5000, "source": "ERP_SAP"},
            {"raw_name": "注册资金", "value": 3000, "source": "Bank_ICBC"},
            {"raw_name": "注册资本金", "value": 2000, "source": "SRM_Procurement"},
            {"raw_name": "营业收入", "value": 12000, "source": "ERP_SAP"},
            {"raw_name": "营收", "value": 8000, "source": "Bank_ICBC"},
            {"raw_name": "净利润", "value": 3500, "source": "ERP_SAP"},
            {"raw_name": "纯利润", "value": 1500, "source": "SRM_Procurement"},
            {"raw_name": "资产负债率", "value": 0.45, "source": "ERP_SAP"},
            {"raw_name": "负债率", "value": 0.12, "source": "Bank_ICBC"},
            {"raw_name": "流动比率", "value": 2.1, "source": "ERP_SAP"},
            {"raw_name": "current_ratio", "value": 1.8, "source": "SRM_Procurement"},
            {"raw_name": "涉诉次数", "value": 3, "source": "Bank_ICBC"},
            {"raw_name": "诉讼数量", "value": 2, "source": "SRM_Procurement"},
        ],
    }


# ============================================================
# Part 2：算法实现（monkey-patch 注入，不改原文件）
# ============================================================

# ---- FA-02 字段标准化引擎 ----

FA02_FIELD_MAP = {
    "注册资本": "registered_capital", "注册资金": "registered_capital",
    "注册资本金": "registered_capital",
    "营业收入": "revenue", "营收": "revenue",
    "净利润": "net_profit", "纯利润": "net_profit",
    "资产负债率": "debt_ratio", "负债率": "debt_ratio",
    "流动比率": "current_ratio", "current_ratio": "current_ratio",
    "涉诉次数": "litigation_count", "诉讼数量": "litigation_count",
}


def _fa02_load_model(self):
    """加载字段映射表。"""
    self.model = FA02_FIELD_MAP


def _fa02_preprocess(self, input_data):
    """从输入提取字段列表。"""
    if self.model is None:          # API 入口未调 setup()，懒加载
        self._load_model()
    if isinstance(input_data, dict) and "fields" in input_data:
        return input_data["fields"]
    return input_data if isinstance(input_data, list) else []


def _fa02_infer(self, prepared):
    """字段名映射 + 同名字段聚合。"""
    standardized = {}
    for f in prepared:
        raw = f.get("raw_name", "")
        val = f.get("value", 0)
        std = self.model.get(raw, raw)
        if std in standardized:
            standardized[std] += val
        else:
            standardized[std] = val
    return standardized


def _fa02_postprocess(self, result):
    """格式化输出。"""
    return {"standardized": result, "field_count": len(result)}


def patch_fa_02():
    """把 FA-02 的 MLEngine 四个抽象方法替换为真实实现。"""
    from modules.fa_02.engine import MLEngine
    MLEngine._load_model = _fa02_load_model
    MLEngine._preprocess = _fa02_preprocess
    MLEngine._infer = _fa02_infer
    MLEngine._postprocess = _fa02_postprocess
    return MLEngine


# ---- FO-01 舞弊检测引擎（Benford + Z-Score） ----

def _fo01_load_model(self):
    """加载 Benford 定律期望频率。"""
    self.model = {d: math.log10(1 + 1 / d) for d in range(1, 10)}


def _fo01_preprocess(self, input_data):
    """提取交易金额列表。"""
    if self.model is None:          # API 入口未调 setup()，懒加载
        self._load_model()
    if isinstance(input_data, dict) and "transactions" in input_data:
        return input_data["transactions"]
    if isinstance(input_data, list):
        return input_data
    return []


def _fo01_infer(self, prepared):
    """Benford 定律卡方检验 + Z-Score 异常检测。"""
    amounts = [t["amount"] for t in prepared if t.get("amount", 0) > 0]

    # --- Benford 定律首位数字分析 ---
    first_digits = [int(str(a)[0]) for a in amounts if a > 0]
    total = len(first_digits)
    observed = {d: first_digits.count(d) for d in range(1, 10)}

    # 卡方统计量
    chi_square = 0.0
    for d in range(1, 10):
        expected = self.model[d] * total
        chi_square += (observed[d] - expected) ** 2 / max(expected, 0.01)

    # --- Z-Score 异常检测 ---
    mean = sum(amounts) / len(amounts) if amounts else 0
    variance = sum((a - mean) ** 2 for a in amounts) / len(amounts) if amounts else 1
    std = math.sqrt(variance) if variance > 0 else 1

    flagged = []
    for t in prepared:
        amt = t.get("amount", 0)
        z = (amt - mean) / std if std > 0 else 0
        is_integer = amt == round(amt) and amt > 10000
        risk = 0
        reasons = []
        if abs(z) > 3:
            risk += 40
            reasons.append(f"Z-Score={z:.2f}")
        if is_integer:
            risk += 30
            reasons.append("整数金额（疑似人为操纵）")
        if 2 < abs(z) <= 3:
            risk += 15
            reasons.append(f"Z-Score={z:.2f}")
        if risk > 0:
            flagged.append({
                "tx_id": t.get("tx_id", "?"),
                "amount": amt,
                "z_score": round(z, 2),
                "risk_score": min(risk, 100),
                "reasons": reasons,
            })

    flagged.sort(key=lambda x: x["risk_score"], reverse=True)
    benford_deviation = chi_square / total if total > 0 else 0
    return {
        "total_transactions": total,
        "benford_chi_square": round(chi_square, 2),
        "benford_deviation": round(benford_deviation, 4),
        "benford_expected": {str(d): round(self.model[d], 4) for d in range(1, 10)},
        "benford_observed": {str(d): observed[d] for d in range(1, 10)},
        "flagged_count": len(flagged),
        "flagged_transactions": flagged[:20],
        "amount_stats": {
            "mean": round(mean, 2),
            "std": round(std, 2),
            "max": max(amounts) if amounts else 0,
            "min": min(amounts) if amounts else 0,
        },
    }


def _fo01_postprocess(self, result):
    """添加风险分级汇总。"""
    flagged = result.get("flagged_transactions", [])
    high = sum(1 for f in flagged if f["risk_score"] >= 70)
    medium = sum(1 for f in flagged if 50 <= f["risk_score"] < 70)
    low = sum(1 for f in flagged if f["risk_score"] < 50)
    result["risk_summary"] = {
        "high_risk": high,
        "medium_risk": medium,
        "low_risk": low,
        "benford_anomaly": result.get("benford_deviation", 0) > 0.01,
    }
    return result


def patch_fo_01():
    """把 FO-01 的 MLEngine 替换为 Benford + Z-Score 实现。"""
    from modules.fo_01.engine import MLEngine
    MLEngine._load_model = _fo01_load_model
    MLEngine._preprocess = _fo01_preprocess
    MLEngine._infer = _fo01_infer
    MLEngine._postprocess = _fo01_postprocess
    return MLEngine


# ---- SC-01 供应商风险评分引擎 ----

SC01_WEIGHTS = {
    "business": 0.15,   # 工商
    "litigation": 0.25,  # 司法
    "financial": 0.30,   # 财务
    "esg": 0.15,         # ESG
    "sentiment": 0.15,   # 舆情
}


def _sc01_load_model(self):
    """加载评分权重。"""
    self.model = SC01_WEIGHTS


def _sc01_preprocess(self, input_data):
    """提取供应商列表。"""
    if self.model is None:          # API 入口未调 setup()，懒加载
        self._load_model()
    if isinstance(input_data, dict) and "suppliers" in input_data:
        return input_data["suppliers"]
    return input_data if isinstance(input_data, list) else []


def _sc01_infer(self, prepared):
    """五维加权风险评分。"""
    results = []
    for s in prepared:
        # 工商风险：低资本+短年限 → 高风险
        cap = s.get("registered_capital", 500)
        years = s.get("establishment_years", 10)
        biz_risk = min(100, (5000 / max(cap, 1)) * 10 + (20 - min(years, 20)) * 3)

        # 司法风险：涉诉+被执行
        lit = s.get("litigation_count", 0)
        exe = s.get("executed_count", 0)
        lit_risk = min(100, lit * 8 + exe * 15)

        # 财务风险：高负债+低流动
        debt = s.get("debt_ratio", 0.4)
        curr = s.get("current_ratio", 2.0)
        fin_risk = min(100, debt * 80 + max(0, (2.0 - curr)) * 30)

        # ESG 风险：处罚+碳排放
        penalty = s.get("esg_penalty", 0)
        carbon = s.get("carbon_intensity", 30)
        esg_risk = min(100, penalty * 15 + carbon * 0.5)

        # 舆情风险：负面新闻+情感
        news = s.get("negative_news", 0)
        senti = s.get("sentiment_score", 0.5)
        sen_risk = min(100, news * 4 + max(0, -senti) * 60)

        # 加权综合
        total = (
            biz_risk * self.model["business"]
            + lit_risk * self.model["litigation"]
            + fin_risk * self.model["financial"]
            + esg_risk * self.model["esg"]
            + sen_risk * self.model["sentiment"]
        )
        results.append({
            "supplier_id": s.get("supplier_id", "?"),
            "name": s.get("name", "?"),
            "risk_score": round(total, 1),
            "sub_scores": {
                "business": round(biz_risk, 1),
                "litigation": round(lit_risk, 1),
                "financial": round(fin_risk, 1),
                "esg": round(esg_risk, 1),
                "sentiment": round(sen_risk, 1),
            },
        })
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


def _sc01_postprocess(self, result):
    """风险分级：红(>=80) / 橙(60-79) / 黄(40-59) / 绿(<40)。"""
    for r in result:
        s = r["risk_score"]
        if s >= 80:
            r["level"] = "红"
        elif s >= 60:
            r["level"] = "橙"
        elif s >= 40:
            r["level"] = "黄"
        else:
            r["level"] = "绿"
    summary = {
        "total": len(result),
        "red": sum(1 for r in result if r["level"] == "红"),
        "orange": sum(1 for r in result if r["level"] == "橙"),
        "yellow": sum(1 for r in result if r["level"] == "黄"),
        "green": sum(1 for r in result if r["level"] == "绿"),
    }
    return {"suppliers": result, "summary": summary}


def patch_sc_01():
    """把 SC-01 的 MLEngine 替换为五维加权评分实现。"""
    from modules.sc_01.engine import MLEngine
    MLEngine._load_model = _sc01_load_model
    MLEngine._preprocess = _sc01_preprocess
    MLEngine._infer = _sc01_infer
    MLEngine._postprocess = _sc01_postprocess
    return MLEngine


# ============================================================
# Part 3：验证测试
# ============================================================

_passed = 0
_failed = 0


def _ok(name: str, detail: str = ""):
    global _passed
    _passed += 1
    print(f"  [PASS] {name}" + (f"  {detail}" if detail else ""))


def _fail(name: str, err: str):
    global _failed
    _failed += 1
    print(f"  [FAIL] {name}  →  {err}")


def test_imports():
    """验证导入链：shared 运行时 + 3 个代表性模块。"""
    print("\n[1/5] 导入链验证")
    try:
        from modules.shared.base_engine import AbstractEngine
        from modules.shared.config_loader import load_config
        from modules.shared.module_meta import load_module_yaml
        _ok("shared 运行时导入")
    except Exception as e:
        _fail("shared 运行时导入", str(e))
        return

    for slug in ("fa_02", "fo_01", "sc_01"):
        try:
            __import__(f"modules.{slug}.main")
            __import__(f"modules.{slug}.engine")
            __import__(f"modules.{slug}.pipeline")
            __import__(f"modules.{slug}.api")
            _ok(f"modules.{slug} 导入")
        except Exception as e:
            _fail(f"modules.{slug} 导入", str(e))


def test_config():
    """验证配置链：三级配置加载 + module.yaml 解析。"""
    print("\n[2/5] 配置链验证")
    try:
        from modules.shared.config_loader import load_config
        from modules.shared.module_meta import load_module_yaml

        mod_dir = os.path.join(REPO_ROOT, "modules", "fa_02")
        cfg = load_config(mod_dir, overrides={"threshold": {"confidence": 0.95}})
        assert "module" in cfg, "配置缺少 module 段"
        assert cfg["module"]["id"] == "FA-02", f"模块ID不符: {cfg['module'].get('id')}"
        assert cfg.get("threshold", {}).get("confidence") == 0.95, "运行时覆盖未生效"
        _ok("三级配置加载", f"id={cfg['module']['id']}, confidence={cfg['threshold']['confidence']}")

        meta = load_module_yaml(mod_dir)
        assert meta["module"]["id"] == "FA-02"
        assert meta["runtime"]["port"] == 8002
        _ok("module.yaml 解析", f"port={meta['runtime']['port']}")
    except Exception as e:
        _fail("配置链", str(e))


def test_fa_02_pipeline(field_data: dict):
    """验证 FA-02 字段标准化管道。"""
    print("\n[3/5] FA-02 字段标准化管道验证")
    try:
        MLEngine = patch_fa_02()
        from modules.fa_02.pipeline import Pipeline

        pipe = Pipeline(config={"threshold": {"confidence": 0.9}})
        pipe.engine.setup()  # 触发 _load_model
        result = pipe.run(field_data)

        std = result["standardized"]
        assert "registered_capital" in std, "缺少标准化字段 registered_capital"
        # 三个同义字段应聚合：5000 + 3000 + 2000 = 10000
        assert std["registered_capital"] == 10000, \
            f"字段聚合错误: {std['registered_capital']} != 10000"
        assert std["revenue"] == 20000, f"revenue 聚合错误: {std['revenue']}"
        assert std["net_profit"] == 5000, f"net_profit 聚合错误: {std['net_profit']}"
        assert std["litigation_count"] == 5, f"litigation_count 聚合错误: {std['litigation_count']}"

        _ok("字段名映射", f"{len(std)} 个标准字段")
        _ok("同义字段聚合", f"registered_capital=10000, revenue=20000, net_profit=5000")
        _ok("Pipeline 全链路", f"engine→thresholds→rules→formatter")
    except Exception as e:
        _fail("FA-02 管道", str(e))
        import traceback
        traceback.print_exc()


def test_fo_01_pipeline(transactions: list):
    """验证 FO-01 舞弊检测管道（Benford + Z-Score）。"""
    print("\n[4/5] FO-01 舞弊检测管道验证")
    try:
        MLEngine = patch_fo_01()
        from modules.fo_01.pipeline import Pipeline

        pipe = Pipeline()
        pipe.engine.setup()
        result = pipe.run({"transactions": transactions})

        assert result["total_transactions"] == len(transactions), "交易总数不符"
        assert result["flagged_count"] > 0, "未检测到任何异常交易"
        assert result["benford_chi_square"] > 0, "Benford 卡方统计量异常"

        # 验证注入的异常被检出
        flagged = result["flagged_transactions"]
        high_risk = [f for f in flagged if f["risk_score"] >= 70]
        assert len(high_risk) > 0, "未检测到高风险交易（>=70分）"

        # 验证 Benford 偏差
        benford_exp = result["benford_expected"]
        assert benford_exp["1"] > benford_exp["9"], "Benford 期望频率错误（1应大于9）"

        summary = result["risk_summary"]
        _ok("Benford 定律检验",
            f"χ²={result['benford_chi_square']}, deviation={result['benford_deviation']}")
        _ok("Z-Score 异常检测",
            f"检出 {result['flagged_count']} 笔异常，高风险 {summary['high_risk']} 笔")
        _ok("Pipeline 全链路",
            f"总交易={result['total_transactions']}, "
            f"红={summary['high_risk']}, 橙={summary['medium_risk']}, 黄={summary['low_risk']}")

        # 打印 Top-3 异常交易
        print("        Top-3 异常交易：")
        for f in flagged[:3]:
            print(f"          {f['tx_id']}  金额={f['amount']:>14,.2f}  "
                  f"风险={f['risk_score']:>3}  Z={f['z_score']:>6.2f}  "
                  f"原因={','.join(f['reasons'])}")
    except Exception as e:
        _fail("FO-01 管道", str(e))
        import traceback
        traceback.print_exc()


def test_sc_01_pipeline(suppliers: list):
    """验证 SC-01 供应商评分管道。"""
    print("\n[4.5/5] SC-01 供应商评分管道验证")
    try:
        MLEngine = patch_sc_01()
        from modules.sc_01.pipeline import Pipeline

        pipe = Pipeline()
        pipe.engine.setup()
        result = pipe.run({"suppliers": suppliers})

        summary = result["summary"]
        assert summary["total"] == len(suppliers), "供应商总数不符"
        assert summary["red"] + summary["orange"] > 0, \
            "未检出任何高风险供应商（红/橙级）"

        top = result["suppliers"][0]
        assert top["risk_score"] >= 60, f"最高分供应商风险分偏低: {top['risk_score']}"
        assert "sub_scores" in top, "缺少子评分"
        assert "level" in top, "缺少风险等级"

        _ok("五维加权评分",
            f"total={summary['total']}, 红={summary['red']}, "
            f"橙={summary['orange']}, 黄={summary['yellow']}, 绿={summary['green']}")
        _ok("风险分级", f"最高分: {top['name']} = {top['risk_score']} ({top['level']})")

        print("        Top-3 高风险供应商：")
        for s in result["suppliers"][:3]:
            sub = s["sub_scores"]
            print(f"          {s['supplier_id']}  {s['name']:<20}  "
                  f"总分={s['risk_score']:>5}  等级={s['level']}  "
                  f"工商={sub['business']:.0f} 司法={sub['litigation']:.0f} "
                  f"财务={sub['financial']:.0f} ESG={sub['esg']:.0f} 舆情={sub['sentiment']:.0f}")
    except Exception as e:
        _fail("SC-01 管道", str(e))
        import traceback
        traceback.print_exc()


def test_http():
    """验证 HTTP 接口：后台启动 uvicorn + urllib 请求。

    绕过 starlette TestClient 与 httpx 0.28 的版本不兼容问题
    （httpx 0.28 移除了 app= 参数，starlette 0.35 仍在使用）。
    """
    print("\n[5/5] HTTP 端到端验证（uvicorn 后台线程 + urllib）")
    try:
        import uvicorn
        from modules.fa_02.main import app as fa_app

        port = 8765  # 避开模块默认端口，防止冲突
        config = uvicorn.Config(fa_app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        # 轮询等待服务就绪（最多 15 秒）
        base = f"http://127.0.0.1:{port}"
        ready = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{base}/api/v1/health", timeout=1) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.5)

        if not ready:
            _fail("HTTP 服务启动", "15 秒内未就绪")
            return

        # 测试 /health
        with urllib.request.urlopen(f"{base}/api/v1/health", timeout=2) as r:
            body = json.loads(r.read())
            assert body["module"] == "FA-02"
            assert body["status"] == "ok"
            _ok("GET /api/v1/health", f"module={body['module']}, status={body['status']}")

        # 测试 /info
        with urllib.request.urlopen(f"{base}/api/v1/info", timeout=2) as r:
            body = json.loads(r.read())
            assert "FA-02" in str(body)
            _ok("GET /api/v1/info", f"返回={body}")

        # 测试 /execute（POST，带模拟数据）
        # 先 patch 引擎，让 /execute 能真正跑算法
        patch_fa_02()
        field_data = generate_field_data()
        payload = json.dumps(field_data).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/v1/execute",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
            assert body["status"] == "ok", f"execute 返回异常: {body}"
            result = body["result"]
            assert "standardized" in result, "结果缺少 standardized"
            _ok("POST /api/v1/execute",
                f"status=ok, fields={result['field_count']}, "
                f"registered_capital={result['standardized'].get('registered_capital')}")

        # 关闭服务
        server.should_exit = True
        thread.join(timeout=5)
        _ok("HTTP 服务关闭", "uvicorn 线程已退出")

    except urllib.error.URLError as e:
        _fail("HTTP 请求", f"连接失败: {e}")
    except Exception as e:
        _fail("HTTP 端到端", str(e))
        import traceback
        traceback.print_exc()
        # 确保清理
        try:
            server.should_exit = True
        except Exception:
            pass


# ============================================================
# Part 4：主入口
# ============================================================

def main():
    print("=" * 70)
    print("  预制菜模块脚手架 —— 端到端验证")
    print("  数据来源：模拟生成（含注入异常，非真实爬取）")
    print("  算法注入：运行时 monkey-patch（不改原文件）")
    print("  HTTP 方案：uvicorn 后台线程 + urllib（绕过 TestClient 版本问题）")
    print("=" * 70)

    # 生成模拟数据
    print("\n[0/5] 生成模拟审计数据")
    transactions = generate_transactions(2000)
    print(f"  生成 {len(transactions)} 笔交易（含 Benford 分布 + 注入异常）")
    suppliers = generate_suppliers(150)
    print(f"  生成 {len(suppliers)} 家供应商（含五维风险特征 + 高风险样本）")
    field_data = generate_field_data()
    print(f"  生成 {len(field_data['fields'])} 个字段映射（含 {len(set(f['raw_name'] for f in field_data['fields']))} 个名称变体）")

    # 执行验证
    test_imports()
    test_config()
    test_fa_02_pipeline(field_data)
    test_fo_01_pipeline(transactions)
    test_sc_01_pipeline(suppliers)
    test_http()

    # 汇总
    total = _passed + _failed
    print("\n" + "=" * 70)
    print(f"  验证结果：{total} 项  →  通过 {_passed}  /  失败 {_failed}")
    if _failed == 0:
        print("  ✅ 全链路跑通：导入 → 配置 → 管道 → 算法 → HTTP")
    else:
        print("  ❌ 有失败项，请检查上方 [FAIL] 详情")
    print("=" * 70)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
