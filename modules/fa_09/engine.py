from typing import Any, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import re, math, json, hashlib
from difflib import SequenceMatcher

from modules.shared.base_engine import AbstractEngine


class LLMEngine(AbstractEngine):
    """FA-09 AI底稿质量复核助手。

    算法维度：
      1) 完整性：必填项/必附凭证/必做程序是否覆盖；
      2) 准确性：数字勾稽、金额精度、借贷方向；
      3) 逻辑性：底稿内部计算链条、与上期衔接、期后事项处理；
      4) 合规性：审计准则条款命中情况、项目阶段应有的程序；
      5) 表达质量：文档结构、语言规范性、证据引用充分性。
    每项打分 0-100，加权平均。
    """

    WEIGHTS = {
        "completeness": 0.25,
        "accuracy": 0.25,
        "logic": 0.2,
        "compliance": 0.2,
        "quality": 0.1,
    }

    MANDATORY_FIELDS = {
        "bank": ["银行对账单", "余额调节表", "函证回函", "截止测试"],
        "ar": ["账龄分析", "函证控制表", "坏账准备测算", "期后回款"],
        "ap": ["账龄分析", "函证回函", "期后付款"],
        "inventory": ["盘点表", "监盘记录", "存货跌价测试", "截止测试"],
        "fa": ["折旧计算表", "盘点记录", "减值测试"],
        "revenue": ["收入确认政策", "截止测试", "毛利率分析", "期后退货"],
        "cost": ["成本结转表", "截止测试"],
        "equity": ["股东协议", "验资报告", "权益变动表"],
    }

    AUDIT_STANDARDS = [
        ("中国注册会计师审计准则第1131号", r"审计工作底稿.*完整性|归档要求"),
        ("中国注册会计师审计准则第1301号", r"审计证据.*充分性.*适当性"),
        ("中国注册会计师审计准则第1312号", r"函证.*控制|发函.*回函"),
        ("中国注册会计师审计准则第1401号", r"组成部分注册会计师|集团审计"),
        ("中国注册会计师审计准则第1101号", r"职业怀疑|职业判断"),
    ]

    def __init__(self, name: str = "fa_09") -> None:
        super().__init__(name)
        self._standards: List[Tuple[str, re.Pattern]] = []

    def _load_model(self) -> None:
        self._standards = [(name, re.compile(p, re.IGNORECASE)) for name, p in self.AUDIT_STANDARDS]

    def _preprocess(self, input_data: Any) -> Dict[str, Any]:
        data = input_data or {}
        if not isinstance(data, dict):
            data = {"workpapers": data}
        wps = data.get("workpapers", data.get("底稿", []))
        if not isinstance(wps, list):
            wps = [wps]
        normalized = []
        for w in wps:
            if not isinstance(w, dict):
                continue
            normalized.append({
                "wp_id": str(w.get("id", w.get("wp_id", hashlib.md5(json.dumps(w, default=str).encode()).hexdigest()[:8]))),
                "wp_type": str(w.get("type", w.get("类别", "other"))),
                "subject": str(w.get("subject", w.get("科目", ""))),
                "title": str(w.get("title", w.get("标题", ""))),
                "content": str(w.get("content", w.get("正文", ""))),
                "fields": w.get("fields", w.get("字段", {})),
                "amounts": w.get("amounts", w.get("金额", {})),
                "procedures": w.get("procedures", w.get("程序", [])),
                "evidences": w.get("evidences", w.get("证据", [])),
                "conclusion": str(w.get("conclusion", w.get("结论", ""))),
                "reviewer_notes": w.get("reviewer_notes", []),
            })
        return {"workpapers": normalized, "context": data.get("context", {})}

    def _infer(self, prepared: Any) -> Any:
        wps = prepared.get("workpapers", [])
        results = []
        for wp in wps:
            scores = self._score_dimensions(wp)
            overall = round(sum(scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS), 1)
            issues = self._find_issues(wp, scores)
            results.append({
                "wp_id": wp["wp_id"],
                "wp_type": wp["wp_type"],
                "title": wp["title"],
                "dimension_scores": scores,
                "overall_score": overall,
                "grade": self._grade(overall),
                "issues": issues,
                "compliance_hits": self._standard_hits(wp["content"] + wp["title"] + " ".join(wp["procedures"])),
                "compliance_rate": round(len(self._standard_hits(wp["content"] + wp["title"] + " ".join(wp["procedures"]))) / max(1, len(self._standards)), 2),
            })
        return results

    def _postprocess(self, result: Any) -> Any:
        items = result or []
        if not isinstance(items, list):
            items = []
        overall_list = [i["overall_score"] for i in items]
        avg_overall = round(sum(overall_list) / max(1, len(overall_list)), 1)
        grade_dist = Counter(i["grade"] for i in items)
        all_issues = []
        for i in items:
            for iss in i["issues"]:
                iss["wp_id"] = i["wp_id"]
                all_issues.append(iss)
        return {
            "items": items,
            "summary": {
                "total_workpapers": len(items),
                "average_score": avg_overall,
                "grade_distribution": dict(grade_dist),
                "total_issues": len(all_issues),
                "critical_issues_count": sum(1 for iss in all_issues if iss["severity"] == "critical"),
                "major_issues_count": sum(1 for iss in all_issues if iss["severity"] == "major"),
            },
            "critical_issues": [iss for iss in all_issues if iss["severity"] == "critical"],
            "improvement_tips": self._improvement_tips(all_issues),
        }

    # ── 评分维度 ─────────────────────────────────────────────────────────────
    def _score_dimensions(self, wp: Dict[str, Any]) -> Dict[str, float]:
        return {
            "completeness": self._completeness_score(wp),
            "accuracy": self._accuracy_score(wp),
            "logic": self._logic_score(wp),
            "compliance": self._compliance_score(wp),
            "quality": self._quality_score(wp),
        }

    def _completeness_score(self, wp: Dict[str, Any]) -> float:
        wp_type = wp["wp_type"]
        content = wp["content"]
        title = wp["title"]
        fields_text = " ".join(str(v) for v in wp["fields"].values()) if isinstance(wp["fields"], dict) else str(wp["fields"])
        mandatory = self.MANDATORY_FIELDS.get(wp_type, self.MANDATORY_FIELDS.get("bank", []))
        hit = sum(1 for m in mandatory if m in content or m in title or m in fields_text)
        if not mandatory:
            return 80.0
        base = min(100.0, 60 + 40 * (hit / len(mandatory)))
        # 证据数
        ev_count = len(wp["evidences"]) if isinstance(wp["evidences"], list) else 0
        if ev_count < 2:
            base -= 10
        return max(0.0, min(100.0, base))

    def _accuracy_score(self, wp: Dict[str, Any]) -> float:
        score = 80.0
        amounts = wp["amounts"] if isinstance(wp["amounts"], dict) else {}
        debits = float(amounts.get("debit", amounts.get("借方", 0)) or 0)
        credits = float(amounts.get("credit", amounts.get("贷方", 0)) or 0)
        if debits and credits and abs(debits - credits) > 0.01:
            score -= 30
        # 精度检查
        text = wp["content"]
        decimals = len(re.findall(r"\d+\.\d{3,}", text))
        if decimals > 5:
            score -= 10
        # 负数金额描述矛盾
        if "元" in text or "人民币" in text:
            bad = re.findall(r"-\d+\.\d{2}", text)
            if bad:
                score -= 5
        return max(0.0, min(100.0, score))

    def _logic_score(self, wp: Dict[str, Any]) -> float:
        score = 75.0
        content = wp["content"]
        if not wp["conclusion"]:
            score -= 25
        # 结论与程序匹配
        if wp["procedures"]:
            proc_text = " ".join(wp["procedures"]) if isinstance(wp["procedures"], list) else str(wp["procedures"])
            if not any(k in content for k in proc_text.split()[:3]):
                score -= 10
        # 期后事项
        if "期后" in content and "截止" not in content and "日后" not in content:
            score -= 8
        return max(0.0, min(100.0, score))

    def _compliance_score(self, wp: Dict[str, Any]) -> float:
        full_text = wp["content"] + wp["title"] + " ".join(wp["procedures"])
        hits = self._standard_hits(full_text)
        rate = len(hits) / max(1, len(self._standards))
        return min(100.0, 50 + 50 * rate)

    def _quality_score(self, wp: Dict[str, Any]) -> float:
        score = 85.0
        content = wp["content"]
        # 格式标记
        if re.search(r"[♥★◎★◆▲]", content):
            score -= 10
        # 过长句子
        sentences = re.split(r"[。！？]", content)
        long_sent = sum(1 for s in sentences if len(s) > 80)
        if long_sent > 3:
            score -= 10
        # 错别字启发式（简化）
        typos = ["的的", "了了", "是是"]
        for t in typos:
            if t in content:
                score -= 3
        # 结论空洞
        if wp["conclusion"] and len(wp["conclusion"]) < 10:
            score -= 10
        return max(0.0, min(100.0, score))

    # ── 其他辅助 ──────────────────────────────────────────────────────────────
    def _standard_hits(self, text: str) -> List[str]:
        hits = []
        for name, pat in self._standards:
            if pat.search(text):
                hits.append(name)
        return hits

    def _grade(self, score: float) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    def _find_issues(self, wp: Dict[str, Any], scores: Dict[str, float]) -> List[Dict[str, Any]]:
        issues = []
        dim_map = {
            "completeness": "完整性",
            "accuracy": "准确性",
            "logic": "逻辑性",
            "compliance": "合规性",
            "quality": "表达质量",
        }
        for dim, s in scores.items():
            if s < 60:
                issues.append({
                    "dimension": dim,
                    "dimension_cn": dim_map.get(dim, dim),
                    "severity": "critical" if s < 40 else "major",
                    "score": s,
                    "issue": f"{dim_map.get(dim, dim)}严重不足（{s}分）",
                    "suggestion": self._suggest(dim, wp),
                })
            elif s < 75:
                issues.append({
                    "dimension": dim,
                    "dimension_cn": dim_map.get(dim, dim),
                    "severity": "minor",
                    "score": s,
                    "issue": f"{dim_map.get(dim, dim)}待加强（{s}分）",
                    "suggestion": self._suggest(dim, wp),
                })
        return issues

    def _suggest(self, dim: str, wp: Dict[str, Any]) -> str:
        if dim == "completeness":
            return f"补充 {self.MANDATORY_FIELDS.get(wp['wp_type'], [])}"
        if dim == "accuracy":
            return "复核借贷平衡与金额精度"
        if dim == "logic":
            return "补充明确的审计结论并链接至程序"
        if dim == "compliance":
            return "在底稿中显式引用审计准则条款"
        if dim == "quality":
            return "精简长句、修正格式标记"
        return ""

    def _improvement_tips(self, all_issues: List[Dict[str, Any]]) -> List[str]:
        tips = []
        by_dim = defaultdict(list)
        for iss in all_issues:
            by_dim[iss["dimension_cn"]].append(iss["suggestion"])
        for dim, sugg in by_dim.items():
            uniq = list(dict.fromkeys(sugg))[:3]
            tips.append(f"【{dim}】" + "；".join(uniq))
        return tips
