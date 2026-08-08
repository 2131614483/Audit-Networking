"""[IP-01] IPO审计智能加速平台 —— RPA + ML + LLM + 知识图谱 四栈融合引擎。

设计（中心化公用辐射：复用 modules.shared.base_engine.AbstractEngine 与
modules.shared.portable_db.PortableDB，纯 stdlib，禁止 langchain/openai/rpa/selenium）：

  * RPA 任务自动化：用规则引擎模拟 RPA 执行重复性任务（数据采集 / 格式转换 /
    交叉核对 / 文件归档），rpa_automatable 模板任务被自动完成并落 acceleration_log。
  * ML 财务核查：Benford 定律首位数字分析 + Z-Score 异常值 + 同比趋势分析，
    识别财务异常（同 FO-01 思路简化版，纯 math 实现）。
  * LLM 文档处理：用纯 stdlib TextRank 模拟 LLM 做文档摘要 + 关键词提取 +
    关键信息抽取（句子切分 → 词频统计 → 句子评分=词频和/句长 → 取 top 句）。
  * 知识图谱穿透：用 dict + set 做图遍历，实现股权穿透 / 关联交易 / 资金流向。
  * 进度加速：按任务计算 acceleration_ratio = RPA替代率 + ML辅助率*(1-RPA替代率)，
    识别瓶颈任务，输出周期缩短比例（业务目标 50-60%）。

模型结构（self.model）：
  {
    "audit_task_templates":  [模板任务]，          # 来自 fixtures/audit_tasks.jsonl
    "checkpoint_rules":      {rule_id: 规则},      # 来自 fixtures/checkpoint_rules.jsonl
    "benford_expected":      {1..9: log10(1+1/d)}, # Benford 期望首位频率
    "related_tx_threshold":  关联交易重点核查阈值,
  }

PortableDB 四张运行时表（modules/ip_01/data/ip_01.db）：
  ipo_tasks          —— 本次执行实例化的审计任务（审计追溯）
  checkpoints        —— 核查点执行记录
  findings           —— 核查发现（财务异常/关联交易/内控/文档）
  acceleration_logs  —— 加速日志（RPA/ML/LLM/KG 各阶段节省工时）
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

# 模块根目录（定位 fixtures 与 data 目录）
_MODULE_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _MODULE_DIR / "tests" / "fixtures"
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ip_01.db"

# ------------------------------------------------------------------
# PortableDB 表 schema
# ------------------------------------------------------------------
# 审计任务表：本次执行实例化的任务（每行 = 一个任务执行记录）
_IPO_TASKS_SCHEMA = {
    "task_id": "TEXT",
    "category": "TEXT",            # financial / legal / business / internal_control
    "task_name": "TEXT",
    "description": "TEXT",
    "status": "TEXT",              # pending / auto_done / manual_review / done
    "rpa_automatable": "INTEGER",  # 0 / 1
    "ml_assisted": "INTEGER",      # 0 / 1
    "rpa_replacement_rate": "REAL",
    "ml_assist_rate": "REAL",
    "acceleration_ratio": "REAL",
    "estimated_hours": "REAL",
    "after_hours": "REAL",
    "is_bottleneck": "INTEGER",
    "payload": "JSON",
    "created_at": "DATETIME",
}
# 核查点表：规则引擎执行记录
_CHECKPOINTS_SCHEMA = {
    "checkpoint_id": "TEXT",
    "category": "TEXT",
    "rule_id": "TEXT",
    "rule_name": "TEXT",
    "target_task_id": "TEXT",
    "status": "TEXT",              # passed / flagged / skipped
    "payload": "JSON",
    "created_at": "DATETIME",
}
# 核查发现表
_FINDINGS_SCHEMA = {
    "finding_id": "TEXT",
    "category": "TEXT",            # financial_anomaly / related_transaction / internal_control / document
    "severity": "TEXT",            # high / medium / low
    "source": "TEXT",              # rpa / ml / llm / kg
    "description": "TEXT",
    "related_task_id": "TEXT",
    "need_manual_review": "INTEGER",
    "payload": "JSON",
    "created_at": "DATETIME",
}
# 加速日志表
_ACCELERATION_LOGS_SCHEMA = {
    "phase": "TEXT",               # rpa / ml / llm / kg / acceleration
    "task_id": "TEXT",
    "action": "TEXT",
    "before_hours": "REAL",
    "after_hours": "REAL",
    "saved_hours": "REAL",
    "payload": "JSON",
    "created_at": "DATETIME",
}

# ------------------------------------------------------------------
# TextRank 中文停用词（单字为主，纯 stdlib 无 jieba 时的噪声过滤）
# ------------------------------------------------------------------
_STOPWORDS = {
    "的", "了", "和", "是", "在", "有", "与", "为", "对", "由", "及", "或", "等",
    "其", "这", "那", "一", "二", "三", "上", "下", "中", "也", "都", "而", "但",
    "并", "则", "以", "到", "从", "把", "被", "让", "使", "给", "向", "于", "之",
    "该", "此", "将", "已", "可", "应", "需", "各", "本", "据", "按", "经", "因",
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "for", "is", "are",
    "was", "were", "be", "by", "with", "as", "at", "it", "this", "that", "from",
}


class LLMEngine(AbstractEngine):
    """IPO审计智能加速引擎（RPA + ML + LLM-TextRank + KG，纯 stdlib）。

    继承 AbstractEngine，实现 _load_model / _preprocess / _infer / _postprocess。
    execute() 模板方法不可修改：预处理 → 推理 → 后处理。
    """

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        # 允许 config 覆盖 fixtures / db 路径，便于测试隔离
        self.fixtures_dir = Path(self.config.get("fixtures_dir", _FIXTURES_DIR))
        self.db_path = Path(self.config.get("db_path", _DB_PATH))

    # ==================================================================
    # 1. 模型加载
    # ==================================================================
    def _load_model(self) -> None:
        """加载 IPO 审计流程模板 + 核查规则库 + PortableDB 初始化。

        数据来源：
          1. tests/fixtures/audit_tasks.jsonl     审计任务模板（财务/法律/业务/内控）
          2. tests/fixtures/checkpoint_rules.jsonl 核查规则库
          3. PortableDB 四张运行时表（ipo_tasks/checkpoints/findings/acceleration_logs）
        """
        # 1. 初始化 PortableDB（中心化公用辐射）
        self.db = PortableDB(self.db_path)

        # 2. 建四张运行时表（若不存在）
        if "ipo_tasks" not in self.db.tables():
            self.db.create_table("ipo_tasks", _IPO_TASKS_SCHEMA)
        if "checkpoints" not in self.db.tables():
            self.db.create_table("checkpoints", _CHECKPOINTS_SCHEMA)
        if "findings" not in self.db.tables():
            self.db.create_table("findings", _FINDINGS_SCHEMA)
        if "acceleration_logs" not in self.db.tables():
            self.db.create_table("acceleration_logs", _ACCELERATION_LOGS_SCHEMA)

        # 3. 加载审计任务模板（流程模板）—— 从 fixtures 读入内存模型
        audit_task_templates = self._load_jsonl_fixture(
            "audit_tasks.jsonl", fallback=_DEFAULT_AUDIT_TASK_TEMPLATES
        )

        # 4. 加载核查规则库 —— 从 fixtures 读入内存模型，按 rule_id 索引
        rule_rows = self._load_jsonl_fixture(
            "checkpoint_rules.jsonl", fallback=_DEFAULT_CHECKPOINT_RULES
        )
        checkpoint_rules: dict[str, dict] = {}
        for r in rule_rows:
            rid = r.get("rule_id") or r.get("id")
            if rid:
                checkpoint_rules[rid] = r

        # 5. Benford 期望首位数字频率（log10(1+1/d)）
        benford_expected = {d: math.log10(1 + 1 / d) for d in range(1, 10)}

        # 6. 关联交易重点核查阈值（可被 config 覆盖）
        related_tx_threshold = float(
            self.config.get("threshold", {}).get("related_tx_amount", 5_000_000)
        )

        self.model = {
            "audit_task_templates": audit_task_templates,
            "checkpoint_rules": checkpoint_rules,
            "benford_expected": benford_expected,
            "related_tx_threshold": related_tx_threshold,
        }

    def _load_jsonl_fixture(self, name: str, fallback: list[dict]) -> list[dict]:
        """从 fixtures 目录加载 jsonl；缺失时回退到内置默认（保证引擎可独立运行）。"""
        path = self.fixtures_dir / name
        rows: list[dict] = []
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        return rows if rows else list(fallback)

    # ==================================================================
    # 2. 预处理
    # ==================================================================
    def _preprocess(self, input_data: Any) -> Any:
        """提取 IPO 项目信息，按模板分解审计任务（财务/法律/业务/内控）。"""
        # 懒加载：若未显式 setup()，execute() 时自动加载模型
        if self.model is None:
            self._load_model()

        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 enterprise/financial_data 等字段")

        # 2.1 提取项目信息（容错：缺失字段给默认值）
        enterprise = input_data.get("enterprise", {}) or {}
        financial_data = input_data.get("financial_data", {}) or {}
        legal_documents = input_data.get("legal_documents", []) or []
        history = input_data.get("history", []) or []
        related_parties = input_data.get("related_parties", []) or []
        equity_structure = input_data.get("equity_structure", {}) or {}
        documents = input_data.get("documents", []) or []

        project = {
            "project_id": input_data.get("project_id", "IPO-UNKNOWN"),
            "enterprise": enterprise,
            "financial_data": financial_data,
            "legal_documents": legal_documents,
            "history": history,
            "related_parties": related_parties,
            "equity_structure": equity_structure,
            "documents": documents,
        }

        # 2.2 按模板分解审计任务：每个模板实例化为本次执行的 pending 任务
        tasks: list[dict] = []
        for i, tpl in enumerate(self.model["audit_task_templates"], start=1):
            task = {
                "task_id": tpl.get("task_id", f"T{i:03d}"),
                "category": tpl.get("category", "financial"),
                "task_name": tpl.get("task_name", ""),
                "description": tpl.get("description", ""),
                "status": "pending",
                "rpa_automatable": bool(tpl.get("rpa_automatable", False)),
                "ml_assisted": bool(tpl.get("ml_assisted", False)),
                "rpa_replacement_rate": float(tpl.get("rpa_replacement_rate", 0.0)),
                "ml_assist_rate": float(tpl.get("ml_assist_rate", 0.0)),
                "estimated_hours": float(tpl.get("estimated_hours", 8.0)),
                "after_hours": float(tpl.get("estimated_hours", 8.0)),
                "acceleration_ratio": 0.0,
                "is_bottleneck": False,
            }
            tasks.append(task)

        return {"project": project, "tasks": tasks}

    # ==================================================================
    # 3. 推理（RPA + ML + LLM + KG + 加速计算）
    # ==================================================================
    def _infer(self, prepared: Any) -> Any:
        """四技术栈融合推理：RPA 自动化 → ML 财务核查 → LLM 文档处理 → KG 穿透 → 加速计算。"""
        project = prepared["project"]
        tasks = prepared["tasks"]
        tasks_by_id = {t["task_id"]: t for t in tasks}

        findings: list[dict] = []
        checkpoints: list[dict] = []

        # ① RPA 任务自动化（规则引擎模拟）
        rpa_results = self._rpa_automate(project, tasks, findings)

        # ② ML 财务核查（Benford + 异常值 + 趋势）
        ml_results = self._ml_financial_check(project, findings, checkpoints, tasks_by_id)

        # ③ LLM 文档处理（TextRank 摘要 + 关键词 + 关键信息）
        llm_results = self._llm_document_process(project, findings, tasks_by_id)

        # ④ 知识图谱穿透（股权 / 关联交易 / 资金流向）
        kg_results = self._kg_penetration(project, findings, tasks_by_id)

        # ⑤ 进度加速计算 + 瓶颈识别
        acceleration = self._compute_acceleration(tasks)

        # 把 checkpoints 一起带上，供 _postprocess 落库
        return {
            "project": project,
            "tasks": tasks,
            "rpa_results": rpa_results,
            "ml_results": ml_results,
            "llm_results": llm_results,
            "kg_results": kg_results,
            "findings": findings,
            "checkpoints": checkpoints,
            "acceleration": acceleration,
        }

    # ------------------------------------------------------------------
    # ① RPA 任务自动化（规则引擎模拟 RPA 执行重复性任务）
    # ------------------------------------------------------------------
    def _rpa_automate(self, project: dict, tasks: list[dict],
                      findings: list[dict]) -> dict:
        """模拟 RPA 执行数据采集/格式转换/交叉核对/文件归档等重复性任务。

        rpa_automatable=True 的任务由 RPA 自动完成；交叉核对发现差异时产出 finding。
        """
        automated: list[dict] = []
        for t in tasks:
            if not t["rpa_automatable"]:
                continue
            action = self._rpa_action_for(t)
            t["status"] = "auto_done"
            automated.append({
                "task_id": t["task_id"],
                "action": action,
                "status": "auto_done",
                "details": f"RPA 自动执行：{t['task_name']}",
            })

        # RPA 交叉核对：财务数据与法律文件中的注册资本是否一致（示例规则）
        enterprise = project.get("enterprise", {})
        financial_data = project.get("financial_data", {})
        reg_capital = enterprise.get("registered_capital")
        if reg_capital is not None and financial_data:
            # 取最新年度实收资本做交叉核对
            latest_year = sorted(financial_data.keys())[-1] if financial_data else None
            paid_in = financial_data.get(latest_year, {}).get("paid_in_capital") \
                if latest_year else None
            if paid_in is not None and abs(float(paid_in) - float(reg_capital)) > 0.01:
                findings.append({
                    "finding_id": f"F-RPA-{len(findings)+1:03d}",
                    "category": "financial_anomaly",
                    "severity": "medium",
                    "source": "rpa",
                    "description": (
                        f"RPA 交叉核对发现：注册资本 {reg_capital} 与 {latest_year} 年"
                        f"实收资本 {paid_in} 不一致"
                    ),
                    "related_task_id": "FIN-01",
                    "need_manual_review": True,
                })

        return {
            "automated_count": len(automated),
            "actions": automated,
        }

    @staticmethod
    def _rpa_action_for(task: dict) -> str:
        """按任务类别映射 RPA 动作类型（规则引擎）。"""
        name = task.get("task_name", "")
        if "采集" in name or "收集" in name or "获取" in name:
            return "data_collection"
        if "格式" in name or "转换" in name:
            return "format_conversion"
        if "核对" in name or "勾稽" in name or "匹配" in name:
            return "cross_check"
        if "归档" in name or "整理" in name or "编制" in name:
            return "file_archiving"
        return "generic_automation"

    # ------------------------------------------------------------------
    # ② ML 财务核查（Benford + Z-Score 异常值 + 同比趋势分析）
    # ------------------------------------------------------------------
    def _ml_financial_check(self, project: dict, findings: list[dict],
                            checkpoints: list[dict],
                            tasks_by_id: dict[str, dict]) -> dict:
        """ML 财务核查：Benford 定律 + 异常值检测 + 趋势分析。"""
        financial_data = project.get("financial_data", {}) or {}
        if not financial_data:
            return {"benford": {}, "outliers": [], "trend": [], "anomaly_count": 0}

        years = sorted(financial_data.keys())
        # 收集所有金额（用于 Benford 分析）
        amounts = self._collect_amounts(financial_data)
        benford = self._benford_analysis(amounts)

        # Z-Score 异常值检测（按指标跨年统计）
        outliers = self._zscore_outliers(financial_data, years)
        # 同比趋势分析
        trend = self._trend_analysis(financial_data, years)

        # 汇总 ML 发现
        for o in outliers:
            findings.append({
                "finding_id": f"F-ML-{len(findings)+1:03d}",
                "category": "financial_anomaly",
                "severity": "high" if o["z_score"] >= 3.0 else "medium",
                "source": "ml",
                "description": (
                    f"ML 异常值：交易 {o['tx_id']}（{o['year']} 年，{o['description']}）"
                    f"金额={o['amount']}，Z-Score={o['z_score']:.2f}（均值={o['mean']:.2f}）"
                ),
                "related_task_id": "FIN-03",
                "need_manual_review": True,
                "payload": {"z_score": o["z_score"], "tx_id": o["tx_id"], "year": o["year"]},
            })
        for t in trend:
            findings.append({
                "finding_id": f"F-ML-{len(findings)+1:03d}",
                "category": "financial_anomaly",
                "severity": t["severity"],
                "source": "ml",
                "description": t["description"],
                "related_task_id": "FIN-02",
                "need_manual_review": t["severity"] == "high",
                "payload": {"metric": t["metric"], "growth_rates": t["growth_rates"]},
            })

        # Benford 偏离过大 → 发现
        if benford.get("deviation", 0) > 0.01:
            findings.append({
                "finding_id": f"F-ML-{len(findings)+1:03d}",
                "category": "financial_anomaly",
                "severity": "medium",
                "source": "ml",
                "description": (
                    f"ML Benford 检验：首位数字分布偏离期望（卡方={benford['chi_square']:.2f}，"
                    f"偏离度={benford['deviation']:.4f}）"
                ),
                "related_task_id": "FIN-03",
                "need_manual_review": True,
                "payload": {"benford_deviation": benford["deviation"]},
            })

        # 核查点：财务核查规则执行
        for rule in self.model["checkpoint_rules"].values():
            if rule.get("category") != "financial":
                continue
            cp_status = self._eval_checkpoint(rule, {
                "benford": benford, "outliers": outliers, "trend": trend,
            })
            checkpoints.append({
                "checkpoint_id": f"CP-{len(checkpoints)+1:03d}",
                "category": "financial",
                "rule_id": rule.get("rule_id"),
                "rule_name": rule.get("rule_name"),
                "target_task_id": "FIN-03",
                "status": cp_status,
                "payload": {"rule": rule.get("rule_name")},
            })

        return {
            "benford": benford,
            "outliers": outliers,
            "trend": trend,
            "anomaly_count": len(outliers) + len(trend) + (1 if benford.get("deviation", 0) > 0.01 else 0),
        }

    def _collect_amounts(self, financial_data: dict) -> list[float]:
        """从财务数据中收集所有正金额（用于 Benford 分析）。"""
        amounts: list[float] = []
        for year_data in financial_data.values():
            if not isinstance(year_data, dict):
                continue
            for k, v in year_data.items():
                if k == "transactions":
                    continue
                if isinstance(v, (int, float)) and v > 0:
                    amounts.append(float(v))
            for tx in year_data.get("transactions", []) or []:
                amt = tx.get("amount") if isinstance(tx, dict) else None
                if isinstance(amt, (int, float)) and amt > 0:
                    amounts.append(float(amt))
        return amounts

    def _benford_analysis(self, amounts: list[float]) -> dict:
        """Benford 定律首位数字卡方检验（同 FO-01 思路简化版）。"""
        expected = self.model["benford_expected"]
        first_digits = [int(str(int(a))[0]) for a in amounts if a > 0]
        total = len(first_digits)
        if total == 0:
            return {"chi_square": 0.0, "deviation": 0.0, "observed": {}, "expected": {}}
        observed = {d: first_digits.count(d) for d in range(1, 10)}
        chi_square = 0.0
        for d in range(1, 10):
            exp_count = expected[d] * total
            chi_square += (observed[d] - exp_count) ** 2 / max(exp_count, 0.01)
        deviation = chi_square / total
        return {
            "chi_square": round(chi_square, 2),
            "deviation": round(deviation, 4),
            "observed": {str(d): observed[d] for d in range(1, 10)},
            "expected": {str(d): round(expected[d], 4) for d in range(1, 10)},
        }

    def _zscore_outliers(self, financial_data: dict, years: list) -> list[dict]:
        """Z-Score 异常值检测：对全部交易金额统计，|z|>阈值 标记为异常。

        说明：IPO 仅 3 年年度指标，n=3 时 |z| 上界为 sqrt(2)≈1.41，无法触发高阈值；
        故对样本量充足的交易明细做 Z-Score（同 FO-01 思路），年度异常由趋势分析覆盖。
        """
        z_threshold = float(self.config.get("threshold", {}).get("z_score", 2.5))
        # 收集所有交易（跨年）
        txs: list[tuple[str, str, float, str]] = []  # (year, tx_id, amount, desc)
        for y in years:
            ydata = financial_data.get(y, {})
            if not isinstance(ydata, dict):
                continue
            for tx in ydata.get("transactions", []) or []:
                if not isinstance(tx, dict):
                    continue
                amt = tx.get("amount")
                if isinstance(amt, (int, float)) and amt > 0:
                    txs.append((y, tx.get("tx_id", "?"), float(amt), tx.get("description", "")))

        if len(txs) < 4:
            return []
        amounts = [a for _, _, a, _ in txs]
        mean = sum(amounts) / len(amounts)
        variance = sum((a - mean) ** 2 for a in amounts) / len(amounts)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return []

        outliers: list[dict] = []
        for year, tx_id, amt, desc in txs:
            z = (amt - mean) / std
            if abs(z) > z_threshold:
                outliers.append({
                    "tx_id": tx_id,
                    "year": year,
                    "amount": amt,
                    "description": desc,
                    "mean": round(mean, 2),
                    "std": round(std, 2),
                    "z_score": round(z, 2),
                })
        return outliers

    def _trend_analysis(self, financial_data: dict, years: list) -> list[dict]:
        """同比趋势分析：识别异常增长 / 收入利润背离。"""
        trends: list[dict] = []
        if len(years) < 2:
            return trends
        # 计算各指标同比增长率
        metric_growth: dict[str, list[float]] = {}
        for i in range(1, len(years)):
            prev = financial_data.get(years[i - 1], {}) or {}
            curr = financial_data.get(years[i], {}) or {}
            for k in set(prev.keys()) | set(curr.keys()):
                if k == "transactions":
                    continue
                pv, cv = prev.get(k), curr.get(k)
                if isinstance(pv, (int, float)) and isinstance(cv, (int, float)) and pv != 0:
                    metric_growth.setdefault(k, []).append((cv - pv) / abs(pv))

        # 单指标异常波动（增长率绝对值 > 0.5）
        for metric, rates in metric_growth.items():
            for r in rates:
                if abs(r) > 0.5:
                    trends.append({
                        "metric": metric,
                        "growth_rates": [round(x, 4) for x in rates],
                        "severity": "high" if abs(r) > 1.0 else "medium",
                        "description": (
                            f"ML 趋势分析：{metric} 同比变动 {r*100:.1f}%，"
                            f"波动较大（阈值±50%）"
                        ),
                    })
                    break  # 每个指标只产一条趋势发现

        # 收入与净利润背离：任一周期收入增长但净利润下滑
        rev_g = metric_growth.get("revenue", [])
        np_g = metric_growth.get("net_profit", [])
        if rev_g and np_g:
            for i in range(min(len(rev_g), len(np_g))):
                if rev_g[i] > 0.1 and np_g[i] < -0.1:
                    trends.append({
                        "metric": "revenue_vs_net_profit",
                        "growth_rates": {"revenue": round(rev_g[i], 4), "net_profit": round(np_g[i], 4)},
                        "severity": "high",
                        "description": (
                            f"ML 趋势分析：收入同比 +{rev_g[i]*100:.1f}% 但净利润同比 "
                            f"{np_g[i]*100:.1f}%，存在收入利润背离"
                        ),
                    })
                    break
        return trends

    @staticmethod
    def _eval_checkpoint(rule: dict, ctx: dict) -> str:
        """评估核查点规则：passed / flagged。"""
        check_type = rule.get("check_type", "")
        if check_type == "benford" and ctx.get("benford"):
            return "flagged" if ctx["benford"].get("deviation", 0) > float(rule.get("params", {}).get("max_deviation", 0.01)) else "passed"
        if check_type == "outlier" and ctx.get("outliers"):
            return "flagged" if len(ctx["outliers"]) > 0 else "passed"
        if check_type == "trend" and ctx.get("trend"):
            return "flagged" if len(ctx["trend"]) > 0 else "passed"
        return "passed"

    # ------------------------------------------------------------------
    # ③ LLM 文档处理（TextRank 摘要 + 关键词 + 关键信息提取）
    # ------------------------------------------------------------------
    def _llm_document_process(self, project: dict, findings: list[dict],
                              tasks_by_id: dict[str, dict]) -> dict:
        """模拟 LLM 做文档摘要 + 关键词提取 + 关键信息抽取（纯 stdlib TextRank）。"""
        documents = project.get("documents", []) or []
        legal_documents = project.get("legal_documents", []) or []
        # 合并所有待处理文档
        all_docs: list[dict] = []
        for d in documents:
            all_docs.append({"doc_name": d.get("doc_name", "未命名"), "content": d.get("content", "")})
        for d in legal_documents:
            content = d.get("content", "")
            if not content and isinstance(d.get("clauses"), list):
                content = "；".join(d["clauses"])
            all_docs.append({"doc_name": d.get("doc_name", d.get("doc_type", "法律文件")), "content": content})

        summaries: list[dict] = []
        for doc in all_docs:
            text = doc["content"] or ""
            if not text.strip():
                continue
            summary, keywords, key_info = self._textrank(text, num_sentences=2, num_keywords=8)
            summaries.append({
                "doc_name": doc["doc_name"],
                "summary": summary,
                "keywords": keywords,
                "key_info": key_info,
            })
            # 文档中命中风险词 → 产出文档类发现（TextRank 关键词为单字，故对全文扫描风险词）
            risk_hit = [w for w in _RISK_WORDS if w in text]
            if risk_hit:
                findings.append({
                    "finding_id": f"F-LLM-{len(findings)+1:03d}",
                    "category": "document",
                    "severity": "medium",
                    "source": "llm",
                    "description": (
                        f"LLM 文档处理：{doc['doc_name']} 命中风险词 "
                        f"{risk_hit}，建议人工复核"
                    ),
                    "related_task_id": "LEG-02",
                    "need_manual_review": True,
                    "payload": {"doc_name": doc["doc_name"], "keywords": keywords},
                })

        return {"summaries": summaries, "doc_count": len(summaries)}

    def _textrank(self, text: str, num_sentences: int = 2,
                  num_keywords: int = 8) -> tuple[str, list[str], dict]:
        """纯 stdlib TextRank：句子切分 → 词频统计 → 句子评分(词频和/句长) → top 句摘要。

        返回 (摘要文本, 关键词列表, 关键信息 dict)。
        """
        # 1. 句子切分（中英文标点）
        sentences = re.split(r"[。！？\n.!?;；]+", text)
        sentences = [s.strip() for s in sentences if s and s.strip()]
        if not sentences:
            return "", [], {}

        # 2. 分词 + 词频统计（中文字 + 英文词 + 数字，过滤停用词）
        token_re = re.compile(r"[a-zA-Z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]")
        word_freq: dict[str, int] = {}
        sent_tokens: list[list[str]] = []
        for s in sentences:
            tokens = [t for t in token_re.findall(s)
                      if t.lower() not in _STOPWORDS and len(t) > 1 or
                      (len(t) == 1 and "\u4e00" <= t <= "\u9fff" and t not in _STOPWORDS)]
            # 过滤纯单字英文/数字噪声
            tokens = [t for t in tokens
                      if not (len(t) == 1 and not ("\u4e00" <= t <= "\u9fff"))]
            sent_tokens.append(tokens)
            for t in tokens:
                word_freq[t] = word_freq.get(t, 0) + 1

        # 3. 句子评分 = 词频和 / 句长（避免长句占优）
        scored: list[tuple[float, int, str]] = []
        for idx, (s, tokens) in enumerate(zip(sentences, sent_tokens)):
            freq_sum = sum(word_freq.get(t, 0) for t in tokens)
            length = max(len(tokens), 1)
            score = freq_sum / length
            scored.append((score, idx, s))

        # 4. 取 top 句子（按分数降序），再按原顺序拼成摘要
        top = sorted(scored, key=lambda x: x[0], reverse=True)[:num_sentences]
        top_idx = sorted(i for _, i, _ in top)
        summary = "。".join(sentences[i] for i in top_idx) + ("。" if top_idx else "")

        # 5. 关键词 = 词频 top-N
        keywords = [w for w, _ in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:num_keywords]]

        # 6. 关键信息：金额 / 日期 / 比例 抽取
        key_info = self._extract_key_info(text)

        return summary, keywords, key_info

    @staticmethod
    def _extract_key_info(text: str) -> dict:
        """从文本抽取关键信息：金额、日期、比例（正则，纯 stdlib）。"""
        amounts = re.findall(r"\d+(?:\.\d+)?(?:万元|元|亿)", text)
        dates = re.findall(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|\d{4}年", text)
        ratios = re.findall(r"\d+(?:\.\d+)?%", text)
        return {
            "amounts": list(dict.fromkeys(amounts))[:10],
            "dates": list(dict.fromkeys(dates))[:10],
            "ratios": list(dict.fromkeys(ratios))[:10],
        }

    # ------------------------------------------------------------------
    # ④ 知识图谱穿透（股权穿透 / 关联交易 / 资金流向，dict + set 图遍历）
    # ------------------------------------------------------------------
    def _kg_penetration(self, project: dict, findings: list[dict],
                        tasks_by_id: dict[str, dict]) -> dict:
        """知识图谱穿透：用 dict + set 做图遍历，实现关联信息穿透。"""
        equity = project.get("equity_structure", {}) or {}
        related_parties = project.get("related_parties", []) or []

        # 1. 股权穿透：BFS 找终极控制人
        equity_penetration = self._equity_penetration(equity)

        # 2. 关联交易：标记超阈值交易为重点核查
        related_transactions = self._related_transactions(related_parties, findings)

        # 3. 资金流向：BFS 追踪多跳资金路径
        fund_flow = self._fund_flow(equity, related_parties)

        # 关联交易超阈值 → 发现
        threshold = self.model["related_tx_threshold"]
        for rt in related_transactions:
            if rt["amount"] > threshold:
                findings.append({
                    "finding_id": f"F-KG-{len(findings)+1:03d}",
                    "category": "related_transaction",
                    "severity": "high",
                    "source": "kg",
                    "description": (
                        f"KG 关联交易穿透：{rt['party_name']} {rt['tx_type']} "
                        f"金额 {rt['amount']} 超过重点核查阈值 {threshold}，标记重点核查"
                    ),
                    "related_task_id": "FIN-05",
                    "need_manual_review": True,
                    "payload": {"party": rt["party_name"], "amount": rt["amount"]},
                })

        # 股权穿透链路过长 → 发现
        for ep in equity_penetration:
            if len(ep["path"]) > 3:
                findings.append({
                    "finding_id": f"F-KG-{len(findings)+1:03d}",
                    "category": "related_transaction",
                    "severity": "medium",
                    "source": "kg",
                    "description": (
                        f"KG 股权穿透：{ep['controller']} 经 {len(ep['path'])} 层持股"
                        f"（路径：{' → '.join(ep['path'])}），结构复杂建议核查"
                    ),
                    "related_task_id": "LEG-04",
                    "need_manual_review": True,
                    "payload": {"controller": ep["controller"], "path": ep["path"]},
                })

        return {
            "equity_penetration": equity_penetration,
            "related_transactions": related_transactions,
            "fund_flow": fund_flow,
        }

    def _equity_penetration(self, equity: dict) -> list[dict]:
        """股权穿透：从企业节点 BFS 向上找终极控制人（dict + set 图遍历）。"""
        nodes = equity.get("nodes", []) or []
        edges = equity.get("edges", []) or []
        node_name = {n["id"]: n.get("name", n["id"]) for n in nodes if isinstance(n, dict)}
        # 找企业节点（type=enterprise 或第一个节点）
        ent_ids = [n["id"] for n in nodes if isinstance(n, dict) and n.get("type") == "enterprise"]
        if not ent_ids:
            ent_ids = [nodes[0]["id"]] if nodes else []

        # 构建反向邻接：to → [(from, ratio)]（股东 → 被投资方 反向）
        parents: dict[str, list[tuple[str, float]]] = {}
        for e in edges:
            if not isinstance(e, dict):
                continue
            if e.get("relation") == "shareholder":
                parents.setdefault(e["to"], []).append((e["from"], float(e.get("ratio", 0.0))))

        results: list[dict] = []
        for ent in ent_ids:
            # BFS：向上找股东，累计持股比例
            # 队列元素：(当前节点, 路径, 累计比例)
            visited: set[str] = set()
            queue: list[tuple[str, list[str], float]] = [(ent, [node_name.get(ent, ent)], 1.0)]
            while queue:
                cur, path, acc_ratio = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                ups = parents.get(cur, [])
                if not ups:
                    # 无上级股东 → 终极控制人
                    if cur != ent:
                        results.append({
                            "controller": node_name.get(cur, cur),
                            "path": path,
                            "total_ratio": round(acc_ratio, 4),
                        })
                    continue
                for parent_id, ratio in ups:
                    if parent_id not in visited:
                        queue.append((
                            parent_id,
                            path + [node_name.get(parent_id, parent_id)],
                            acc_ratio * ratio,
                        ))
        return results

    def _related_transactions(self, related_parties: list, findings: list) -> list[dict]:
        """关联交易穿透：列出关联方交易，标记超阈值。"""
        threshold = self.model["related_tx_threshold"]
        result: list[dict] = []
        for party in related_parties:
            if not isinstance(party, dict):
                continue
            pname = party.get("party_name", "?")
            for tx in party.get("transactions", []) or []:
                if not isinstance(tx, dict):
                    continue
                amt = float(tx.get("amount", 0))
                result.append({
                    "party_name": pname,
                    "tx_type": tx.get("type", "未知"),
                    "amount": amt,
                    "date": tx.get("date", ""),
                    "flagged": amt > threshold,
                })
        return result

    def _fund_flow(self, equity: dict, related_parties: list) -> list[dict]:
        """资金流向：用 dict + set 做图遍历，追踪多跳资金路径。"""
        # 构建有向图：A → B 表示资金从 A 流向 B
        graph: dict[str, set[str]] = {}
        node_name: dict[str, str] = {}
        for n in equity.get("nodes", []) or []:
            if isinstance(n, dict):
                node_name[n["id"]] = n.get("name", n["id"])

        # 关联方交易作为资金流边（关联方 ↔ 企业）
        ent_id = "ENTERPRISE"
        for n in equity.get("nodes", []) or []:
            if isinstance(n, dict) and n.get("type") == "enterprise":
                ent_id = n["id"]
                break
        party_name_to_id = {p.get("party_name"): p.get("party_name") for p in related_parties if isinstance(p, dict)}
        for pname in party_name_to_id:
            node_name.setdefault(pname, pname)

        for party in related_parties:
            if not isinstance(party, dict):
                continue
            pname = party.get("party_name")
            for tx in party.get("transactions", []) or []:
                if not isinstance(tx, dict):
                    continue
                ttype = tx.get("type", "")
                # 采购/支付 → 企业流出资金到关联方；销售/收款 → 反向
                if "采购" in ttype or "支付" in ttype or "付款" in ttype:
                    graph.setdefault(ent_id, set()).add(pname)
                elif "销售" in ttype or "收款" in ttype or "收入" in ttype:
                    graph.setdefault(pname, set()).add(ent_id)
                else:
                    graph.setdefault(ent_id, set()).add(pname)

        # 从企业出发 BFS，找 2-3 跳资金路径
        paths: list[dict] = []
        visited_global: set[str] = set()
        # BFS 找路径
        queue: list[tuple[str, list[str]]] = [(ent_id, [node_name.get(ent_id, ent_id)])]
        while queue:
            cur, path = queue.pop(0)
            if len(path) > 3:
                continue
            for nxt in graph.get(cur, set()):
                nxt_name = node_name.get(nxt, nxt)
                new_path = path + [nxt_name]
                if len(new_path) >= 3:
                    paths.append({
                        "path": new_path,
                        "hops": len(new_path) - 1,
                    })
                key = f"{cur}->{nxt}"
                if key not in visited_global:
                    visited_global.add(key)
                    queue.append((nxt, new_path))
        # 去重（同路径只保留一条）
        seen = set()
        unique_paths: list[dict] = []
        for p in paths:
            sig = " -> ".join(p["path"])
            if sig not in seen:
                seen.add(sig)
                unique_paths.append(p)
        return unique_paths[:20]

    # ------------------------------------------------------------------
    # ⑤ 进度加速计算 + 瓶颈识别
    # ------------------------------------------------------------------
    def _compute_acceleration(self, tasks: list[dict]) -> dict:
        """计算各任务加速比例（RPA替代率 + ML辅助率），识别瓶颈任务。

        acceleration_ratio = rpa_replacement_rate + ml_assist_rate * (1 - rpa_replacement_rate)
        上限 0.95（保留人工终审）。
        """
        bottleneck_threshold = float(
            self.config.get("threshold", {}).get("bottleneck", 0.5)
        )
        task_accelerations: list[dict] = []
        total_before = 0.0
        total_after = 0.0
        for t in tasks:
            rpa_rate = t["rpa_replacement_rate"]
            ml_rate = t["ml_assist_rate"]
            ratio = min(0.95, rpa_rate + ml_rate * (1 - rpa_rate))
            t["acceleration_ratio"] = round(ratio, 4)
            before = t["estimated_hours"]
            after = before * (1 - ratio)
            t["after_hours"] = round(after, 2)
            # 瓶颈：加速比例低于阈值且非 RPA 全自动
            t["is_bottleneck"] = ratio < bottleneck_threshold
            # 状态：RPA 可自动且高加速 → auto_done；中加速 → manual_review；低 → manual
            if t["status"] == "pending":
                if ratio >= 0.85:
                    t["status"] = "auto_done"
                elif ratio >= bottleneck_threshold:
                    t["status"] = "manual_review"
                else:
                    t["status"] = "manual"
            total_before += before
            total_after += after
            task_accelerations.append({
                "task_id": t["task_id"],
                "task_name": t["task_name"],
                "category": t["category"],
                "acceleration_ratio": t["acceleration_ratio"],
                "before_hours": before,
                "after_hours": t["after_hours"],
                "saved_hours": round(before - after, 2),
                "is_bottleneck": t["is_bottleneck"],
            })

        overall = (total_before - total_after) / total_before if total_before > 0 else 0.0
        bottleneck_tasks = [a for a in task_accelerations if a["is_bottleneck"]]
        # 瓶颈按加速比例升序（最待优化的在前）
        bottleneck_tasks.sort(key=lambda x: x["acceleration_ratio"])

        return {
            "task_accelerations": task_accelerations,
            "bottleneck_tasks": bottleneck_tasks,
            "overall_acceleration_ratio": round(overall, 4),
            "total_before_hours": round(total_before, 2),
            "total_after_hours": round(total_after, 2),
            "total_saved_hours": round(total_before - total_after, 2),
            # 预计周期缩短比例 = 整体加速比例（业务目标 50-60%）
            "estimated_cycle_reduction_pct": round(overall * 100, 2),
        }

    # ==================================================================
    # 4. 后处理
    # ==================================================================
    def _postprocess(self, result: Any) -> Any:
        """输出 IPO 审计加速报告：任务完成状态 + 核查发现 + 加速效果 + 瓶颈分析。"""
        tasks = result.get("tasks", [])
        findings = result.get("findings", [])
        accel = result.get("acceleration", {})

        # 任务完成状态汇总
        status_count = {"auto_done": 0, "manual_review": 0, "manual": 0, "pending": 0, "done": 0}
        category_status: dict[str, dict[str, int]] = {}
        for t in tasks:
            s = t.get("status", "pending")
            status_count[s] = status_count.get(s, 0) + 1
            cat = t.get("category", "unknown")
            category_status.setdefault(cat, {"auto_done": 0, "manual_review": 0, "manual": 0})
            if s in category_status[cat]:
                category_status[cat][s] += 1

        # 核查发现汇总（按来源 / 严重程度）
        findings_by_source: dict[str, int] = {}
        findings_by_severity: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for f in findings:
            findings_by_source[f["source"]] = findings_by_source.get(f["source"], 0) + 1
            sev = f.get("severity", "low")
            findings_by_severity[sev] = findings_by_severity.get(sev, 0) + 1

        # 瓶颈分析
        bottlenecks = accel.get("bottleneck_tasks", [])

        result["report"] = {
            "task_completion": {
                "status_count": status_count,
                "category_status": category_status,
            },
            "findings_summary": {
                "total": len(findings),
                "by_source": findings_by_source,
                "by_severity": findings_by_severity,
                "need_manual_review": sum(1 for f in findings if f.get("need_manual_review")),
            },
            "acceleration_effect": {
                "overall_acceleration_ratio": accel.get("overall_acceleration_ratio", 0.0),
                "total_before_hours": accel.get("total_before_hours", 0.0),
                "total_after_hours": accel.get("total_after_hours", 0.0),
                "total_saved_hours": accel.get("total_saved_hours", 0.0),
                "estimated_cycle_reduction_pct": accel.get("estimated_cycle_reduction_pct", 0.0),
            },
            "bottleneck_analysis": {
                "bottleneck_count": len(bottlenecks),
                "bottleneck_tasks": [
                    {"task_id": b["task_id"], "task_name": b["task_name"],
                     "category": b["category"], "acceleration_ratio": b["acceleration_ratio"],
                     "after_hours": b["after_hours"]}
                    for b in bottlenecks
                ],
            },
        }

        # 统计指标
        result["statistics"] = {
            "total_tasks": len(tasks),
            "completed_tasks": status_count.get("auto_done", 0) + status_count.get("done", 0),
            "auto_done_tasks": status_count.get("auto_done", 0),
            "manual_review_tasks": status_count.get("manual_review", 0),
            "manual_tasks": status_count.get("manual", 0),
            "overall_acceleration_ratio": accel.get("overall_acceleration_ratio", 0.0),
            "findings_count": len(findings),
            "bottleneck_count": len(bottlenecks),
            "estimated_cycle_reduction_pct": accel.get("estimated_cycle_reduction_pct", 0.0),
            # 周期天数估算（按 8 小时/天，加速前总工时 → 天数）
            "cycle_before_days": round(accel.get("total_before_hours", 0.0) / 8, 1),
            "cycle_after_days": round(accel.get("total_after_hours", 0.0) / 8, 1),
        }
        return result

    # ==================================================================
    # 生命周期
    # ==================================================================
    def close(self) -> None:
        """关闭 PortableDB 连接。"""
        if self.db is not None:
            self.db.close()
            self.db = None


# 风险词（LLM 关键信息抽取后命中 → 产出文档类发现）
_RISK_WORDS = ["纠纷", "诉讼", "仲裁", "处罚", "违规", "瑕疵", "风险", "关联", "占用", "担保"]


# ==================================================================
# 内置默认模板（fixtures 缺失时回退，保证引擎可独立运行）
# 财务/法律/业务/内控 各 5+ 任务，rpa_replacement_rate + ml_assist_rate
# 经加权后整体加速比例落在 50-60% 区间。
# ==================================================================
_DEFAULT_AUDIT_TASK_TEMPLATES: list[dict] = [
    # ---- 财务核查（financial）----
    {"task_id": "FIN-01", "category": "financial", "task_name": "财务数据采集与归档",
     "description": "采集三年财务报表、总账、明细账并归档", "rpa_automatable": True, "ml_assisted": False,
     "rpa_replacement_rate": 0.9, "ml_assist_rate": 0.0, "estimated_hours": 40},
    {"task_id": "FIN-02", "category": "financial", "task_name": "财务数据格式转换与勾稽核对",
     "description": "多源财务数据格式统一、报表勾稽关系核对", "rpa_automatable": True, "ml_assisted": True,
     "rpa_replacement_rate": 0.7, "ml_assist_rate": 0.2, "estimated_hours": 32},
    {"task_id": "FIN-03", "category": "financial", "task_name": "财务异常智能核查",
     "description": "Benford/异常值/趋势分析识别财务异常", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.0, "ml_assist_rate": 0.7, "estimated_hours": 48},
    {"task_id": "FIN-04", "category": "financial", "task_name": "收入成本跨期核查",
     "description": "收入确认时点、成本跨期匹配核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.2, "ml_assist_rate": 0.4, "estimated_hours": 36},
    {"task_id": "FIN-05", "category": "financial", "task_name": "关联交易定价核查",
     "description": "关联方交易识别与定价公允性核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.5, "estimated_hours": 40},
    {"task_id": "FIN-06", "category": "financial", "task_name": "现金流与银行流水核对",
     "description": "银行流水采集与账面现金流交叉核对", "rpa_automatable": True, "ml_assisted": True,
     "rpa_replacement_rate": 0.6, "ml_assist_rate": 0.3, "estimated_hours": 44},
    # ---- 法律核查（legal）----
    {"task_id": "LEG-01", "category": "legal", "task_name": "法律文件采集与归档",
     "description": "公司章程、合同、诉讼文书采集归档", "rpa_automatable": True, "ml_assisted": False,
     "rpa_replacement_rate": 0.85, "ml_assist_rate": 0.0, "estimated_hours": 24},
    {"task_id": "LEG-02", "category": "legal", "task_name": "合同条款智能抽取",
     "description": "合同关键条款抽取与风险识别", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.6, "estimated_hours": 36},
    {"task_id": "LEG-03", "category": "legal", "task_name": "历史沿革梳理",
     "description": "工商变更、股权演变梳理", "rpa_automatable": True, "ml_assisted": True,
     "rpa_replacement_rate": 0.5, "ml_assist_rate": 0.3, "estimated_hours": 30},
    {"task_id": "LEG-04", "category": "legal", "task_name": "股权穿透核查",
     "description": "实际控制人认定、股权穿透核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.6, "estimated_hours": 32},
    {"task_id": "LEG-05", "category": "legal", "task_name": "诉讼合规核查",
     "description": "未决诉讼、行政处罚合规核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.2, "ml_assist_rate": 0.5, "estimated_hours": 28},
    # ---- 业务核查（business）----
    {"task_id": "BIZ-01", "category": "business", "task_name": "业务数据采集",
     "description": "生产、销售、采购业务数据采集", "rpa_automatable": True, "ml_assisted": False,
     "rpa_replacement_rate": 0.8, "ml_assist_rate": 0.0, "estimated_hours": 28},
    {"task_id": "BIZ-02", "category": "business", "task_name": "客户供应商核查",
     "description": "主要客户供应商访谈与核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.2, "ml_assist_rate": 0.4, "estimated_hours": 40},
    {"task_id": "BIZ-03", "category": "business", "task_name": "行业与市场分析",
     "description": "行业地位、市场竞争分析", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.5, "estimated_hours": 24},
    {"task_id": "BIZ-04", "category": "business", "task_name": "业务模式描述",
     "description": "盈利模式、业务流程描述", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.4, "estimated_hours": 20},
    {"task_id": "BIZ-05", "category": "business", "task_name": "技术核查",
     "description": "核心技术、研发能力核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.3, "estimated_hours": 22},
    # ---- 内控核查（internal_control）----
    {"task_id": "IC-01", "category": "internal_control", "task_name": "内控制度文件采集",
     "description": "内控制度、流程文件采集归档", "rpa_automatable": True, "ml_assisted": False,
     "rpa_replacement_rate": 0.8, "ml_assist_rate": 0.0, "estimated_hours": 16},
    {"task_id": "IC-02", "category": "internal_control", "task_name": "控制点测试",
     "description": "关键控制点设计与执行测试", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.2, "ml_assist_rate": 0.5, "estimated_hours": 36},
    {"task_id": "IC-03", "category": "internal_control", "task_name": "内控缺陷识别",
     "description": "内控设计与运行缺陷识别", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.6, "estimated_hours": 30},
    {"task_id": "IC-04", "category": "internal_control", "task_name": "IT一般控制核查",
     "description": "信息系统一般控制核查", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.2, "ml_assist_rate": 0.4, "estimated_hours": 24},
    {"task_id": "IC-05", "category": "internal_control", "task_name": "整改建议跟踪",
     "description": "内控缺陷整改建议与跟踪", "rpa_automatable": False, "ml_assisted": True,
     "rpa_replacement_rate": 0.1, "ml_assist_rate": 0.3, "estimated_hours": 20},
]

_DEFAULT_CHECKPOINT_RULES: list[dict] = [
    {"rule_id": "CR-FIN-01", "category": "financial", "rule_name": "Benford首位数字检验",
     "check_type": "benford", "params": {"max_deviation": 0.01}},
    {"rule_id": "CR-FIN-02", "category": "financial", "rule_name": "财务指标异常值检验",
     "check_type": "outlier", "params": {"z_threshold": 2.5}},
    {"rule_id": "CR-FIN-03", "category": "financial", "rule_name": "同比趋势异常检验",
     "check_type": "trend", "params": {"max_growth": 0.5}},
    {"rule_id": "CR-LEG-01", "category": "legal", "rule_name": "股权穿透复杂度检验",
     "check_type": "graph", "params": {"max_depth": 3}},
    {"rule_id": "CR-IC-01", "category": "internal_control", "rule_name": "内控缺陷分级检验",
     "check_type": "rule", "params": {"severity": "high"}},
]
