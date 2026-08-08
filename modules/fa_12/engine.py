from typing import Any, Dict, List, Optional, Tuple
from collections import Counter, defaultdict
import re, math, json, hashlib
from difflib import SequenceMatcher

from modules.shared.base_engine import AbstractEngine


class KGEngine(AbstractEngine):
    """FA-12 关联交易披露完整性检查。

    算法：
      1) 从"账簿/交易"侧识别关联交易（按关联方定义 + 交易类型分类）；
      2) 从"披露文本"侧抽取已披露的关联交易条目（正则+语义匹配）；
      3) 构建差集：应披露 - 已披露 = 未披露清单；
      4) 合规性检查：2023 版证监会《公开发行证券的公司信息披露内容与格式准则》的必填字段；
      5) 输出：完整性评分 + 缺失清单 + 补披露建议 + 风险等级。
    """

    DISCLOSURE_RULES = [
        ("identifier", "关联方名称/姓名", True, [r"名称", r"姓名", r"公司"]),
        ("relationship", "关联关系类型", True, [r"母公司", r"子公司", r"合营", r"联营", r"关联自然人", r"控股股东", r"董事"]),
        ("transaction_type", "交易类型", True, [r"采购", r"销售", r"担保", r"资金占用", r"资产转让", r"接受劳务", r"提供劳务", r"租赁"]),
        ("transaction_amount", "交易金额", True, [r"人民币.*元", r"交易金额", r"发生额", r"万元", r"元"]),
        ("outstanding_balance", "期末余额", True, [r"期末余额", r"应收账款", r"应付账款", r"其他应收款", r"其他应付款"]),
        ("pricing_policy", "定价政策", False, [r"定价", r"公允", r"协商", r"成本加成", r"市价"]),
        ("approval", "审批程序", False, [r"董事会", r"股东大会", r"关联董事回避", r"审议"]),
        ("impact", "对财务状况影响", False, [r"影响", r"利润", r"现金流", r"净资产"]),
    ]

    RELATED_PARTY_HINTS = [
        r"母公司", r"子公司", r"合营企业", r"联营企业",
        r"控股股东", r"实际控制人", r"董事.*控制", r"高级管理人员",
        r"一致行动人", r"主要股东.{0,6}亲属",
    ]

    def __init__(self, name: str = "fa_12") -> None:
        super().__init__(name)
        self._hints: List[re.Pattern] = []

    def _load_model(self) -> None:
        self._hints = [re.compile(p) for p in self.RELATED_PARTY_HINTS]

    def _preprocess(self, input_data: Any) -> Dict[str, Any]:
        data = input_data or {}
        if not isinstance(data, dict):
            data = {"transactions": data}
        txs = data.get("transactions", data.get("交易", []))
        disclosure = data.get("disclosure_text", data.get("披露文本", ""))
        related_parties = data.get("related_parties", data.get("关联方清单", []))
        if not isinstance(txs, list):
            txs = [txs]
        norm_txs = []
        for t in txs:
            if not isinstance(t, dict):
                continue
            norm_txs.append({
                "tx_id": str(t.get("tx_id", t.get("id", hashlib.md5(json.dumps(t, default=str).encode()).hexdigest()[:8]))),
                "related_party": str(t.get("related_party", t.get("关联方", ""))),
                "relationship": str(t.get("relationship", t.get("关联关系", ""))),
                "tx_type": str(t.get("tx_type", t.get("交易类型", ""))),
                "amount": self._f(t.get("amount", t.get("交易金额", 0))),
                "outstanding": self._f(t.get("outstanding", t.get("期末余额", 0))),
                "pricing_policy": str(t.get("pricing_policy", t.get("定价政策", ""))),
                "approval": str(t.get("approval", t.get("审批", ""))),
            })
        parties = [str(p) for p in related_parties] if isinstance(related_parties, list) else [str(related_parties)]
        return {
            "transactions": norm_txs,
            "disclosure_text": str(disclosure),
            "declared_parties": parties,
            "context": data.get("context", {}),
        }

    def _infer(self, prepared: Any) -> Any:
        txs = prepared["transactions"]
        disc = prepared["disclosure_text"]
        declared = prepared["declared_parties"]

        # 识别哪些交易在披露文本中被提及
        matched_txs = set()
        disclosed_parties_in_text = set()
        for tx in txs:
            if self._tx_in_disclosure(tx, disc, declared):
                matched_txs.add(tx["tx_id"])
                if tx["related_party"]:
                    disclosed_parties_in_text.add(tx["related_party"])
            elif tx["related_party"] and tx["related_party"] in disc:
                disclosed_parties_in_text.add(tx["related_party"])

        undisclosed = [tx for tx in txs if tx["tx_id"] not in matched_txs]
        # 披露文本侧还声明但可能没交易的关联方（如仅股东）：不计入问题，但提示
        all_related_known = {tx["related_party"] for tx in txs if tx["related_party"]} | set(declared)
        missing_fields = self._check_mandatory_fields(disc, txs)

        results = []
        for tx in undisclosed:
            results.append({
                "tx_id": tx["tx_id"],
                "related_party": tx["related_party"],
                "relationship": tx["relationship"],
                "tx_type": tx["tx_type"],
                "amount": tx["amount"],
                "outstanding": tx["outstanding"],
                "status": "UNDISCLOSED",
                "severity": self._severity(tx),
                "reason": self._undisclose_reason(tx, disc),
                "suggestion": self._suggest(tx),
            })
        # 已披露但字段缺失的
        for tx in [t for t in txs if t["tx_id"] in matched_txs]:
            missing = self._tx_missing_fields(tx, disc)
            if missing:
                results.append({
                    "tx_id": tx["tx_id"],
                    "related_party": tx["related_party"],
                    "relationship": tx["relationship"],
                    "tx_type": tx["tx_type"],
                    "amount": tx["amount"],
                    "outstanding": tx["outstanding"],
                    "status": "PARTIAL",
                    "severity": "medium",
                    "missing_fields": missing,
                    "suggestion": f"补充披露: {missing}",
                })
        # 完全合规的
        disclosed_txs = [t for t in txs if t["tx_id"] in matched_txs and not self._tx_missing_fields(t, disc)]
        for tx in disclosed_txs:
            results.append({
                "tx_id": tx["tx_id"],
                "related_party": tx["related_party"],
                "relationship": tx["relationship"],
                "tx_type": tx["tx_type"],
                "amount": tx["amount"],
                "outstanding": tx["outstanding"],
                "status": "OK",
                "severity": "low",
                "suggestion": "",
            })

        return {
            "check_results": results,
            "summary_fields": missing_fields,
            "declared_parties_in_text": sorted(disclosed_parties_in_text),
            "total_related_parties_known": len(all_related_known),
        }

    def _postprocess(self, result: Any) -> Any:
        items = result.get("check_results", []) if isinstance(result, dict) else []
        if not isinstance(items, list):
            items = []
        undisclosed = [i for i in items if i["status"] == "UNDISCLOSED"]
        partial = [i for i in items if i["status"] == "PARTIAL"]
        ok = [i for i in items if i["status"] == "OK"]
        total_amount = sum(i.get("amount", 0) for i in items)
        undisclosed_amount = sum(i.get("amount", 0) for i in undisclosed)
        severity_dist = Counter(i["severity"] for i in items if i["status"] != "OK")
        completeness_score = self._completeness_score(len(ok), len(partial), len(undisclosed))
        return {
            "items": items,
            "summary": {
                "total_transactions": len(items),
                "fully_disclosed": len(ok),
                "partially_disclosed": len(partial),
                "undisclosed": len(undisclosed),
                "completeness_score": completeness_score,
                "severity_distribution": dict(severity_dist),
                "total_transaction_amount": round(total_amount, 2),
                "undisclosed_amount": round(undisclosed_amount, 2),
                "missing_mandatory_fields": result.get("summary_fields", []),
            },
            "high_risk_items": [i for i in items if i["severity"] == "high" and i["status"] != "OK"],
            "remediation_plan": self._remediation(items, result),
        }

    # ── 匹配辅助 ──────────────────────────────────────────────────────────────
    def _tx_in_disclosure(self, tx: Dict[str, Any], disc: str, declared: List[str]) -> bool:
        rp = tx["related_party"]
        if rp and rp in disc:
            return True
        # 模糊匹配
        if rp:
            for d in declared:
                if SequenceMatcher(None, rp, d).ratio() > 0.7:
                    if d in disc:
                        return True
        # 类型+金额
        if tx["tx_type"] and tx["amount"] > 0:
            if tx["tx_type"] in disc and f"{tx['amount']:.0f}" in disc:
                return True
        return False

    def _check_mandatory_fields(self, disc: str, txs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        missing = []
        for fid, desc, required, keywords in self.DISCLOSURE_RULES:
            if required:
                hit = any(any(k in disc for k in keywords) for _ in [0])
                if not hit:
                    missing.append({"field_id": fid, "description": desc, "is_required": True})
        return missing

    def _tx_missing_fields(self, tx: Dict[str, Any], disc: str) -> List[str]:
        missing = []
        for fid, desc, required, keywords in self.DISCLOSURE_RULES:
            if not required:
                continue
            if fid == "identifier" and tx["related_party"] and tx["related_party"] not in disc:
                missing.append(desc)
            elif fid == "transaction_type" and tx["tx_type"] and tx["tx_type"] not in disc:
                missing.append(desc)
            elif fid == "transaction_amount" and f"{tx['amount']:.0f}" not in disc and f"{tx['amount']}" not in disc:
                missing.append(desc)
        return missing

    def _undisclose_reason(self, tx, disc) -> str:
        reasons = []
        if not tx["related_party"]:
            reasons.append("未声明关联方名称")
        if tx["amount"] > 0 and f"{tx['amount']:.0f}" not in disc and f"{tx['amount']}" not in disc:
            reasons.append("交易金额未披露")
        if tx["relationship"] and tx["relationship"] not in disc:
            reasons.append("关联关系类型未披露")
        return "；".join(reasons) if reasons else "关联方整体未在披露文本出现"

    def _severity(self, tx) -> str:
        if tx["amount"] > 50_000_000:
            return "high"
        if tx["relationship"] in ("母公司", "控股股东", "实际控制人") and tx["amount"] > 5_000_000:
            return "high"
        if tx["amount"] > 1_000_000:
            return "medium"
        return "low"

    def _suggest(self, tx) -> str:
        if tx["relationship"] in ("母公司", "控股股东"):
            return f"立即补充披露 {tx['related_party']} 的{tx['tx_type']}交易"
        return f"补充 {tx['related_party']} 交易明细至关联交易章节"

    def _completeness_score(self, ok, partial, undisclosed):
        total = ok + partial + undisclosed
        if total == 0:
            return 100.0
        return round((ok * 1.0 + partial * 0.6) / total * 100, 1)

    def _remediation(self, items, result) -> List[Dict[str, Any]]:
        steps = []
        for i in items:
            if i["status"] == "UNDISCLOSED":
                steps.append({
                    "priority": "P0" if i["severity"] == "high" else "P1",
                    "action": f"补披露: {i['related_party']} - {i['tx_type']} - ¥{i['amount']:,.0f}",
                    "owner": "董秘/财务",
                })
            elif i["status"] == "PARTIAL":
                steps.append({
                    "priority": "P1",
                    "action": f"补充字段: {i.get('missing_fields', [])}",
                    "owner": "董秘/财务",
                })
        return steps

    @staticmethod
    def _f(x):
        try:
            return float(x)
        except Exception:
            return 0.0
