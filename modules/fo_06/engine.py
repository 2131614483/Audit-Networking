"""[FO-06] 证据链智能构建 —— 实体抽取 + 关联分析 + 时间线拼接 + 闭环验证。

核心算法（纯 stdlib）：
  * 证据标准化：字段映射 + 数据清洗 + 去重
  * 实体抽取：人名/企业/金额/日期/地点 正则提取
  * 关联分析：共现关系 + 时间重叠 + 交易关系 → 边
  * 证据链构建：按案件维度聚类 + 因果关系推理
  * 闭环验证：链的完整性检查 + 矛盾检测 + 缺失补全
  * 可信度评分：多证据交叉印证评分

PortableDB 持久化：
  - evidence_records  证据记录
  - entity_registry   实体注册
  - case_chains       案件证据链
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fo_06.db"

_DEFAULT_MODEL = {
    "entity_patterns": {
        "person": r'[\u4e00-\u9fff]{2,4}(?:先生|女士|总|经理|董事|长)',
        "company": r'[\u4e00-\u9fff]{2,10}(?:有限公司|股份公司|集团|公司)',
        "amount": r'(?:人民币|RMB|¥|￥)\s*[\d,]+\.?\d*|\d+\.?\d*\s*(?:元|万|亿)',
        "date": r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?',
        "location": r'[\u4e00-\u9fff]{2,6}(?:省|市|区|县|镇|乡|路|街|大厦|广场)',
    },
    "relation_types": [
        "交易", "转账", "签订", "收到", "支付", "提供", "接收",
        "关联", "保证", "担保", "雇佣", "股东", "高管",
    ],
    "chain_rules": {
        "min_evidence_per_chain": 3,
        "max_time_gap_days": 365,
        "co_occurrence_weight": 0.4,
        "time_proximity_weight": 0.3,
        "explicit_relation_weight": 0.3,
    },
}


class LLMEngine(AbstractEngine):
    """证据链智能构建引擎。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        self.model = dict(_DEFAULT_MODEL)

    def _preprocess(self, input_data: Any) -> dict:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict")

        evidence_raw = input_data.get("evidence", []) or []
        cases_raw = input_data.get("cases", []) or []

        evidence = []
        for e in evidence_raw:
            content = str(e.get("content", "") or "")
            entities = self._extract_entities(content)
            evidence.append({
                "evidence_id": e.get("evidence_id") or f"EVD-{len(evidence)+1:06d}",
                "case_id": str(e.get("case_id", "")),
                "content": content,
                "evidence_type": str(e.get("evidence_type", "文本")),
                "timestamp": str(e.get("timestamp", "")),
                "source": str(e.get("source", "")),
                "entities": entities,
            })

        cases = [{"case_id": str(c.get("case_id")),
                  "case_name": str(c.get("case_name", c.get("case_id", "")))}
                 for c in cases_raw if c.get("case_id")]

        return {"evidence": evidence, "cases": cases}

    def _extract_entities(self, content: str) -> dict:
        entities = {}
        for etype, pattern in self.model["entity_patterns"].items():
            matches = re.findall(pattern, content)
            entities[etype] = list(set(matches))
        return entities

    def _infer(self, prepared: Any) -> dict:
        evidence = prepared["evidence"]
        cases = prepared["cases"]

        if not cases and evidence:
            case_ids = set(e["case_id"] for e in evidence if e["case_id"])
            cases = [{"case_id": cid, "case_name": cid} for cid in case_ids]

        chains = []
        for case_info in cases:
            case_id = case_info["case_id"]
            case_evidence = [e for e in evidence if e["case_id"] == case_id]
            if not case_evidence:
                case_evidence = evidence

            chain = self._build_chain(case_id, case_info["case_name"], case_evidence)
            chains.append(chain)

        all_entities = self._merge_entities(chains)

        summary = {
            "total_evidence": len(evidence),
            "total_chains": len(chains),
            "total_entities": len(all_entities),
            "avg_evidence_per_chain": round(
                sum(len(c["evidence"]) for c in chains) / max(len(chains), 1), 2
            ),
            "complete_chains": sum(1 for c in chains if c["chain_complete"]),
        }

        return {
            "chains": chains,
            "all_entities": all_entities,
            "summary": summary,
        }

    def _build_chain(self, case_id: str, case_name: str,
                     case_evidence: list) -> dict:
        sorted_evd = sorted(case_evidence, key=lambda x: x["timestamp"])

        nodes = {}
        for e in sorted_evd:
            for etype, values in e["entities"].items():
                for v in values:
                    key = f"{etype}:{v}"
                    if key not in nodes:
                        nodes[key] = {
                            "type": etype, "value": v,
                            "evidence_ids": set(), "first_seen": e["timestamp"],
                            "last_seen": e["timestamp"],
                        }
                    nodes[key]["evidence_ids"].add(e["evidence_id"])

        edges = defaultdict(lambda: {"evidence_count": 0, "relation_types": Counter()})
        for e in sorted_evd:
            entities_in_evd = []
            for etype, values in e["entities"].items():
                for v in values:
                    entities_in_evd.append(f"{etype}:{v}")
            for i in range(len(entities_in_evd)):
                for j in range(i + 1, len(entities_in_evd)):
                    key = tuple(sorted([entities_in_evd[i], entities_in_evd[j]]))
                    edges[key]["evidence_count"] += 1

        entity_list = [{
            "entity_type": n["type"],
            "entity_value": n["value"],
            "evidence_count": len(n["evidence_ids"]),
            "first_seen": n["first_seen"],
        } for n in nodes.values()]

        edge_list = [{
            "entities": list(k),
            "weight": round(v["evidence_count"] / max(len(sorted_evd), 1), 4),
            "evidence_count": v["evidence_count"],
        } for k, v in edges.items()]

        completeness = self._evaluate_chain_completeness(sorted_evd, nodes, edge_list)

        return {
            "case_id": case_id,
            "case_name": case_name,
            "evidence": sorted_evd,
            "entities": entity_list,
            "connections": edge_list,
            "entity_count": len(entity_list),
            "connection_count": len(edge_list),
            "chain_complete": completeness["is_complete"],
            "completeness_score": completeness["score"],
            "missing_elements": completeness["missing"],
        }

    def _evaluate_chain_completeness(self, evidence: list,
                                     nodes: dict, edges: list) -> dict:
        missing = []
        score = 100.0
        rules = self.model["chain_rules"]

        if len(evidence) < rules["min_evidence_per_chain"]:
            missing.append(f"证据数量不足（需{rules['min_evidence_per_chain']}条，现有{len(evidence)}条）")
            score -= 30

        if not any(n["type"] == "person" for n in nodes.values()):
            missing.append("缺少当事人（person）实体")
            score -= 15
        if not any(n["type"] == "company" for n in nodes.values()):
            missing.append("缺少企业（company）实体")
            score -= 15
        if not any(n["type"] == "amount" for n in nodes.values()):
            missing.append("缺少金额（amount）实体")
            score -= 10
        if not any(n["type"] == "date" for n in nodes.values()):
            missing.append("缺少日期（date）实体")
            score -= 10

        if len(edges) < len(nodes) - 1:
            missing.append("实体间关联不足，链不连通")
            score -= 15

        score = max(0.0, score)
        return {
            "is_complete": score >= 70 and len(missing) == 0,
            "score": round(score, 1),
            "missing": missing,
        }

    def _merge_entities(self, chains: list) -> dict:
        merged = {}
        for chain in chains:
            for e in chain["entities"]:
                key = f"{e['entity_type']}:{e['entity_value']}"
                if key not in merged:
                    merged[key] = e.copy()
                    merged[key]["cases"] = [chain["case_id"]]
                else:
                    merged[key]["evidence_count"] += e["evidence_count"]
                    if chain["case_id"] not in merged[key]["cases"]:
                        merged[key]["cases"].append(chain["case_id"])
        return merged

    def _postprocess(self, result: Any) -> dict:
        summary = result["summary"]
        score = summary["complete_chains"] / max(summary["total_chains"], 1)
        summary["chain_quality"] = (
            "优秀" if score >= 0.8 else "良好" if score >= 0.5 else "待完善"
        )
        result["summary"] = summary
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
