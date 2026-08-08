"""[SC-01] 供应商风险智能评分引擎 —— 五维加权评分 + 风险分级。

算法设计（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，纯 stdlib 实现，不引入任何第三方依赖）：

  * 工商维度（business, 权重 0.15）：注册资本 / 成立年限 / 经营状态 / 变更频次
                                     —— 纯规则评分（阈值分级）
  * 司法维度（litigation, 权重 0.25）：诉讼数量 / 被执行 / 失信记录
                                     —— 计数加权 + 关键词匹配
  * 财务维度（financial, 权重 0.30）：营收 / 资产负债率 / 流动比率 / 现金流
                                     —— 阈值评分，用 math 计算比率
  * ESG 维度（esg, 权重 0.15）：环保处罚 / 社保合规 / 税务违规
                                     —— 关键词匹配 + 计数加权
  * 舆情维度（sentiment, 权重 0.15）：负面新闻数量与情感倾向
                                     —— 纯 stdlib 情感分析（负面/正面词典词频）

  * 综合评分：五维加权汇总 → 综合风险评分（0-100，越高越危险）
  * 风险等级：≥80 极高 / 60-80 高 / 40-60 中 / <40 低
  * 评估周期：从季度/年度压缩至 T+1 天（自动化采集 + 评分）

模型结构（self.model）：
  {
    "weights":   {"business": 0.15, "litigation": 0.25, "financial": 0.30,
                  "esg": 0.15, "sentiment": 0.15},
    "levels":    [("极高", 80), ("高", 60), ("中", 40), ("低", 0)],
    "keywords":  {
        "litigation":          [诉讼, 纠纷, 起诉, 被执行, 失信, ...],
        "esg":                 [环保, 污染, 排放, 欠薪, 偷税, ...],
        "sentiment_negative":  [违约, 破产, 欺诈, 造假, 暴雷, ...],
        "sentiment_positive":  [增长, 获奖, 优质, 创新, ...],
    },
  }

PortableDB 持久化（中心化公用辐射）：
  - suppliers           供应商主表（按 supplier_id 唯一）
  - risk_assessments    评分结果（每次执行追加，含五维子分/风险点/建议）
  - risk_events         风险事件明细（每个风险点一条记录）
  - scoring_weights     评分权重配置（可调参）
  - risk_keywords       风险关键词库（司法/ESG/舆情）
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# 模块根目录（用于定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "sc_01.db"

# 出厂默认权重（五维加权，和为 1.0；与 module.yaml threshold.confidence=0.85 一致）
_DEFAULT_WEIGHTS = {
    "business": 0.15,
    "litigation": 0.25,
    "financial": 0.30,
    "esg": 0.15,
    "sentiment": 0.15,
}
_DEFAULT_WEIGHT_DESC = {
    "business": "工商风险（注册资本/成立年限/经营状态/变更频次）",
    "litigation": "司法风险（诉讼/被执行/失信 + 关键词匹配）",
    "financial": "财务风险（负债率/流动比率/现金流，math 比率计算）",
    "esg": "ESG风险（环保处罚/社保合规/税务违规 + 关键词匹配）",
    "sentiment": "舆情风险（负面新闻数量 + 纯stdlib情感分析）",
}

# 风险等级阈值（与 custom_thresholds 保持一致）
_DEFAULT_LEVELS = [("极高", 80), ("高", 60), ("中", 40), ("低", 0)]

# 内置风险关键词库（fixtures 缺失时的兜底；fixtures/risk_keywords.jsonl 优先级更高）
_BUILTIN_KEYWORDS = {
    "litigation": [
        "诉讼", "纠纷", "起诉", "被告", "被执行", "失信", "判决", "欠款",
        "拖欠", "违约金", "强制执行", "限制消费", "限消", "查封", "冻结",
    ],
    "esg": [
        "环保", "污染", "排放", "欠薪", "欠税", "偷税", "漏税", "处罚",
        "违规排放", "安全事故", "社保违规", "停产", "整顿",
    ],
    "sentiment_negative": [
        "违约", "破产", "欺诈", "造假", "暴雷", "被查", "退市", "亏损",
        "裁员", "欠薪", "纠纷", "违规", "风险", "下滑", "暴跌", "问询",
        "警告", "处罚", "通报", "涉嫌", "立案", "执行", "爆雷", "停牌",
    ],
    "sentiment_positive": [
        "增长", "获奖", "优质", "创新", "突破", "领先", "卓越", "优秀",
        "表彰", "上榜", "第一", "突出", "盈利", "稳健", "认可", "提升",
    ],
}

# ---------- PortableDB 表 schema ----------
_SUPPLIERS_SCHEMA = {
    "supplier_id": "TEXT PRIMARY KEY",
    "name": "TEXT",
    "uscc": "TEXT",
    "registered_capital": "REAL",
    "establishment_years": "REAL",
    "business_status": "TEXT",
    "change_count": "INTEGER",
    "source": "TEXT",
    "payload": "JSON",
    "ingested_at": "DATETIME",
}
_RISK_ASSESSMENTS_SCHEMA = {
    "supplier_id": "TEXT",
    "name": "TEXT",
    "total_score": "REAL",
    "level": "TEXT",
    "sub_scores": "JSON",
    "risk_points": "JSON",
    "recommendations": "JSON",
    "assessed_at": "DATETIME",
}
_RISK_EVENTS_SCHEMA = {
    "supplier_id": "TEXT",
    "name": "TEXT",
    "dimension": "TEXT",
    "event_type": "TEXT",
    "severity": "TEXT",
    "description": "TEXT",
    "created_at": "DATETIME",
}
_SCORING_WEIGHTS_SCHEMA = {
    "dimension": "TEXT PRIMARY KEY",
    "weight": "REAL",
    "description": "TEXT",
}
_RISK_KEYWORDS_SCHEMA = {
    "category": "TEXT",
    "keyword": "TEXT",
    "weight": "REAL",
}


# ---------- 工具函数 ----------
def _clean_uscc(uscc: Any) -> str:
    """统一社会信用代码标准化：去空白 + 转大写 + 去标点（保留字母数字）。"""
    if not uscc or not isinstance(uscc, str):
        return ""
    return re.sub(r"\s+", "", uscc).upper()


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转 float：None/异常返回 default。"""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """安全转 int。"""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """将分数限定在 [lo, hi] 区间。"""
    return max(lo, min(hi, value))


def _count_keyword_hits(text: Any, keywords) -> int:
    """统计 keywords 在 text 中的命中总次数（同词多次出现也计入）。"""
    if not text or not isinstance(text, str):
        return 0
    hits = 0
    for kw in keywords:
        if not kw:
            continue
        hits += text.count(kw)
    return hits


class MLEngine(AbstractEngine):
    """供应商五维风险评分引擎（纯 stdlib 实现）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改：预处理 → 推理 → 后处理。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        # 允许 config 覆盖 fixtures / db 路径，便于测试隔离
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载评分权重配置 + 风险关键词库 + PortableDB 初始化（建四张核心表）。

        数据来源（按优先级合并）：
          1. PortableDB scoring_weights 表（持久化的权重配置，最高优先级）
          2. 内置 _DEFAULT_WEIGHTS（兜底）
          3. PortableDB risk_keywords 表（持久化的关键词库）
          4. tests/fixtures/risk_keywords.jsonl（首次启动种子导入）
          5. 内置 _BUILTIN_KEYWORDS（兜底）
        """
        # 1. 初始化 PortableDB（中心化公用辐射）
        self.db = PortableDB(self.db_path)

        # 2. 建表（若不存在）
        for name, schema in [
            ("suppliers", _SUPPLIERS_SCHEMA),
            ("risk_assessments", _RISK_ASSESSMENTS_SCHEMA),
            ("risk_events", _RISK_EVENTS_SCHEMA),
            ("scoring_weights", _SCORING_WEIGHTS_SCHEMA),
            ("risk_keywords", _RISK_KEYWORDS_SCHEMA),
        ]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)

        # 3. 若 scoring_weights 为空，写入出厂默认权重
        if self.db.count("scoring_weights") == 0:
            self.db.insert_many("scoring_weights", [
                {
                    "dimension": dim,
                    "weight": float(w),
                    "description": _DEFAULT_WEIGHT_DESC.get(dim, ""),
                }
                for dim, w in _DEFAULT_WEIGHTS.items()
            ])

        # 4. 合并权重（DB 优先，缺失维度用默认补全）
        weights: dict[str, float] = {}
        for row in self.db.all("scoring_weights"):
            weights[row["dimension"]] = float(row["weight"])
        for dim, w in _DEFAULT_WEIGHTS.items():
            weights.setdefault(dim, float(w))

        # 5. 合并关键词库（内置兜底 + DB 持久化 + fixtures 种子）
        keywords: dict[str, list[str]] = {
            cat: list(kws) for cat, kws in _BUILTIN_KEYWORDS.items()
        }
        # 5.1 若 risk_keywords 表为空，从 fixtures 导入种子
        if self.db.count("risk_keywords") == 0:
            kw_fixture = self.fixtures_dir / "risk_keywords.jsonl"
            if kw_fixture.exists():
                self.db.import_jsonl(
                    "risk_keywords", kw_fixture,
                    schema=_RISK_KEYWORDS_SCHEMA, drop_if_exists=False,
                )
        # 5.2 合并 DB 关键词（去重保序）
        for row in self.db.all("risk_keywords"):
            cat = row.get("category")
            kw = row.get("keyword")
            if cat and kw:
                keywords.setdefault(cat, [])
                if kw not in keywords[cat]:
                    keywords[cat].append(kw)

        self.model = {
            "weights": weights,
            "levels": _DEFAULT_LEVELS,
            "keywords": keywords,
        }

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """提取供应商列表，清洗（USCC 标准化 / 名称去重 / 五维数据补全与缺失值处理）。"""
        # 懒加载：若未显式 setup()，execute() 时自动加载模型
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 suppliers 列表")

        suppliers = input_data.get("suppliers", [])
        if not isinstance(suppliers, list):
            raise ValueError("input_data['suppliers'] 必须为列表")

        cleaned: list[dict] = []
        seen_uscc: set[str] = set()
        seen_name: set[str] = set()
        default_source = input_data.get("source", "default")

        for s in suppliers:
            if not isinstance(s, dict):
                continue
            uscc = _clean_uscc(s.get("uscc"))
            name = (s.get("name") or "").strip()
            # 实体对齐：优先用 USCC 去重，无 USCC 则用名称去重
            dedup_key = uscc if uscc else name
            if not dedup_key:
                continue
            if uscc and uscc in seen_uscc:
                continue
            if not uscc and name in seen_name:
                continue
            if uscc:
                seen_uscc.add(uscc)
            else:
                seen_name.add(name)

            biz = s.get("business", {}) or {}
            lit = s.get("litigation", {}) or {}
            fin = s.get("financial", {}) or {}
            esg = s.get("esg", {}) or {}
            sen = s.get("sentiment", {}) or {}

            cleaned.append({
                "supplier_id": s.get("supplier_id") or f"S-{len(cleaned) + 1:04d}",
                "name": name or "未命名供应商",
                "uscc": uscc,
                "source": s.get("source", default_source),
                "business": {
                    "registered_capital": _safe_float(biz.get("registered_capital")),
                    "establishment_years": _safe_float(biz.get("establishment_years")),
                    "business_status": (biz.get("business_status") or "未知").strip(),
                    "change_count": _safe_int(biz.get("change_count")),
                },
                "litigation": {
                    "litigation_count": _safe_int(lit.get("litigation_count")),
                    "executed_count": _safe_int(lit.get("executed_count")),
                    "dishonest_count": _safe_int(lit.get("dishonest_count")),
                    "litigation_text": lit.get("litigation_text") or "",
                },
                "financial": {
                    "revenue": _safe_float(fin.get("revenue")),
                    "debt_ratio": _safe_float(fin.get("debt_ratio")),
                    "current_ratio": _safe_float(fin.get("current_ratio")),
                    "cash_flow": _safe_float(fin.get("cash_flow")),
                },
                "esg": {
                    "esg_penalty_count": _safe_int(esg.get("esg_penalty_count")),
                    "social_security_compliance": (
                        esg.get("social_security_compliance") or "未知"
                    ).strip(),
                    "tax_violation_count": _safe_int(esg.get("tax_violation_count")),
                    "esg_text": esg.get("esg_text") or "",
                },
                "sentiment": {
                    "news_count": _safe_int(sen.get("news_count")),
                    "news_text": sen.get("news_text") or "",
                },
                "_raw": s,  # 保留原始字段用于落库
            })

        return {"source": default_source, "suppliers": cleaned}

    # ------------------------------------------------------------------
    # 推理：五维评分 + 加权汇总
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """五维子评分计算 + 加权汇总综合风险评分（0-100）。"""
        model = self.model or {}
        weights = model.get("weights", _DEFAULT_WEIGHTS)
        keywords = model.get("keywords", _BUILTIN_KEYWORDS)

        results: list[dict] = []
        for s in prepared["suppliers"]:
            biz = s["business"]
            lit = s["litigation"]
            fin = s["financial"]
            esg = s["esg"]
            sen = s["sentiment"]

            # ① 工商维度：纯规则评分
            biz_score, biz_points = self._score_business(biz)
            # ② 司法维度：关键词匹配 + 计数加权
            lit_score, lit_points = self._score_litigation(
                lit, keywords.get("litigation", []),
            )
            # ③ 财务维度：阈值评分，math 计算比率
            fin_score, fin_points = self._score_financial(fin)
            # ④ ESG 维度：关键词匹配
            esg_score, esg_points = self._score_esg(
                esg, keywords.get("esg", []),
            )
            # ⑤ 舆情维度：纯 stdlib 情感分析（负面/正面词典词频）
            sen_score, sen_points = self._score_sentiment(
                sen,
                keywords.get("sentiment_negative", []),
                keywords.get("sentiment_positive", []),
            )

            # 加权汇总综合风险评分（0-100，越高越危险）
            total = (
                biz_score * weights["business"]
                + lit_score * weights["litigation"]
                + fin_score * weights["financial"]
                + esg_score * weights["esg"]
                + sen_score * weights["sentiment"]
            )
            total = _clamp(total)

            risk_points = (
                [{"dimension": "business", "point": p} for p in biz_points]
                + [{"dimension": "litigation", "point": p} for p in lit_points]
                + [{"dimension": "financial", "point": p} for p in fin_points]
                + [{"dimension": "esg", "point": p} for p in esg_points]
                + [{"dimension": "sentiment", "point": p} for p in sen_points]
            )

            results.append({
                "supplier_id": s["supplier_id"],
                "name": s["name"],
                "uscc": s["uscc"],
                "source": s["source"],
                "total_score": round(total, 1),
                "sub_scores": {
                    "business": round(biz_score, 1),
                    "litigation": round(lit_score, 1),
                    "financial": round(fin_score, 1),
                    "esg": round(esg_score, 1),
                    "sentiment": round(sen_score, 1),
                },
                "risk_points": risk_points,
                "_raw": s.get("_raw", {}),
            })

        # 按综合风险评分降序排列（高风险在前）
        results.sort(key=lambda x: x["total_score"], reverse=True)
        return {"suppliers": results, "source": prepared.get("source")}

    # ------------------------------------------------------------------
    # 五维评分细节
    # ------------------------------------------------------------------
    def _score_business(self, biz: dict) -> tuple[float, list[str]]:
        """① 工商维度：注册资本 / 成立年限 / 经营状态 / 变更频次（纯规则评分）。"""
        cap = biz["registered_capital"]           # 单位：元
        years = biz["establishment_years"]
        status = biz["business_status"]
        change = biz["change_count"]
        points: list[str] = []

        # 注册资本（元）：≥500万=低风险；100-500万=一般；10-100万=偏低；<10万=过低
        if cap <= 0:
            cap_score = 80.0
            points.append("注册资本缺失（建议补充工商数据）")
        elif cap < 100000:                        # <10万
            cap_score = 80.0
            points.append(f"注册资本过低（{cap / 10000:.2f}万元）")
        elif cap < 1000000:                       # 10万-100万
            cap_score = 50.0
            points.append(f"注册资本偏低（{cap / 10000:.2f}万元）")
        elif cap < 5000000:                       # 100万-500万
            cap_score = 25.0
            points.append(f"注册资本一般（{cap / 10000:.2f}万元）")
        elif cap < 50000000:                      # 500万-5000万
            cap_score = 10.0
        else:                                     # ≥5000万：用对数衰减趋近 0
            # log10(5e7)≈7.7，log10(5e8)≈8.7，越大越趋近 0
            cap_score = _clamp(10.0 * (math.log10(50000000) / max(math.log10(cap), 1.0)) - 8.0)
            cap_score = max(0.0, cap_score)

        # 成立年限（年）：≥10年=低；5-10=偏低；3-5=偏短；1-3=较短；<1=新设
        if years <= 0:
            years_score = 80.0
            points.append("成立年限缺失（建议核实）")
        elif years < 1:
            years_score = 80.0
            points.append(f"新设企业（成立{years:.1f}年）")
        elif years < 3:
            years_score = 50.0
            points.append(f"成立年限较短（{years:.1f}年）")
        elif years < 5:
            years_score = 30.0
            points.append(f"成立年限偏短（{years:.1f}年）")
        elif years < 10:
            years_score = 15.0
        else:
            years_score = 5.0

        # 经营状态：注销/吊销/停业/清算=极高；存续=低；其他=中等
        if status in ("注销", "吊销", "停业", "清算"):
            status_score = 100.0
            points.append(f"经营状态异常：{status}")
        elif status == "存续":
            status_score = 0.0
        elif status in ("在营", "在业", "正常"):
            status_score = 5.0
        else:
            status_score = 40.0
            points.append(f"经营状态非标准：{status}")

        # 变更频次：0=0；1-2=15；3-5=30；6+=50
        if change >= 6:
            change_score = 50.0
            points.append(f"工商变更频次过高（{change}次）")
        elif change >= 3:
            change_score = 30.0
            points.append(f"工商变更频次较高（{change}次）")
        elif change >= 1:
            change_score = 15.0
        else:
            change_score = 0.0

        # 加权（注册资本30% + 年限30% + 状态25% + 变更15%）
        score = (
            cap_score * 0.30
            + years_score * 0.30
            + status_score * 0.25
            + change_score * 0.15
        )
        return _clamp(score), points

    def _score_litigation(self, lit: dict, keywords: list) -> tuple[float, list[str]]:
        """② 司法维度：诉讼数量 / 被执行 / 失信记录（关键词匹配 + 计数加权）。"""
        count = lit["litigation_count"]
        exe = lit["executed_count"]
        dishonest = lit["dishonest_count"]
        text = lit["litigation_text"] or ""
        points: list[str] = []

        # 诉讼数量：0=0；1-3=30；4-10=60；10+=85
        if count >= 10:
            count_score = 85.0
            points.append(f"诉讼数量过多（{count}起）")
        elif count >= 4:
            count_score = 60.0
            points.append(f"诉讼数量较多（{count}起）")
        elif count >= 1:
            count_score = 30.0
            points.append(f"存在诉讼记录（{count}起）")
        else:
            count_score = 0.0

        # 被执行记录：0=0；1=50；2+=80
        if exe >= 2:
            exe_score = 80.0
            points.append(f"多次被执行（{exe}次）")
        elif exe == 1:
            exe_score = 50.0
            points.append("存在被执行记录")
        else:
            exe_score = 0.0

        # 失信记录：0=0；1+=100（一票否决式高风险）
        if dishonest >= 1:
            dis_score = 100.0
            points.append(f"失信被执行人（{dishonest}次）")
        else:
            dis_score = 0.0

        # 关键词匹配：每个命中加 5 分（上限 40）
        kw_hits = _count_keyword_hits(text, keywords)
        kw_score = _clamp(kw_hits * 5.0, 0.0, 40.0)
        if kw_hits > 0:
            points.append(f"司法文本命中风险关键词{kw_hits}处")

        # 加权（数量30% + 被执行25% + 失信30% + 关键词15%）
        score = (
            count_score * 0.30
            + exe_score * 0.25
            + dis_score * 0.30
            + kw_score * 0.15
        )
        return _clamp(score), points

    def _score_financial(self, fin: dict) -> tuple[float, list[str]]:
        """③ 财务维度：营收 / 负债率 / 流动比率 / 现金流（阈值评分，math 计算比率）。"""
        revenue = fin["revenue"]
        debt_ratio = fin["debt_ratio"]            # 0-1 之间
        current_ratio = fin["current_ratio"]
        cash_flow = fin["cash_flow"]
        points: list[str] = []

        # 资产负债率：<0.4=低；0.4-0.6=偏低；0.6-0.8=偏高；≥0.8=过高
        if debt_ratio <= 0:
            debt_score = 50.0
            points.append("资产负债率缺失（默认中等风险）")
        elif debt_ratio >= 0.8:
            debt_score = 85.0
            points.append(f"资产负债率过高（{debt_ratio * 100:.1f}%）")
        elif debt_ratio >= 0.6:
            debt_score = 50.0
            points.append(f"资产负债率偏高（{debt_ratio * 100:.1f}%）")
        elif debt_ratio >= 0.4:
            debt_score = 20.0
        else:
            debt_score = 5.0

        # 流动比率：≥2=低；1.5-2=偏低；1-1.5=偏紧；<1=紧张
        if current_ratio <= 0:
            curr_score = 60.0
            points.append("流动比率缺失（默认中高风险）")
        elif current_ratio < 1.0:
            curr_score = 80.0
            points.append(
                f"流动比率过低（{current_ratio:.2f}，短期偿债压力大）"
            )
        elif current_ratio < 1.5:
            curr_score = 40.0
            points.append(f"流动比率偏低（{current_ratio:.2f}）")
        elif current_ratio < 2.0:
            curr_score = 20.0
        else:
            curr_score = 5.0

        # 现金流：负=高；零/极小=中等；正且≥营收5%=低
        if cash_flow < 0:
            cf_score = 80.0
            points.append(f"经营现金流为负（{cash_flow / 10000:.2f}万元）")
        elif cash_flow == 0:
            cf_score = 60.0
            points.append("经营现金流为零")
        elif revenue > 0 and cash_flow < revenue * 0.05:
            cf_score = 30.0
            # 用 math 计算现金流营收比，标注偏弱
            ratio = cash_flow / revenue
            points.append(
                f"现金流相对营收偏弱（现金流营收比 {ratio * 100:.1f}%）"
            )
        else:
            cf_score = 5.0

        # 营收缺失标记（仅作风险点，不直接计分）
        if revenue <= 0:
            points.append("营收数据缺失（建议补充财务报表）")

        # 加权：负债率40% + 流动比率30% + 现金流30%
        score = (
            debt_score * 0.40
            + curr_score * 0.30
            + cf_score * 0.30
        )
        return _clamp(score), points

    def _score_esg(self, esg: dict, keywords: list) -> tuple[float, list[str]]:
        """④ ESG维度：环保处罚 / 社保合规 / 税务违规（关键词匹配）。"""
        penalty = esg["esg_penalty_count"]
        ss_comp = esg["social_security_compliance"]
        tax_violation = esg["tax_violation_count"]
        text = esg["esg_text"] or ""
        points: list[str] = []

        # 环保处罚：0=0；1=50；2+=80
        if penalty >= 2:
            pen_score = 80.0
            points.append(f"多次环保处罚（{penalty}次）")
        elif penalty == 1:
            pen_score = 50.0
            points.append("存在环保处罚记录")
        else:
            pen_score = 0.0

        # 社保合规：合规=0；不合规=70；未知=30
        if ss_comp in ("不合规", "违规", "欠缴", "未缴"):
            ss_score = 70.0
            points.append(f"社保不合规：{ss_comp}")
        elif ss_comp == "合规":
            ss_score = 0.0
        else:
            ss_score = 30.0
            points.append(f"社保状态不明：{ss_comp}")

        # 税务违规：0=0；1=60；2+=85
        if tax_violation >= 2:
            tax_score = 85.0
            points.append(f"多次税务违规（{tax_violation}次）")
        elif tax_violation == 1:
            tax_score = 60.0
            points.append("存在税务违规记录")
        else:
            tax_score = 0.0

        # 关键词匹配：每命中加 5 分（上限 30）
        kw_hits = _count_keyword_hits(text, keywords)
        kw_score = _clamp(kw_hits * 5.0, 0.0, 30.0)
        if kw_hits > 0:
            points.append(f"ESG文本命中风险关键词{kw_hits}处")

        # 加权：环保30% + 社保30% + 税务30% + 关键词10%
        score = (
            pen_score * 0.30
            + ss_score * 0.30
            + tax_score * 0.30
            + kw_score * 0.10
        )
        return _clamp(score), points

    def _score_sentiment(self, sen: dict, neg_kws: list,
                         pos_kws: list) -> tuple[float, list[str]]:
        """⑤ 舆情维度：负面新闻数量 + 情感倾向（纯 stdlib 情感分析）。"""
        news_count = sen["news_count"]
        text = sen["news_text"] or ""
        points: list[str] = []

        # 负面新闻数量：0=0；1-3=30；4-10=60；10+=85
        if news_count >= 10:
            news_score = 85.0
            points.append(f"负面新闻过多（{news_count}条）")
        elif news_count >= 4:
            news_score = 60.0
            points.append(f"负面新闻较多（{news_count}条）")
        elif news_count >= 1:
            news_score = 30.0
            points.append(f"存在负面新闻（{news_count}条）")
        else:
            news_score = 0.0

        # 纯 stdlib 情感分析：负面词频 vs 正面词频 → 负面占比 → 风险分
        neg_hits = _count_keyword_hits(text, neg_kws)
        pos_hits = _count_keyword_hits(text, pos_kws)
        total_hits = neg_hits + pos_hits
        if total_hits == 0:
            # 无可识别情感词：若 news_count=0 给低风险，有新闻但无词给中等
            senti_score = 30.0 if news_count > 0 else 10.0
            if text and news_count > 0:
                points.append("舆情文本无可识别倾向")
        else:
            # 负面占比 → 风险分（负面占比越高，风险越高）
            neg_ratio = neg_hits / total_hits
            senti_score = _clamp(neg_ratio * 100.0)
            if neg_hits > 0:
                points.append(
                    f"舆情负面倾向（负面词{neg_hits}处，正面词{pos_hits}处，"
                    f"负面占比{neg_ratio * 100:.0f}%）"
                )

        # 加权：新闻数量50% + 情感倾向50%
        score = news_score * 0.50 + senti_score * 0.50
        return _clamp(score), points

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """输出每个供应商评分明细 + 风险等级 + 风险点清单 + 建议措施；统计汇总。"""
        levels = (self.model or {}).get("levels", _DEFAULT_LEVELS)
        for r in result["suppliers"]:
            score = r["total_score"]
            # 风险等级映射（≥80 极高 / 60-80 高 / 40-60 中 / <40 低）
            level = "低"
            for lv, threshold in levels:
                if score >= threshold:
                    level = lv
                    break
            r["level"] = level
            # 维度级建议措施
            r["recommendations"] = self._recommendations(r)

        suppliers = result["suppliers"]
        summary = {
            "total": len(suppliers),
            "level_distribution": {
                "极高": sum(1 for r in suppliers if r["level"] == "极高"),
                "高": sum(1 for r in suppliers if r["level"] == "高"),
                "中": sum(1 for r in suppliers if r["level"] == "中"),
                "低": sum(1 for r in suppliers if r["level"] == "低"),
            },
        }
        result["summary"] = summary
        return result

    def _recommendations(self, r: dict) -> list[str]:
        """根据风险等级 + 各维度子分生成建议措施（去重保序）。"""
        level = r["level"]
        recs: list[str] = []
        if level == "极高":
            recs.append("立即暂停合作，启动专项尽职调查")
            recs.append("法务介入评估违约风险与替代供应商方案")
        elif level == "高":
            recs.append("收紧账期，提高预付款比例")
            recs.append("季度跟踪复评，重点监控司法与财务维度")
        elif level == "中":
            recs.append("半年度复评，关注高风险维度变化")
        else:
            recs.append("年度常规复评")

        # 维度级建议（子分 ≥ 60 触发）
        sub = r["sub_scores"]
        if sub.get("litigation", 0) >= 60:
            recs.append("核查诉讼/被执行/失信详情与影响范围")
        if sub.get("financial", 0) >= 60:
            recs.append("要求补充近期财报与银行流水")
        if sub.get("esg", 0) >= 60:
            recs.append("核查环保/社保/税务合规整改情况")
        if sub.get("sentiment", 0) >= 60:
            recs.append("持续监测舆情动态与传播范围")
        if sub.get("business", 0) >= 60:
            recs.append("核查工商变更原因与股东背景")

        return list(dict.fromkeys(recs))  # 去重保序

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 PortableDB 连接。"""
        if self.db is not None:
            self.db.close()
            self.db = None
