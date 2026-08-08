"""[FO-01] 全量交易智能舞弊扫描引擎 —— 四层扫描模型（纯 stdlib）。

四层扫描架构（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，不引入任何第三方依赖）：

  * 第一层 统计层：
      - Benford 定律卡方检验（首位数字分布偏离 log10(1+1/d)）
      - Z-Score 异常检测（|z| > 3σ）
      - IQR 异常检测（超出 [Q1-1.5*IQR, Q3+1.5*IQR]）
  * 第二层 无监督 ML 层：
      - 模拟 Isolation Forest：随机选特征+随机切分点算路径深度，路径短=异常
      - 重构误差代理：与特征中心点的标准化欧氏距离
  * 第三层 监督 ML 层：
      - 规则匹配历史舞弊模式（年末大额/整数金额/非营业时间/关联方等）
  * 第四层 知识图谱层：
      - 构建交易对手网络（dict+set），发现共享地址/电话/法人的隐藏关联

模型结构（self.model）：
  {
    "benford_expected": {1..9: log10(1+1/d)},
    "benford_critical": 15.507,                # df=8, p=0.05 卡方临界值
    "layer_weights": {"statistical": 0.30, "unsupervised": 0.25,
                      "supervised": 0.30, "graph": 0.15},
    "fraud_patterns": [...],                    # 历史舞弊模式库
    "iqr_multiplier": 1.5,
    "z_threshold": 3.0,
    "iso_forest": {"n_trees": 50, "sample_size": 256, "max_depth": 8},
  }
"""
from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# 模块根目录（用于定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fo_01.db"

# 卡方临界值（df=8, p=0.05）—— Benford 首位数字分布检验
_BENFORD_CRITICAL_VALUE = 15.507

# PortableDB 表 schema —— transactions / fraud_flags / fraud_patterns / scan_results
_TRANSACTIONS_SCHEMA = {
    "tx_id": "TEXT",
    "amount": "REAL",
    "tx_date": "TEXT",
    "tx_time": "TEXT",
    "hour": "INTEGER",
    "counterparty": "TEXT",
    "counterparty_address": "TEXT",
    "counterparty_phone": "TEXT",
    "counterparty_legal_rep": "TEXT",
    "account_id": "TEXT",
    "description": "TEXT",
    "is_related_party": "INTEGER",
    "tx_type": "TEXT",
    "payload": "JSON",
}

_FRAUD_FLAGS_SCHEMA = {
    "tx_id": "TEXT",
    "layer": "TEXT",
    "sub_layer": "TEXT",
    "evidence": "TEXT",
    "score_contribution": "REAL",
    "created_at": "DATETIME",
}

_FRAUD_PATTERNS_SCHEMA = {
    "pattern_id": "TEXT",
    "name": "TEXT",
    "description": "TEXT",
    "layer": "TEXT",
    "conditions": "JSON",
    "weight": "REAL",
    "enabled": "INTEGER",
}

_SCAN_RESULTS_SCHEMA = {
    "scan_id": "TEXT",
    "tx_id": "TEXT",
    "risk_score": "REAL",
    "risk_level": "TEXT",
    "hit_layers": "JSON",
    "evidence_chain": "JSON",
    "matched_patterns": "JSON",
    "created_at": "DATETIME",
}


def _parse_amount(value: Any) -> float:
    """金额转 float：支持字符串（含千分位/货币符号/万/亿单位）。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    # 去除货币符号与千分位
    s = re.sub(r"[¥$€£,\s]", "", s)
    # 处理中文单位
    multiplier = 1.0
    if s.endswith("万"):
        s = s[:-1]
        multiplier = 10000.0
    elif s.endswith("亿"):
        s = s[:-1]
        multiplier = 100000000.0
    try:
        return float(s) * multiplier
    except ValueError:
        return 0.0


def _parse_date(value: Any) -> date | None:
    """日期归一化：支持多种格式 → date 对象。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d",
                "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_hour(value: Any) -> int | None:
    """提取小时：从 time 字段或 datetime 字符串。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).time().hour
        except ValueError:
            continue
    # 尝试完整 datetime 解析
    try:
        return datetime.fromisoformat(s).hour
    except ValueError:
        return None


def _normalize_name(name: Any) -> str:
    """对手名称标准化：去首尾空格 + 多空格合一。"""
    if name is None:
        return ""
    return re.sub(r"\s+", " ", str(name).strip())


def _extract_month(t: dict) -> int | None:
    """从交易记录提取月份。"""
    s = t.get("tx_date")
    if not s:
        return None
    try:
        return date.fromisoformat(s).month
    except (ValueError, TypeError):
        return None


def _extract_day(t: dict) -> int | None:
    """从交易记录提取日。"""
    s = t.get("tx_date")
    if not s:
        return None
    try:
        return date.fromisoformat(s).day
    except (ValueError, TypeError):
        return None


class MLEngine(AbstractEngine):
    """全量交易舞弊扫描引擎（四层模型，纯 stdlib）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改：预处理 → 推理 → 后处理。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------
    def _load_model(self) -> None:
        """加载历史舞弊模式库 + 初始化 PortableDB（建 4 张表）。

        数据来源：
          1. tests/fixtures/fraud_patterns.jsonl  历史舞弊模式库（规则+特征）
          2. PortableDB fraud_patterns 表（人工维护的模式，同源）
        PortableDB 表：transactions / fraud_flags / fraud_patterns / scan_results
        """
        self.db = PortableDB(self.db_path)

        # 建 4 张表（若不存在）
        if "transactions" not in self.db.tables():
            self.db.create_table("transactions", _TRANSACTIONS_SCHEMA)
        if "fraud_flags" not in self.db.tables():
            self.db.create_table("fraud_flags", _FRAUD_FLAGS_SCHEMA)
        if "fraud_patterns" not in self.db.tables():
            self.db.create_table("fraud_patterns", _FRAUD_PATTERNS_SCHEMA)
        if "scan_results" not in self.db.tables():
            self.db.create_table("scan_results", _SCAN_RESULTS_SCHEMA)

        # 首次启动：从 fixtures 导入历史舞弊模式库
        if self.db.count("fraud_patterns") == 0:
            fp_fixture = self.fixtures_dir / "fraud_patterns.jsonl"
            if fp_fixture.exists():
                self.db.import_jsonl(
                    "fraud_patterns", fp_fixture,
                    schema=_FRAUD_PATTERNS_SCHEMA, drop_if_exists=False,
                )

        # 加载启用的规则
        patterns = [dict(r) for r in self.db.all("fraud_patterns")]
        patterns = [p for p in patterns if p.get("enabled", 1)]

        self.model = {
            "benford_expected": {d: math.log10(1 + 1 / d) for d in range(1, 10)},
            "benford_critical": _BENFORD_CRITICAL_VALUE,
            "layer_weights": {
                "statistical": 0.30,
                "unsupervised": 0.25,
                "supervised": 0.30,
                "graph": 0.15,
            },
            "fraud_patterns": patterns,
            "iqr_multiplier": float(
                self.config.get("threshold", {}).get("iqr_multiplier", 1.5)
            ),
            "z_threshold": float(
                self.config.get("threshold", {}).get("z_score", 3.0)
            ),
            "iso_forest": {
                "n_trees": int(self.config.get("iso_forest", {}).get("n_trees", 50)),
                "sample_size": int(
                    self.config.get("iso_forest", {}).get("sample_size", 256)
                ),
                "max_depth": int(
                    self.config.get("iso_forest", {}).get("max_depth", 8)
                ),
            },
            "random_seed": int(self.config.get("random_seed", 42)),
        }

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """提取交易记录列表 + 清洗（金额转float、日期归一化、对手名称标准化）。"""
        if self.model is None:
            self._load_model()

        # 提取交易列表（兼容 dict 包装与裸 list）
        if isinstance(input_data, dict) and "transactions" in input_data:
            raw_txs = input_data["transactions"]
        elif isinstance(input_data, list):
            raw_txs = input_data
        else:
            raw_txs = []

        cleaned = []
        for i, t in enumerate(raw_txs):
            if not isinstance(t, dict):
                continue
            amt = _parse_amount(t.get("amount"))
            tx_date = _parse_date(t.get("date") or t.get("tx_date"))
            hour = _parse_hour(t.get("time") or t.get("tx_time"))
            counterparty = _normalize_name(
                t.get("counterparty") or t.get("party")
            )
            cleaned.append({
                "tx_id": str(
                    t.get("tx_id") or t.get("id") or f"TX{i + 1:04d}"
                ),
                "amount": amt,
                "tx_date": tx_date.isoformat() if tx_date else None,
                "hour": hour,
                "counterparty": counterparty,
                "counterparty_address": _normalize_name(
                    t.get("counterparty_address") or t.get("address")
                ),
                "counterparty_phone": _normalize_name(
                    t.get("counterparty_phone") or t.get("phone")
                ),
                "counterparty_legal_rep": _normalize_name(
                    t.get("counterparty_legal_rep") or t.get("legal_rep")
                ),
                "account_id": str(t.get("account_id", "")),
                "description": str(t.get("description", "")),
                "is_related_party": bool(t.get("is_related_party", False)),
                "tx_type": str(t.get("tx_type", "transfer")),
            })
        return {"transactions": cleaned}

    # ------------------------------------------------------------------
    # 推理（四层扫描）
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """执行四层扫描：统计层 + 无监督 + 监督 + 图谱。"""
        txs = prepared["transactions"]
        n = len(txs)

        # 每交易命中标记
        flags: dict[str, dict] = {
            t["tx_id"]: {
                "statistical": False,
                "unsupervised": False,
                "supervised": [],          # pattern_id 列表
                "supervised_details": [],   # 含权重的模式详情
                "graph": False,
                "evidence_chain": [],
            }
            for t in txs
        }
        layer_results: dict[str, Any] = {}

        # === 第一层：统计层（Benford + Z-score + IQR）===
        layer_results["statistical"] = self._scan_statistical(txs, flags)

        # === 第二层：无监督 ML 层（Isolation Forest 模拟 + 重构误差）===
        layer_results["unsupervised"] = self._scan_unsupervised(txs, flags)

        # === 第三层：监督 ML 层（规则匹配）===
        layer_results["supervised"] = self._scan_supervised(txs, flags)

        # === 第四层：知识图谱层（隐藏关联）===
        layer_results["graph"] = self._scan_graph(txs, flags)

        return {
            "transactions": txs,
            "layer_results": layer_results,
            "flags": flags,
            "total_transactions": n,
        }

    # ------------------------------------------------------------------
    # 第一层：统计层
    # ------------------------------------------------------------------
    def _scan_statistical(self, txs: list[dict],
                          flags: dict[str, dict]) -> dict:
        """Benford 定律卡方检验 + Z-Score + IQR 异常检测。"""
        amounts = [t["amount"] for t in txs if t["amount"] > 0]
        n = len(amounts)
        result: dict[str, Any] = {
            "benford": {}, "z_score": {}, "iqr": {},
        }
        if n == 0:
            return result

        # --- Benford 卡方检验（整体层面）---
        expected = self.model["benford_expected"]
        first_digits = [int(str(int(a))[0]) for a in amounts if a > 0]
        observed = {d: first_digits.count(d) for d in range(1, 10)}
        chi_square = 0.0
        for d in range(1, 10):
            exp_count = expected[d] * n
            chi_square += (observed[d] - exp_count) ** 2 / max(exp_count, 0.01)
        is_benford_anomaly = chi_square > self.model["benford_critical"]

        # 每交易 Benford 偏离：该首位数字在整体分布中过度代表（比例 > 1.5）
        per_digit_ratio = {}
        for d in range(1, 10):
            exp_count = expected[d] * n
            per_digit_ratio[d] = observed[d] / max(exp_count, 0.01)

        benford_flagged = []
        if is_benford_anomaly:
            for t in txs:
                a = t["amount"]
                if a <= 0:
                    continue
                d = int(str(int(a))[0])
                ratio = per_digit_ratio.get(d, 0)
                if ratio > 1.5:
                    flags[t["tx_id"]]["statistical"] = True
                    flags[t["tx_id"]]["evidence_chain"].append(
                        f"Benford首位数字{d}过度代表(比例{ratio:.2f})"
                    )
                    benford_flagged.append(t["tx_id"])

        result["benford"] = {
            "chi_square": round(chi_square, 2),
            "critical_value": self.model["benford_critical"],
            "is_anomaly": is_benford_anomaly,
            "expected": {
                str(d): round(expected[d], 4) for d in range(1, 10)
            },
            "observed": {str(d): observed[d] for d in range(1, 10)},
            "per_digit_ratio": {
                str(d): round(per_digit_ratio[d], 2) for d in range(1, 10)
            },
            "flagged_tx_ids": benford_flagged,
        }

        # --- Z-Score 异常检测 ---
        mean = sum(amounts) / n
        variance = sum((a - mean) ** 2 for a in amounts) / n
        std = math.sqrt(variance) if variance > 0 else 1.0
        z_thresh = self.model["z_threshold"]
        z_flagged = []
        for t in txs:
            a = t["amount"]
            if a <= 0 or std <= 0:
                continue
            z = (a - mean) / std
            if abs(z) > z_thresh:
                flags[t["tx_id"]]["statistical"] = True
                flags[t["tx_id"]]["evidence_chain"].append(
                    f"Z-Score={z:.2f}(>{z_thresh})"
                )
                z_flagged.append(t["tx_id"])
        result["z_score"] = {
            "mean": round(mean, 2),
            "std": round(std, 2),
            "threshold": z_thresh,
            "flagged_tx_ids": z_flagged,
        }

        # --- IQR 异常检测 ---
        sorted_amt = sorted(amounts)
        q1 = self._percentile(sorted_amt, 25)
        q3 = self._percentile(sorted_amt, 75)
        iqr = q3 - q1
        multiplier = self.model["iqr_multiplier"]
        lower = q1 - multiplier * iqr
        upper = q3 + multiplier * iqr
        iqr_flagged = []
        for t in txs:
            a = t["amount"]
            if a <= 0:
                continue
            if a < lower or a > upper:
                flags[t["tx_id"]]["statistical"] = True
                side = "上界" if a > upper else "下界"
                flags[t["tx_id"]]["evidence_chain"].append(
                    f"IQR异常({side}越界,范围[{lower:.0f},{upper:.0f}])"
                )
                iqr_flagged.append(t["tx_id"])
        result["iqr"] = {
            "q1": round(q1, 2),
            "q3": round(q3, 2),
            "iqr": round(iqr, 2),
            "lower_bound": round(lower, 2),
            "upper_bound": round(upper, 2),
            "multiplier": multiplier,
            "flagged_tx_ids": iqr_flagged,
        }
        return result

    @staticmethod
    def _percentile(sorted_list: list[float], p: float) -> float:
        """计算百分位数（线性插值法）。"""
        if not sorted_list:
            return 0.0
        k = (len(sorted_list) - 1) * p / 100.0
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return float(sorted_list[int(k)])
        return sorted_list[f] * (c - k) + sorted_list[c] * (k - f)

    # ------------------------------------------------------------------
    # 第二层：无监督 ML 层（Isolation Forest 模拟 + 重构误差）
    # ------------------------------------------------------------------
    def _scan_unsupervised(self, txs: list[dict],
                           flags: dict[str, dict]) -> dict:
        """模拟 Isolation Forest：随机选特征+随机切分点算路径深度。

        路径越短 = 越异常（异常点更容易被孤立）。
        重构误差代理：与特征中心点的标准化欧氏距离。
        """
        result: dict[str, Any] = {
            "iso_forest": {"flagged_tx_ids": []},
            "reconstruction_error": {"flagged_tx_ids": []},
        }
        if len(txs) < 8:
            # 样本太少，iForest 无统计意义
            return result

        # 构建特征矩阵（标准化）
        features, feat_names = self._extract_features(txs)
        n = len(features)
        normalized = self._standardize_features(features)
        m = len(feat_names)

        # --- Isolation Forest 模拟 ---
        rng = random.Random(self.model["random_seed"])
        n_trees = self.model["iso_forest"]["n_trees"]
        max_depth = self.model["iso_forest"]["max_depth"]
        sample_size = min(self.model["iso_forest"]["sample_size"], n)

        path_lengths: dict[str, float] = {
            txs[i]["tx_id"]: 0.0 for i in range(n)
        }
        for _ in range(n_trees):
            indices = rng.sample(range(n), sample_size)
            sample = [normalized[i] for i in indices]
            sample_ids = [txs[i]["tx_id"] for i in indices]
            tree_paths = self._build_iso_tree(sample, max_depth, m, rng)
            for sid, p in zip(sample_ids, tree_paths):
                path_lengths[sid] += p

        avg_paths = {
            tid: p / n_trees for tid, p in path_lengths.items() if p > 0
        }
        # 异常评分 s = 2^(-E(h)/c(n))
        c_n = self._avg_path_length_unsucceeded(sample_size)
        anomaly_scores = {}
        for tid, h in avg_paths.items():
            s = 2 ** (-(h / c_n)) if c_n > 0 else 0.5
            anomaly_scores[tid] = round(s, 4)

        # 标记异常：评分 > 0.65 或 Top 5% 最高评分
        if anomaly_scores:
            scores_sorted = sorted(
                anomaly_scores.values(), reverse=True
            )
            top_k = max(1, int(len(scores_sorted) * 0.05))
            top_threshold = scores_sorted[top_k - 1]
        else:
            top_threshold = 1.0
        iso_flagged = []
        for tid, s in anomaly_scores.items():
            if s > 0.65 or s >= top_threshold:
                flags[tid]["unsupervised"] = True
                flags[tid]["evidence_chain"].append(
                    f"iForest异常评分={s:.2f}(路径深度{avg_paths[tid]:.2f})"
                )
                iso_flagged.append(tid)
        result["iso_forest"] = {
            "n_trees": n_trees,
            "sample_size": sample_size,
            "anomaly_scores": anomaly_scores,
            "flagged_tx_ids": iso_flagged,
        }

        # --- 重构误差代理：与中心的标准化欧氏距离 ---
        centroid = [sum(col) / n for col in zip(*normalized)]
        recon_errors = {}
        for i, t in enumerate(txs):
            tid = t["tx_id"]
            d = math.sqrt(
                sum(
                    (normalized[i][k] - centroid[k]) ** 2
                    for k in range(len(centroid))
                )
            )
            recon_errors[tid] = round(d, 4)

        if recon_errors:
            recon_sorted = sorted(recon_errors.values(), reverse=True)
            recon_k = max(1, int(len(recon_sorted) * 0.10))
            recon_threshold = recon_sorted[recon_k - 1]
        else:
            recon_threshold = 0.0
        recon_flagged = []
        for tid, e in recon_errors.items():
            if e >= recon_threshold and e > 0:
                flags[tid]["unsupervised"] = True
                flags[tid]["evidence_chain"].append(
                    f"重构误差={e:.2f}(>90%分位)"
                )
                recon_flagged.append(tid)
        result["reconstruction_error"] = {
            "errors": recon_errors,
            "threshold_90": round(recon_threshold, 4),
            "flagged_tx_ids": recon_flagged,
        }
        return result

    @staticmethod
    def _extract_features(txs: list[dict]) -> tuple[list[list[float]], list[str]]:
        """提取数值特征向量（用于 iForest 与重构误差）。"""
        names = [
            "amount_log", "hour", "day_of_month", "month",
            "is_integer", "is_weekend", "is_related",
        ]
        feats = []
        for t in txs:
            amt = t["amount"]
            amount_log = math.log10(amt + 1) if amt > 0 else 0.0
            hour = float(t.get("hour") or 12)  # 缺失用中午
            tx_date_str = t.get("tx_date")
            day_of_month = 15.0
            month = 6.0
            is_weekend = 0.0
            if tx_date_str:
                try:
                    d = date.fromisoformat(tx_date_str)
                    day_of_month = float(d.day)
                    month = float(d.month)
                    is_weekend = 1.0 if d.weekday() >= 5 else 0.0
                except ValueError:
                    pass
            is_integer = 1.0 if (amt == round(amt) and amt > 0) else 0.0
            is_related = 1.0 if t.get("is_related_party") else 0.0
            feats.append([
                amount_log, hour, day_of_month, month,
                is_integer, is_weekend, is_related,
            ])
        return feats, names

    @staticmethod
    def _standardize_features(features: list[list[float]]) -> list[list[float]]:
        """Z-Score 标准化每个特征列。"""
        if not features:
            return []
        n = len(features)
        m = len(features[0])
        means = [0.0] * m
        stds = [1.0] * m
        for j in range(m):
            col = [features[i][j] for i in range(n)]
            mu = sum(col) / n
            var = sum((x - mu) ** 2 for x in col) / n
            means[j] = mu
            stds[j] = math.sqrt(var) if var > 0 else 1.0
        return [
            [
                (features[i][j] - means[j]) / stds[j] if stds[j] > 0 else 0.0
                for j in range(m)
            ]
            for i in range(n)
        ]

    def _build_iso_tree(self, sample: list[list[float]], max_depth: int,
                        m: int, rng: random.Random) -> list[float]:
        """构建一棵 isolation tree，返回每个样本的路径深度。

        用栈模拟递归二叉切分：随机选特征 + 随机切分点。
        """
        n = len(sample)
        paths = [0.0] * n
        if n == 0 or m == 0:
            return paths
        # 每个样本的当前索引集 → 跟踪路径深度
        stack: list[tuple[list[int], int]] = [(list(range(n)), 0)]
        while stack:
            indices, depth = stack.pop()
            if len(indices) <= 1 or depth >= max_depth:
                for i in indices:
                    paths[i] = float(depth)
                continue
            # 随机选特征
            feat_idx = rng.randint(0, m - 1)
            col = [sample[i][feat_idx] for i in indices]
            cmin, cmax = min(col), max(col)
            if cmin == cmax:
                for i in indices:
                    paths[i] = float(depth)
                continue
            # 随机切分点
            split = rng.uniform(cmin, cmax)
            left, right = [], []
            for i in indices:
                if sample[i][feat_idx] < split:
                    left.append(i)
                else:
                    right.append(i)
            if not left or not right:
                for i in indices:
                    paths[i] = float(depth)
                continue
            stack.append((left, depth + 1))
            stack.append((right, depth + 1))
        return paths

    @staticmethod
    def _avg_path_length_unsucceeded(n: int) -> float:
        """iForest 的 c(n) 调整函数：未成功搜索的平均路径长度。"""
        if n <= 1:
            return 0.0
        if n == 2:
            return 1.0
        return 2.0 * (math.log(n - 1) + 0.5772156649015329) - 2.0 * (n - 1) / n

    # ------------------------------------------------------------------
    # 第三层：监督 ML 层（规则匹配）
    # ------------------------------------------------------------------
    def _scan_supervised(self, txs: list[dict],
                         flags: dict[str, dict]) -> dict:
        """规则匹配历史舞弊模式（基于 fraud_patterns 库）。"""
        patterns = self.model["fraud_patterns"]
        matched: dict[str, list[dict]] = {t["tx_id"]: [] for t in txs}
        for pattern in patterns:
            conditions = pattern.get("conditions", {}) or {}
            for t in txs:
                if self._match_pattern(t, conditions):
                    detail = {
                        "pattern_id": pattern["pattern_id"],
                        "name": pattern["name"],
                        "weight": float(pattern.get("weight", 0.5)),
                    }
                    matched[t["tx_id"]].append(detail)
                    flags[t["tx_id"]]["supervised"].append(
                        pattern["pattern_id"]
                    )
                    flags[t["tx_id"]]["supervised_details"].append(detail)
                    flags[t["tx_id"]]["evidence_chain"].append(
                        f"命中规则:{pattern['name']}({pattern['pattern_id']})"
                    )
        flagged_tx_ids = [tid for tid, ms in matched.items() if ms]
        return {
            "patterns_loaded": len(patterns),
            "matched": matched,
            "flagged_tx_ids": flagged_tx_ids,
        }

    @staticmethod
    def _match_pattern(t: dict, conditions: dict) -> bool:
        """评估单条规则是否命中交易 t。所有条件 AND 组合。

        支持的条件键：
          month / month_in / day_min / day_max
          hour_min / hour_max / hour_outside [low, high]
          amount_min / amount_max / amount_is_integer
          amount_first_digit_in / amount_multiple_of
          is_related_party / tx_type / tx_type_in
        """
        if not conditions:
            return False
        # 月份
        if "month" in conditions:
            if _extract_month(t) != conditions["month"]:
                return False
        if "month_in" in conditions:
            if _extract_month(t) not in conditions["month_in"]:
                return False
        # 日
        if "day_min" in conditions:
            d = _extract_day(t)
            if d is None or d < conditions["day_min"]:
                return False
        if "day_max" in conditions:
            d = _extract_day(t)
            if d is None or d > conditions["day_max"]:
                return False
        # 小时
        if "hour_min" in conditions:
            h = t.get("hour")
            if h is None or h < conditions["hour_min"]:
                return False
        if "hour_max" in conditions:
            h = t.get("hour")
            if h is None or h > conditions["hour_max"]:
                return False
        if "hour_outside" in conditions:
            h = t.get("hour")
            if h is None:
                return False
            low, high = conditions["hour_outside"]
            if low <= h <= high:
                return False
        # 金额
        amt = t["amount"]
        if "amount_min" in conditions and amt < conditions["amount_min"]:
            return False
        if "amount_max" in conditions and amt > conditions["amount_max"]:
            return False
        if conditions.get("amount_is_integer") and not (
            amt == round(amt) and amt > 0
        ):
            return False
        if "amount_first_digit_in" in conditions:
            if amt <= 0:
                return False
            d = int(str(int(amt))[0])
            if d not in conditions["amount_first_digit_in"]:
                return False
        if "amount_multiple_of" in conditions:
            mod = conditions["amount_multiple_of"]
            if mod <= 0 or amt % mod != 0:
                return False
        # 关联方
        if conditions.get("is_related_party") and not t.get("is_related_party"):
            return False
        # 交易类型
        if "tx_type" in conditions and t.get("tx_type") != conditions["tx_type"]:
            return False
        if "tx_type_in" in conditions and t.get("tx_type") not in conditions["tx_type_in"]:
            return False
        return True

    # ------------------------------------------------------------------
    # 第四层：知识图谱层
    # ------------------------------------------------------------------
    def _scan_graph(self, txs: list[dict],
                    flags: dict[str, dict]) -> dict:
        """构建交易对手网络（dict+set），发现共享地址/电话/法人的隐藏关联。"""
        # 节点：counterparty → 属性
        nodes: dict[str, dict] = {}
        # 属性倒排索引：属性值 → 交易对手集合
        addr_index: dict[str, set[str]] = defaultdict(set)
        phone_index: dict[str, set[str]] = defaultdict(set)
        legal_index: dict[str, set[str]] = defaultdict(set)

        for t in txs:
            cp = t["counterparty"]
            if not cp:
                continue
            nodes.setdefault(cp, {
                "address": t.get("counterparty_address") or "",
                "phone": t.get("counterparty_phone") or "",
                "legal_rep": t.get("counterparty_legal_rep") or "",
                "tx_count": 0,
            })
            nodes[cp]["tx_count"] += 1
            addr = (t.get("counterparty_address") or "").strip()
            phone = (t.get("counterparty_phone") or "").strip()
            legal = (t.get("counterparty_legal_rep") or "").strip()
            if addr:
                addr_index[addr].add(cp)
            if phone:
                phone_index[phone].add(cp)
            if legal:
                legal_index[legal].add(cp)

        # 发现共享同一属性的 ≥2 个不同对手
        hidden_links = []
        linked_parties: set[str] = set()
        for addr, parties in addr_index.items():
            if len(parties) >= 2:
                hidden_links.append({
                    "type": "shared_address",
                    "value": addr,
                    "entities": sorted(parties),
                })
                linked_parties.update(parties)
        for phone, parties in phone_index.items():
            if len(parties) >= 2:
                hidden_links.append({
                    "type": "shared_phone",
                    "value": phone,
                    "entities": sorted(parties),
                })
                linked_parties.update(parties)
        for legal, parties in legal_index.items():
            if len(parties) >= 2:
                hidden_links.append({
                    "type": "shared_legal_rep",
                    "value": legal,
                    "entities": sorted(parties),
                })
                linked_parties.update(parties)

        # 标记涉及隐藏关联的交易
        flagged_tx_ids = []
        for t in txs:
            cp = t["counterparty"]
            if cp in linked_parties:
                flags[t["tx_id"]]["graph"] = True
                link_types = [
                    link["type"] for link in hidden_links
                    if cp in link["entities"]
                ]
                flags[t["tx_id"]]["evidence_chain"].append(
                    f"图谱隐藏关联({','.join(link_types)})对手:{cp}"
                )
                flagged_tx_ids.append(t["tx_id"])

        return {
            "node_count": len(nodes),
            "edge_count": sum(n["tx_count"] for n in nodes.values()),
            "hidden_links": hidden_links,
            "linked_parties": sorted(linked_parties),
            "flagged_tx_ids": flagged_tx_ids,
        }

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """汇总舞弊评分（各层命中加权）+ 风险分级 + 可疑交易列表 + 统计。"""
        txs = result["transactions"]
        flags = result["flags"]
        weights = self.model["layer_weights"]

        suspicious = []
        layer_hit_counts = {
            "statistical": 0, "unsupervised": 0,
            "supervised": 0, "graph": 0,
        }
        for t in txs:
            tid = t["tx_id"]
            f = flags[tid]
            # 各层命中贡献
            stat_hit = 1.0 if f["statistical"] else 0.0
            unsup_hit = 1.0 if f["unsupervised"] else 0.0
            # 监督层：取命中规则的最大权重作为贡献
            sup_details = f.get("supervised_details", [])
            sup_hit = max((p["weight"] for p in sup_details), default=0.0)
            graph_hit = 1.0 if f["graph"] else 0.0

            # 加权评分
            risk_score = (
                stat_hit * weights["statistical"]
                + unsup_hit * weights["unsupervised"]
                + sup_hit * weights["supervised"]
                + graph_hit * weights["graph"]
            )
            risk_score = round(min(risk_score, 1.0), 4)

            # 命中层列表
            hit_layers = []
            if f["statistical"]:
                hit_layers.append("statistical")
                layer_hit_counts["statistical"] += 1
            if f["unsupervised"]:
                hit_layers.append("unsupervised")
                layer_hit_counts["unsupervised"] += 1
            if sup_details:
                hit_layers.append("supervised")
                layer_hit_counts["supervised"] += 1
            if f["graph"]:
                hit_layers.append("graph")
                layer_hit_counts["graph"] += 1

            # 默认风险分级（custom_thresholds 可覆盖）
            if risk_score >= 0.8:
                risk_level = "high"
            elif risk_score >= 0.5:
                risk_level = "medium"
            else:
                risk_level = "low"

            # 仅记录有命中的交易为可疑
            if hit_layers:
                suspicious.append({
                    "tx_id": tid,
                    "amount": t["amount"],
                    "tx_date": t.get("tx_date"),
                    "hour": t.get("hour"),
                    "counterparty": t["counterparty"],
                    "is_related_party": t.get("is_related_party", False),
                    "tx_type": t.get("tx_type"),
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "hit_layers": hit_layers,
                    "matched_patterns": [
                        {"pattern_id": p["pattern_id"], "name": p["name"],
                         "weight": p["weight"]}
                        for p in sup_details
                    ],
                    "evidence_chain": f["evidence_chain"],
                })

        suspicious.sort(key=lambda x: x["risk_score"], reverse=True)
        total = len(txs)
        suspicious_count = len(suspicious)
        risk_dist = {
            "high": sum(1 for s in suspicious if s["risk_level"] == "high"),
            "medium": sum(1 for s in suspicious if s["risk_level"] == "medium"),
            "low": sum(1 for s in suspicious if s["risk_level"] == "low"),
        }
        result["suspicious_transactions"] = suspicious
        result["statistics"] = {
            "total_transactions": total,
            "suspicious_count": suspicious_count,
            "coverage_rate": 1.0,  # 全量扫描覆盖率 100%
            "suspicious_rate": round(
                suspicious_count / max(total, 1), 4
            ),
            "layer_hit_counts": layer_hit_counts,
            "risk_distribution": risk_dist,
        }
        return result

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def close(self) -> None:
        """关闭 PortableDB 连接。"""
        if self.db is not None:
            self.db.close()
            self.db = None
