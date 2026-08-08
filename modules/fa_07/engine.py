"""[FA-07] 智能底稿自动生成平台 —— 纯 stdlib 模板引擎 + 规则结论生成。

算法设计（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，不引入任何第三方依赖）：

  * 模板库：200+ 标准化模板元数据（library_size_meta），实供 15+ 核心底稿模板
    （tests/fixtures/templates.jsonl），覆盖函证/账龄/盘点/折旧/核对/截止/分析性复核。
  * ① 模板匹配：按科目名/别名匹配适用底稿模板（一个科目可匹配多个模板，
    如银行存款 → 银行存款函证底稿 + 银行存款余额表底稿）。
  * ② 数据填入：string.Template.safe_substitute 把占位符 ${name} 替换为
    从 context 点分路径（entity.name / subject.balance / subject.detail.aging...）
    提取的值；缺失值以「【待补充】」兜底并记入 placeholders_missing。
  * ③ 结论生成：规则引擎对 conclusion_rules 逐条求值（op: >/>=/</<=/==/!=/missing/present），
    命中规则拼装审计结论；severity 取最严重（warning > info > ok）。
  * ④ 交叉引用：按模板声明的 cross_refs 自动建立底稿间引用边，
    被引用模板未生成 → status=broken 并标 warning。
  * 完成度：必填占位符填充率 × (1 - 0.2×warning命中数)，下限 0.4。

模型结构（self.model）：
  {
    "templates":          [模板dict, ...],
    "by_id":              {template_id: 模板dict},
    "library_size_meta":  200,   # 元数据声明的模板库规模
  }
"""
from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# 模块根目录（定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "fa_07.db"

# 严重程度优先级（数值越大越严重）：用于结论汇总取最严重
_SEVERITY_RANK = {"ok": 1, "info": 2, "warning": 3}
# 完成度扣分：每个 warning 级规则命中扣 0.2，最低 0.4
_WARNING_PENALTY = 0.2
_MIN_COMPLETENESS = 0.4

# 模板库 schema（持久化模板元数据）
_TEMPLATES_SCHEMA = {
    "template_id": "TEXT",
    "template_name": "TEXT",
    "subject_type": "TEXT",
    "audit_procedure": "TEXT",
    "description": "TEXT",
    "payload": "JSON",
}
# 生成的底稿 schema（审计追溯）
_WORKPAPERS_SCHEMA = {
    "workpaper_id": "TEXT",
    "template_id": "TEXT",
    "subject_code": "TEXT",
    "subject_name": "TEXT",
    "filled_content": "TEXT",
    "conclusion": "TEXT",
    "conclusion_severity": "TEXT",
    "completeness": "REAL",
    "created_at": "DATETIME",
    "payload": "JSON",
}
# 交叉引用 schema
_CROSS_REFS_SCHEMA = {
    "from_workpaper_id": "TEXT",
    "to_workpaper_id": "TEXT",
    "to_template_id": "TEXT",
    "to_template_name": "TEXT",
    "status": "TEXT",
    "created_at": "DATETIME",
}
# 生成日志 schema
_GEN_LOGS_SCHEMA = {
    "batch_id": "TEXT",
    "template_id": "TEXT",
    "workpaper_id": "TEXT",
    "action": "TEXT",
    "created_at": "DATETIME",
    "payload": "JSON",
}


def _resolve_path(context: dict, path: str) -> Any:
    """点分路径取值：如 'subject.detail.aging.within_1y_ratio'。

    依次从 context dict 递归取键；取不到返回 None。仅支持 dict 嵌套（不支持 list 索引）。
    """
    if not path:
        return None
    cur: Any = context
    for part in str(path).split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _eval_rule(metric: Any, op: str, value: Any) -> bool:
    """规则求值（纯 stdlib，禁止 eval）。

    支持的 op：
      * missing  : metric 为 None → 命中
      * present  : metric 不为 None → 命中
      * >/>=/</<= : 数值比较（metric 为 None 不命中）
      * ==/!=    : 等值比较
    """
    if op == "missing":
        return metric is None
    if op == "present":
        return metric is not None
    # 数值/等值比较：metric 为 None 一律不命中
    if metric is None:
        return False
    try:
        if op == ">":
            return metric > value
        if op == ">=":
            return metric >= value
        if op == "<":
            return metric < value
        if op == "<=":
            return metric <= value
        if op == "==":
            return metric == value
        if op == "!=":
            return metric != value
    except TypeError:
        return False
    return False


class KGEngine(AbstractEngine):
    """智能底稿自动生成引擎（纯 stdlib：string.Template + 规则引擎）。

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
        """加载模板库（200+ 元数据，实供 15+ 核心模板）+ PortableDB 初始化。

        数据来源（按优先级）：
          1. tests/fixtures/templates.jsonl   核心底稿模板种子（首次导入）
          2. PortableDB templates 表          持久化模板（后续直接读取）
        """
        # 1. 初始化 PortableDB（中心化公用辐射）
        self.db = PortableDB(self.db_path)

        # 2. 建 4 张持久化表（若不存在）
        for name, schema in [
            ("templates", _TEMPLATES_SCHEMA),
            ("workpapers", _WORKPAPERS_SCHEMA),
            ("cross_references", _CROSS_REFS_SCHEMA),
            ("generation_logs", _GEN_LOGS_SCHEMA),
        ]:
            if name not in self.db.tables():
                self.db.create_table(name, schema)

        # 3. 首次启动：从 fixtures 导入模板种子（仅当表为空）
        if self.db.count("templates") == 0:
            tpl_fixture = self.fixtures_dir / "templates.jsonl"
            if tpl_fixture.exists():
                with open(tpl_fixture, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        t = json.loads(line)
                        self.db.insert("templates", {
                            "template_id": t.get("template_id"),
                            "template_name": t.get("template_name"),
                            "subject_type": t.get("subject_type"),
                            "audit_procedure": t.get("audit_procedure"),
                            "description": t.get("description"),
                            "payload": t,
                        })

        # 4. 加载到内存模型
        templates: list[dict] = []
        for row in self.db.all("templates"):
            payload = row.get("payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            if payload:
                templates.append(payload)
        self.model = {
            "templates": templates,
            "by_id": {t["template_id"]: t for t in templates},
            "library_size_meta": 200,  # 元数据声明：模板库规模 200+
        }

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------
    def _preprocess(self, input_data: Any) -> Any:
        """提取审计对象信息（科目/期间/被审单位）+ 可用数据源，规范化为 context。"""
        # 懒加载：若未显式 setup()，execute() 时自动加载模型
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 entity/period/subjects")

        entity = input_data.get("entity", {}) or {}
        period = input_data.get("period", {}) or {}
        subjects = input_data.get("subjects", []) or []
        vouchers = input_data.get("vouchers", []) or []
        contracts = input_data.get("contracts", []) or []

        # 若 subjects 为空，从 audit_data.jsonl 数据底座回退重建
        if not subjects:
            subjects = self._load_subjects_from_fixture()

        # 规范化：仅保留含 subject_name 的科目
        norm_subjects = []
        for s in subjects:
            if isinstance(s, dict) and s.get("subject_name"):
                norm_subjects.append(s)

        return {
            "entity": entity,
            "period": period,
            "subjects": norm_subjects,
            "vouchers": vouchers,
            "contracts": contracts,
        }

    def _load_subjects_from_fixture(self) -> list[dict]:
        """从 audit_data.jsonl 重建 subjects（record_type=balance 的记录聚合）。"""
        path = self.fixtures_dir / "audit_data.jsonl"
        if not path.exists():
            return []
        subjects: list[dict] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("record_type") == "balance":
                    subjects.append({
                        "subject_code": rec.get("subject_code"),
                        "subject_name": rec.get("subject_name"),
                        "category": rec.get("category"),
                        "balance": rec.get("balance"),
                        "detail": rec.get("detail", {}),
                    })
        return subjects

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def _infer(self, prepared: Any) -> Any:
        """① 模板匹配 ② 数据填入 ③ 结论生成 ④ 交叉引用。"""
        templates = (self.model or {}).get("templates", [])
        workpapers: list[dict] = []
        wp_counter = 0

        for subject in prepared["subjects"]:
            # 构造该科目的 context（subject 指向当前科目）
            ctx = {
                "entity": prepared["entity"],
                "period": prepared["period"],
                "subject": subject,
                "vouchers": prepared["vouchers"],
                "contracts": prepared["contracts"],
            }
            # ① 模板匹配
            matched = self._match_templates(subject, templates)
            for tpl in matched:
                wp_counter += 1
                wp_id = f"wp_{wp_counter:03d}"
                # ② 数据填入 + ③ 结论生成
                wp = self._build_workpaper(wp_id, tpl, subject, ctx)
                workpapers.append(wp)

        # ④ 交叉引用（需在所有底稿生成后建立）
        cross_refs = self._build_cross_references(workpapers)

        # 把交叉引用挂到每份底稿，并处理断裂 warning
        wp_refs: dict[str, list[dict]] = {}
        for ref in cross_refs:
            wp_refs.setdefault(ref["from_workpaper_id"], []).append(ref)
        for wp in workpapers:
            refs = wp_refs.get(wp["workpaper_id"], [])
            wp["cross_references"] = refs
            for r in refs:
                if r["status"] == "broken":
                    wp["warnings"].append(
                        f"warning: 交叉引用断裂 —— {r['to_template_name']}"
                        f"({r['to_template_id']}) 未生成对应底稿"
                    )

        return {
            "workpapers": workpapers,
            "cross_references": cross_refs,
            "meta": {
                "library_total_meta": (self.model or {}).get("library_size_meta", 0),
                "core_templates": len(templates),
            },
        }

    def _match_templates(self, subject: dict, templates: list[dict]) -> list[dict]:
        """根据科目名/别名匹配适用模板（一个科目可匹配多个模板）。

        匹配规则：科目名 == 模板主名/别名，或二者互为包含。
        """
        name = (subject.get("subject_name") or "").strip()
        hits: list[dict] = []
        for tpl in templates:
            stype = (tpl.get("subject_type") or "").strip()
            aliases = [a.strip() for a in tpl.get("subject_aliases", []) if a]
            keys = [stype] + aliases
            for k in keys:
                if not k:
                    continue
                if k == name or k in name or name in k:
                    hits.append(tpl)
                    break
        return hits

    def _build_workpaper(self, wp_id: str, tpl: dict, subject: dict,
                         ctx: dict) -> dict:
        """单份底稿生成：占位符填入 + 结论规则求值 + 完成度计算。"""
        # ② 数据填入：从 context 点分路径取值，string.Template 安全替换
        substitutions: dict[str, Any] = {}
        filled: dict[str, Any] = {}
        missing: list[str] = []
        for ph in tpl.get("placeholders", []):
            pname = ph["name"]
            val = _resolve_path(ctx, ph.get("source"))
            filled[pname] = val
            if val is None:
                missing.append(pname)
                substitutions[pname] = "【待补充】"
            else:
                substitutions[pname] = val
        content = Template(tpl.get("content_template", "")).safe_substitute(substitutions)

        # ③ 结论生成：规则引擎逐条求值
        rules = tpl.get("conclusion_rules", [])
        hit_rules: list[dict] = []
        severities: list[str] = []
        for rule in rules:
            metric = _resolve_path(ctx, rule.get("metric_path"))
            if _eval_rule(metric, rule.get("op"), rule.get("value")):
                hit_rules.append({
                    "metric_path": rule.get("metric_path"),
                    "op": rule.get("op"),
                    "value": rule.get("value"),
                    "conclusion": rule.get("conclusion"),
                    "severity": rule.get("severity", "info"),
                })
                severities.append(rule.get("severity", "info"))

        # 汇总结论文本与总体 severity（取最严重）
        if hit_rules:
            conclusion_text = "；".join(r["conclusion"] for r in hit_rules)
            overall_sev = max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))
        else:
            conclusion_text = "未命中结论规则，需人工判断。"
            overall_sev = "info"

        # 完成度：必填占位符填充率 × (1 - 0.2×warning命中数)，下限 0.4
        required = [ph for ph in tpl.get("placeholders", []) if ph.get("required")]
        req_total = len(required)
        req_filled = sum(1 for ph in required if filled.get(ph["name"]) is not None)
        base = (req_filled / req_total) if req_total > 0 else 1.0
        warning_count = sum(1 for r in hit_rules if r["severity"] == "warning")
        completeness = max(_MIN_COMPLETENESS, base - _WARNING_PENALTY * warning_count)
        completeness = round(completeness, 4)

        # warnings：缺失数据标记 TODO
        warnings: list[str] = []
        for m in missing:
            warnings.append(f"TODO: 缺失数据 {m}，需补充后完善底稿")

        # needs_review 基础标记：severity=warning 需人工复核（custom_rules 会补充）
        needs_review = overall_sev == "warning"

        return {
            "workpaper_id": wp_id,
            "template_id": tpl.get("template_id"),
            "template_name": tpl.get("template_name"),
            "subject_code": subject.get("subject_code"),
            "subject_name": subject.get("subject_name"),
            "audit_procedure": tpl.get("audit_procedure"),
            "filled_content": content,
            "placeholders_filled": filled,
            "placeholders_missing": missing,
            "conclusion": conclusion_text,
            "conclusion_severity": overall_sev,
            "conclusion_rules_hit": hit_rules,
            "completeness": completeness,
            "needs_review": needs_review,
            "warnings": warnings,
            "cross_references": [],  # 后置填充
        }

    def _build_cross_references(self, workpapers: list[dict]) -> list[dict]:
        """自动建立底稿间引用关系：被引用模板未生成 → status=broken。"""
        by_id = (self.model or {}).get("by_id", {})
        # template_id → 首份生成的 workpaper_id（同模板多科目时取首个）
        tpl_to_wp: dict[str, str] = {}
        for wp in workpapers:
            tid = wp["template_id"]
            if tid not in tpl_to_wp:
                tpl_to_wp[tid] = wp["workpaper_id"]

        refs: list[dict] = []
        for wp in workpapers:
            tpl = by_id.get(wp["template_id"], {})
            for to_tid in tpl.get("cross_refs", []):
                to_tpl = by_id.get(to_tid, {})
                to_name = to_tpl.get("template_name", to_tid)
                if to_tid in tpl_to_wp:
                    refs.append({
                        "from_workpaper_id": wp["workpaper_id"],
                        "to_workpaper_id": tpl_to_wp[to_tid],
                        "to_template_id": to_tid,
                        "to_template_name": to_name,
                        "status": "linked",
                    })
                else:
                    refs.append({
                        "from_workpaper_id": wp["workpaper_id"],
                        "to_workpaper_id": None,
                        "to_template_id": to_tid,
                        "to_template_name": to_name,
                        "status": "broken",
                    })
        return refs

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------
    def _postprocess(self, result: Any) -> Any:
        """输出生成的底稿列表 + 统计（生成数/完成率/覆盖科目/交叉引用数）。"""
        wps = result.get("workpapers", [])
        total = len(wps)
        covered = {wp.get("subject_code") for wp in wps if wp.get("subject_code")}
        completeness_vals = [wp.get("completeness", 0.0) for wp in wps]
        avg_completeness = round(sum(completeness_vals) / total, 4) if total else 0.0
        cross_refs = result.get("cross_references", [])
        broken_refs = sum(1 for r in cross_refs if r["status"] == "broken")
        needs_review_count = sum(1 for wp in wps if wp.get("needs_review"))

        result["statistics"] = {
            "total_workpapers": total,
            "generated": total,
            "completeness_avg": avg_completeness,
            "covered_subjects": len(covered),
            "cross_references": len(cross_refs),
            "broken_refs": broken_refs,
            "needs_review": needs_review_count,
            "core_templates": len((self.model or {}).get("templates", [])),
            "library_total_meta": (self.model or {}).get("library_size_meta", 0),
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
