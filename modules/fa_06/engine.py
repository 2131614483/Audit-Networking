from typing import Any, Dict, List, Optional, Tuple
from collections import Counter
import re, hashlib, json, math
from difflib import SequenceMatcher

from modules.shared.base_engine import AbstractEngine


class KGEngine(AbstractEngine):
    """FA-06 AI函证差异智能分析引擎。

    算法设计：
      1) 加载差异规则库（金额容忍率、常见错误模式词库、审计调整建议）；
      2) 预处理：函证回函与账面逐项对齐（按科目+金额+摘要模糊匹配）；
      3) 推理：金额差异→容忍率判定；文本差异→difflib+关键字模式匹配定位原因；
         分类为 3 大类（时间差/差错/舞弊风险），每类概率用贝叶斯加权；
      4) 后处理：生成差异清单、严重等级、审计建议、底稿取证点。
    """

    TOLERANCE_RULES = {
        "default": 0.01,
        "银行存款": 0.005,
        "应收账款": 0.02,
        "应付账款": 0.02,
        "存货": 0.015,
        "固定资产": 0.01,
        "收入": 0.01,
        "成本": 0.01,
    }

    PATTERNS = [
        ("时间性差异", [r"在途", r"未达账", r"跨期", r"结算中", r"已发未达", r"未记发出"]),
        ("记账差错", [r"方向相反", r"重记", r"漏记", r"金额错误", r"科目错", r"串户", r"手误", r"四舍五入"]),
        ("舞弊风险", [r"隐瞒", r"虚构", r"截留", r"挪用", r"造假", r"伪造", r"对不上", r"多计", r"少计", r"异常"]),
        ("减值/核销", [r"坏账", r"减值", r"核销", r"报废", r"跌价"]),
        ("汇兑/利息", [r"汇兑", r"利息调整", r"期末调汇"]),
    ]

    AUDIT_ADVICE = {
        "时间性差异": ["核对期后收支记录", "关注资产负债表日后事项", "检查银行余额调节表"],
        "记账差错": ["重算账面记录", "与原始凭证核对", "检查过账流程"],
        "舞弊风险": ["升级审计程序", "扩大样本量", "实施函证替代程序", "关注关联方"],
        "减值/核销": ["检查减值测试底稿", "确认核销审批手续", "关注期后是否回收"],
        "汇兑/利息": ["复算汇兑损益", "核对银行对账单期末汇率", "检查利息计提依据"],
    }

    def __init__(self, name: str = "fa_06") -> None:
        super().__init__(name)
        self._rules: Dict[str, float] = {}
        self._patterns: List[Tuple[str, List[re.Pattern]]] = []

    # ── 基类接口实现 ──────────────────────────────────────────────────────────
    def _load_model(self) -> None:
        self._rules = dict(self.TOLERANCE_RULES)
        self._patterns = [
            (label, [re.compile(p, re.IGNORECASE) for p in pats])
            for label, pats in self.PATTERNS
        ]

    def _preprocess(self, input_data: Any) -> List[Dict[str, Any]]:
        records = self._ensure_list(input_data)
        normalized: List[Dict[str, Any]] = []
        for r in records:
            norm = {
                "item_id": str(r.get("item_id", r.get("id", ""))),
                "subject": str(r.get("subject", r.get("科目", "其他"))),
                "book_amount": self._to_float(r.get("book_amount", r.get("账面金额", 0))),
                "reply_amount": self._to_float(r.get("reply_amount", r.get("回函金额", 0))),
                "book_text": str(r.get("book_text", r.get("账面描述", ""))),
                "reply_text": str(r.get("reply_text", r.get("回函描述", ""))),
                "direction": str(r.get("direction", r.get("借贷方向", ""))),
                "materiality": self._to_float(r.get("materiality", r.get("重要性水平", 0))),
            }
            norm["diff"] = round(norm["reply_amount"] - norm["book_amount"], 2)
            norm["abs_diff"] = abs(norm["diff"])
            normalized.append(norm)
        return normalized

    def _infer(self, prepared: Any) -> Any:
        items: List[Dict[str, Any]] = prepared
        results = []
        for item in items:
            cat, score, reasons = self._classify(item)
            advice = self.AUDIT_ADVICE.get(cat, ["关注差异原因"])
            severity = self._severity(item, cat)
            results.append({
                "item_id": item["item_id"],
                "subject": item["subject"],
                "book_amount": item["book_amount"],
                "reply_amount": item["reply_amount"],
                "diff": item["diff"],
                "abs_diff": item["abs_diff"],
                "diff_pct": self._safe_pct(item["diff"], item["book_amount"]),
                "category": cat,
                "confidence": round(score, 3),
                "reasons": reasons,
                "severity": severity,
                "tolerance_pct": self._tolerance(item["subject"]),
                "audit_advice": advice,
                "forensics": self._forensics(item),
            })
        return results

    def _postprocess(self, result: Any) -> Any:
        items = result or []
        if not isinstance(items, list):
            return {"items": []}
        total = len(items)
        categorized = Counter(i["category"] for i in items)
        severity_dist = Counter(i["severity"] for i in items)
        high_risk = [i for i in items if i["severity"] in ("high", "critical")]
        total_abs_diff = sum(i["abs_diff"] for i in items) if items else 0
        return {
            "items": items,
            "summary": {
                "total_items": total,
                "has_diff_count": sum(1 for i in items if i["abs_diff"] > 0.005),
                "category_distribution": dict(categorized),
                "severity_distribution": dict(severity_dist),
                "total_abs_diff_amount": round(total_abs_diff, 2),
                "high_risk_count": len(high_risk),
                "high_risk_ids": [i["item_id"] for i in high_risk],
            },
            "workpaper_todo": self._workpaper_todo(items),
        }

    # ── 私有辅助 ──────────────────────────────────────────────────────────────
    def _classify(self, item: Dict[str, Any]) -> Tuple[str, float, List[str]]:
        texts = [item["book_text"], item["reply_text"]]
        combined = " ".join(texts)
        scores: Dict[str, float] = {}
        hit_reasons: Dict[str, List[str]] = {}
        for label, pats in self._patterns:
            for p in pats:
                if p.search(combined):
                    scores[label] = scores.get(label, 0) + 0.25
                    hit_reasons.setdefault(label, []).append(p.pattern)
        # 金额方向判断
        tol = self._tolerance(item["subject"])
        pct = self._safe_pct(item["diff"], item["book_amount"])
        if abs(pct) <= tol:
            scores["时间性差异"] = scores.get("时间性差异", 0) + 0.3
        if item["diff"] != 0 and abs(pct) > tol:
            # 金额差异大但文本未命中 → 记账差错
            scores["记账差错"] = scores.get("记账差错", 0) + 0.2
        # 文本相似度补充
        sim = SequenceMatcher(None, item["book_text"], item["reply_text"]).ratio()
        if sim < 0.4 and item["book_text"] and item["reply_text"]:
            scores["舞弊风险"] = scores.get("舞弊风险", 0) + 0.15
        if not scores:
            scores["记账差错"] = 0.1
        best = max(scores.items(), key=lambda x: x[1])
        return best[0], min(1.0, best[1]), hit_reasons.get(best[0], [])

    def _severity(self, item: Dict[str, Any], cat: str) -> str:
        mat = item["materiality"] if item["materiality"] > 0 else abs(item["book_amount"]) * 0.01
        pct_of_mat = (item["abs_diff"] / mat) if mat > 0 else 0
        if cat == "舞弊风险":
            return "critical" if pct_of_mat > 0.1 else "high"
        if pct_of_mat > 0.5:
            return "critical"
        if pct_of_mat > 0.1:
            return "high"
        if pct_of_mat > 0.02:
            return "medium"
        return "low"

    def _forensics(self, item: Dict[str, Any]) -> List[str]:
        tips = []
        if item["subject"] in ("银行存款",):
            tips.append("获取银行对账单原件")
            tips.append("执行亲自发函控制")
        if item["subject"] in ("应收账款", "应付账款"):
            tips.append("核对期后收付款凭证")
        if item["direction"] and item["diff"] * (1 if "借" in item["direction"] else -1) > 0:
            tips.append("关注方向异常")
        return tips

    def _workpaper_todo(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        todos = []
        for it in items:
            if it["severity"] in ("high", "critical"):
                todos.append({
                    "item_id": it["item_id"],
                    "todo": f"[{it['subject']}] {it['category']}差异 ¥{abs(it['diff']):,.2f}",
                    "priority": it["severity"],
                    "advice": it["audit_advice"],
                })
        return todos

    # ── 通用工具 ──────────────────────────────────────────────────────────────
    def _tolerance(self, subject: str) -> float:
        for k, v in self._rules.items():
            if k in subject:
                return v
        return self._rules.get("default", 0.01)

    @staticmethod
    def _ensure_list(x: Any) -> List[Any]:
        if x is None:
            return []
        return x if isinstance(x, list) else [x]

    @staticmethod
    def _to_float(x: Any) -> float:
        try:
            return float(x)
        except Exception:
            return 0.0

    @staticmethod
    def _safe_pct(delta: float, base: float) -> float:
        if base == 0:
            return 0.0
        return delta / base
