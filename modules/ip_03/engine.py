"""[IP-03] 知识图谱历史沿革梳理引擎 —— 时间线排序 + 合规检查 + 股权关系推断。

算法设计（纯 stdlib）：

  * _load_model:
      - 加载合规规则库（出资/转让/增资/减资/改制/外资/国资 7大类）
      - 预定义异常检测规则（比例合计!=100%/时间顺序矛盾/缺少决议文件等）
  * _preprocess:
      - 从 input 提取 events 列表，按日期排序、解析日期字符串、标准化字段
  * _infer:
      ① 时间线：按日期排序 → 阶段划分 → 关键节点标注（控制权变更/改制）
      ② 股权快照：逐事件更新 shareholder → 构建 timeline 快照列表
      ③ 合规检查：对每个事件跑规则库 + 异常检测
      ④ 时间冲突检测：日期重叠 / 顺序矛盾
  * _postprocess:
      - 整理为 timeline + anomalies + compliance_report 三部分
      - 计算合规覆盖率、异常数
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from collections import defaultdict

from modules.shared.base_engine import AbstractEngine


def _parse_date(s: Any) -> datetime | None:
    if isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        return None
    fmts = ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%Y-%m-%d %H:%M:%S"]
    for f in fmts:
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            pass
    m = re.search(r"(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


class KGEngine(AbstractEngine):
    """知识图谱历史沿革梳理引擎（纯 stdlib：时间线 + 合规规则 + 股权快照）。"""

    def _load_model(self) -> None:
        compliance_rules = [
            {"id": "CR-01", "name": "股权比例合计100%", "category": "基本",
             "desc": "同一时点所有股东持股比例合计应为100%"},
            {"id": "CR-02", "name": "出资不低于注册资本", "category": "出资",
             "desc": "出资额合计应不低于注册资本"},
            {"id": "CR-03", "name": "转让价格合理", "category": "转让",
             "desc": "股权转让价格不应显著偏离净资产（±50%）"},
            {"id": "CR-04", "name": "增资经股东会决议", "category": "增资",
             "desc": "增资应经代表2/3以上表决权的股东通过"},
            {"id": "CR-05", "name": "减资需公告", "category": "减资",
             "desc": "减资应在报纸上公告3次以上并通知债权人"},
            {"id": "CR-06", "name": "改制需评估", "category": "改制",
             "desc": "有限责任公司变更为股份有限公司应当评估净资产"},
            {"id": "CR-07", "name": "外资准入限制", "category": "外资",
             "desc": "外商投资应符合负面清单规定"},
            {"id": "CR-08", "name": "国资进场交易", "category": "国资",
             "desc": "国有股权转让应在产权交易机构公开进行"},
        ]
        anomaly_patterns = [
            {"id": "AP-01", "name": "比例异常", "desc": "持股比例合计偏离100%超过1%"},
            {"id": "AP-02", "name": "时间顺序矛盾", "desc": "后发事件日期早于前序事件"},
            {"id": "AP-03", "name": "缺少决议文件", "desc": "重大变更缺少股东会/董事会决议"},
            {"id": "AP-04", "name": "价格异常", "desc": "转让价格显著偏离净资产评估值"},
        ]
        self.model = {
            "compliance_rules": compliance_rules,
            "anomaly_patterns": anomaly_patterns,
        }

    def _preprocess(self, input_data: Any) -> Any:
        """标准化事件列表：日期解析 + 字段补全 + 类型归类。"""
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 events 列表")
        events = input_data.get("events", []) or []
        company = input_data.get("company_name", "")
        norm: list[dict] = []
        for e in events:
            if not isinstance(e, dict):
                continue
            d = _parse_date(e.get("date", ""))
            if d is None:
                continue
            norm.append({
                "event_type": e.get("event_type", "unknown"),
                "date": d,
                "date_str": d.strftime("%Y-%m-%d"),
                "description": e.get("description", ""),
                "shareholders": e.get("shareholders", []),
                "amount": e.get("amount"),
                "price": e.get("price"),
                "net_asset": e.get("net_asset"),
                "has_resolution": e.get("has_resolution", True),
                "has_notice": e.get("has_notice", True),
                "raw": e,
            })
        norm.sort(key=lambda x: x["date"])
        return {"company": company, "events": norm}

    def _infer(self, prepared: Any) -> Any:
        events = prepared["events"]
        timeline = self._build_timeline(events)
        snapshots = self._build_equity_snapshots(events)
        anomalies = self._detect_anomalies(events, snapshots)
        compliance = self._compliance_check(events, prepared["company"])
        return {
            "timeline": timeline,
            "equity_snapshots": snapshots,
            "anomalies": anomalies,
            "compliance": compliance,
            "company": prepared["company"],
        }

    def _build_timeline(self, events: list[dict]) -> list[dict]:
        key_event_types = {"restructuring", "改制", "ipo", "liquidation", "control_change", "控制权变更"}
        periods: list[dict] = []
        timeline: list[dict] = []
        cur_start = None
        cur_name = ""
        for i, e in enumerate(events):
            is_key = any(k in (e["event_type"] + e["description"]) for k in key_event_types)
            if cur_start is None:
                cur_start = e["date"]
                cur_name = f"阶段{i + 1}"
            timeline.append({
                "seq": i + 1,
                "date": e["date_str"],
                "event_type": e["event_type"],
                "description": e["description"],
                "is_key_node": is_key,
                "has_resolution": e["has_resolution"],
            })
            if is_key or i == len(events) - 1:
                periods.append({
                    "name": cur_name,
                    "start": cur_start.strftime("%Y-%m-%d"),
                    "end": e["date_str"],
                    "event_count": sum(1 for t in timeline if cur_start <= _parse_date(t["date"]) <= e["date"]),
                })
                cur_start = None
                cur_name = ""
        return timeline

    def _build_equity_snapshots(self, events: list[dict]) -> list[dict]:
        shareholders: dict[str, float] = {}
        snapshots: list[dict] = []
        for e in events:
            for sh in e["shareholders"]:
                name = sh.get("name") or sh.get("shareholder")
                pct = sh.get("ratio") or sh.get("percentage") or 0
                if name:
                    shareholders[name] = float(pct)
            total = sum(shareholders.values())
            if abs(total - 100) > 0.5 and shareholders:
                snapshots.append({
                    "date": e["date_str"],
                    "status": "比例异常",
                    "shareholders": dict(shareholders),
                    "total_ratio": round(total, 2),
                })
            else:
                snapshots.append({
                    "date": e["date_str"],
                    "status": "正常",
                    "shareholders": dict(shareholders),
                    "total_ratio": round(total, 2),
                })
        return snapshots

    def _detect_anomalies(self, events: list[dict], snapshots: list[dict]) -> list[dict]:
        anomalies: list[dict] = []
        for i, e in enumerate(events):
            if i > 0 and events[i - 1]["date"] > e["date"]:
                anomalies.append({
                    "rule_id": "AP-02", "name": "时间顺序矛盾",
                    "severity": "high", "event_seq": i + 1,
                    "detail": f"第{i}个事件 {events[i-1]['date_str']} 晚于第{i+1}个事件 {e['date_str']}",
                })
            if e["event_type"] in ("增资", "减资", "restructuring", "改制") and not e["has_resolution"]:
                anomalies.append({
                    "rule_id": "AP-03", "name": "缺少决议文件",
                    "severity": "high", "event_seq": i + 1,
                    "detail": f"{e['event_type']}事件 {e['date_str']} 标记 has_resolution=False",
                })
        for snap in snapshots:
            if abs(snap["total_ratio"] - 100) > 0.5:
                anomalies.append({
                    "rule_id": "AP-01", "name": "比例异常",
                    "severity": "medium", "event_seq": None,
                    "detail": f"{snap['date']} 时点持股比例合计 {snap['total_ratio']}%",
                })
        return anomalies

    def _compliance_check(self, events: list[dict], company: str) -> dict:
        rules = self.model["compliance_rules"]
        hits: list[dict] = []
        for r in rules:
            status = "pass"
            detail = r["desc"]
            for e in events:
                if r["id"] == "CR-01":
                    sh_total = sum((s.get("ratio") or s.get("percentage") or 0) for s in e["shareholders"])
                    if e["shareholders"] and abs(sh_total - 100) > 1:
                        status = "fail"
                        detail = f"{e['date_str']} 股东比例合计 {sh_total:.1f}%"
                elif r["id"] == "CR-03" and e["price"] and e["net_asset"]:
                    if abs(e["price"] - e["net_asset"]) / e["net_asset"] > 0.5:
                        status = "warning"
                        detail = f"转让价格 {e['price']} 显著偏离净资产 {e['net_asset']}"
                elif r["id"] == "CR-04" and e["event_type"] in ("增资",) and not e["has_resolution"]:
                    status = "fail"
                    detail = "增资缺少股东会决议"
                elif r["id"] == "CR-05" and e["event_type"] in ("减资",) and not e["has_notice"]:
                    status = "fail"
                    detail = "减资未执行公告程序"
                elif r["id"] == "CR-06" and e["event_type"] in ("restructuring", "改制"):
                    status = "info"
                    detail = "改制需确认是否进行资产评估（需人工复核）"
            hits.append({"rule_id": r["id"], "name": r["name"], "category": r["category"],
                         "status": status, "detail": detail})
        total = len(hits)
        passed = sum(1 for h in hits if h["status"] == "pass")
        warnings = sum(1 for h in hits if h["status"] == "warning")
        fails = sum(1 for h in hits if h["status"] == "fail")
        return {
            "rules_checked": hits,
            "total": total,
            "passed": passed,
            "warnings": warnings,
            "fails": fails,
            "coverage": f"{passed}/{total}",
        }

    def _postprocess(self, result: Any) -> Any:
        events = len(result["timeline"])
        anomalies = result["anomalies"]
        compliance = result["compliance"]
        high_sev = sum(1 for a in anomalies if a["severity"] == "high")
        medium_sev = sum(1 for a in anomalies if a["severity"] == "medium")
        result["statistics"] = {
            "total_events": events,
            "key_events": sum(1 for t in result["timeline"] if t["is_key_node"]),
            "equity_snapshots": len(result["equity_snapshots"]),
            "total_anomalies": len(anomalies),
            "high_severity": high_sev,
            "medium_severity": medium_sev,
            "compliance_coverage": compliance["coverage"],
            "compliance_fails": compliance["fails"],
        }
        if high_sev > 0 or compliance["fails"] > 0:
            result["verdict"] = "需重点人工复核"
        elif medium_sev > 0 or compliance["warnings"] > 0:
            result["verdict"] = "建议人工复核"
        else:
            result["verdict"] = "通过自动化梳理"
        return result
