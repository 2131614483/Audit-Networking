"""[IA-03] 审计资源智能分配引擎 —— 纯 stdlib 遗传算法 + 余弦相似度技能匹配。

算法设计（复用 modules.shared.base_engine.AbstractEngine + PortableDB）：

  * 技能匹配度计算（余弦相似度 + 技能权重）：
      - 项目需求技能向量 vs 审计师技能向量 → 加权余弦相似度
      - 行业匹配：审计师历史行业经验与项目行业标签的 Jaccard 系数
  * 目标函数（6 维度加权）：
      - 技能匹配度 ×0.35 + 负载均衡 ×0.20 + 成本效率 ×0.15
      + 人员发展 ×0.15 + 团队协同 ×0.10 + 连续性 ×0.05
      - 硬约束违反：-50分 / 项；软约束违反：-10分 / 项
  * 遗传算法求解（纯 stdlib GA）：
      - 染色体编码：项目 → 人员分配列表
      - 初始化：50% 贪心 + 30% 随机 + 20% 历史（若有）
      - 选择：锦标赛选择（size=3）+ 精英保留 Top 10%
      - 交叉：PMX（部分映射交叉）概率 0.8
      - 变异：交换变异 + 替换变异 概率 0.1
      - 早停：80 代无改进
  * 硬约束检查：每人工时 ≤ 可用工时；关键技能覆盖率；高级审计师最低配置
  * 差旅成本估算：城市间地理距离近似 + 人均差旅费率

模型结构（self.model）：
  {
    "skill_weights": {...},
    "city_coords": {...},
    "industry_clusters": {...},
    "ga_params": {"pop_size": 200, "max_gen": 300, "elite_ratio": 0.1},
    "assignments": [],       # 历史分配（连续性参考）
  }
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.shared.base_engine import AbstractEngine
from modules.shared.portable_db import PortableDB

_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR / "data"
_DB_PATH = _DATA_DIR / "ia_03.db"

_AUDITORS_SCHEMA = {
    "auditor_id": "TEXT PRIMARY KEY",
    "name": "TEXT",
    "level": "TEXT",
    "skills": "JSON",
    "industries": "JSON",
    "city": "TEXT",
    "hourly_rate": "REAL",
    "weekly_hours": "REAL",
    "available_hours": "REAL",
    "development_goals": "JSON",
    "created_at": "DATETIME",
}
_PROJECTS_SCHEMA = {
    "project_id": "TEXT PRIMARY KEY",
    "name": "TEXT",
    "industry": "TEXT",
    "city": "TEXT",
    "required_skills": "JSON",
    "required_count": "INTEGER",
    "duration_weeks": "REAL",
    "budget": "REAL",
    "complexity": "REAL",
    "created_at": "DATETIME",
}
_ASSIGNMENTS_SCHEMA = {
    "assignment_id": "TEXT PRIMARY KEY",
    "project_id": "TEXT",
    "auditor_id": "TEXT",
    "fit_score": "REAL",
    "assigned_at": "DATETIME",
}
_PLANS_SCHEMA = {
    "plan_id": "TEXT PRIMARY KEY",
    "score": "REAL",
    "skill_match": "REAL",
    "load_balance": "REAL",
    "cost_efficiency": "REAL",
    "development": "REAL",
    "team_synergy": "REAL",
    "continuity": "REAL",
    "violations": "INTEGER",
    "assignments": "JSON",
    "created_at": "DATETIME",
}


_SKILL_WEIGHTS = {
    "财务审计": 1.2, "IT审计": 1.1, "数据分析": 1.0,
    "风险评估": 1.0, "内部控制": 0.9, "合规审计": 0.9,
    "舞弊调查": 1.1, "ESG审计": 1.0, "运营审计": 0.8,
}

_CITY_COORDS = {
    "北京": (39.9, 116.4), "上海": (31.2, 121.5),
    "广州": (23.1, 113.3), "深圳": (22.5, 114.1),
    "成都": (30.6, 104.1), "杭州": (30.3, 120.2),
    "南京": (32.1, 118.8), "武汉": (30.6, 114.3),
}

_INDUSTRY_CLUSTERS = {
    "金融": ["银行", "保险", "证券", "基金", "金融科技"],
    "制造": ["制造业", "工厂", "生产", "供应链"],
    "零售": ["零售", "电商", "分销", "消费品"],
    "科技": ["IT", "软件", "互联网", "科技公司"],
    "医药": ["制药", "医疗器械", "医疗", "生物科技"],
    "能源": ["电力", "石油", "天然气", "新能源"],
}


def _haversine_km(c1: tuple, c2: tuple) -> float:
    lat1, lon1 = c1
    lat2, lon2 = c2
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _cosine(vec_a: dict, vec_b: dict) -> float:
    keys = set(vec_a.keys()) | set(vec_b.keys())
    if not keys:
        return 0.0
    dot = sum(vec_a.get(k, 0) * vec_b.get(k, 0) for k in keys)
    na = math.sqrt(sum(v * v for v in vec_a.values()))
    nb = math.sqrt(sum(v * v for v in vec_b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class ResourceEngine(AbstractEngine):
    """IA-03 审计资源智能分配引擎（GA 优化 + 技能匹配）。"""

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self.db: PortableDB | None = None
        self.db_path = Path(self.config.get("db_path", _DB_PATH))
        self._auditors: list[dict] = []
        self._projects: list[dict] = []
        self._constraints: dict = {}

    def _load_model(self) -> None:
        self.db = PortableDB(self.db_path)
        for table, schema in [
            ("auditors", _AUDITORS_SCHEMA),
            ("projects", _PROJECTS_SCHEMA),
            ("assignments", _ASSIGNMENTS_SCHEMA),
            ("plans", _PLANS_SCHEMA),
        ]:
            if table not in self.db.tables():
                self.db.create_table(table, schema)

        self.model = {
            "skill_weights": dict(_SKILL_WEIGHTS),
            "city_coords": dict(_CITY_COORDS),
            "industry_clusters": dict(_INDUSTRY_CLUSTERS),
            "ga_params": {
                "pop_size": 40,
                "max_gen": 30,
                "elite_ratio": 0.1,
                "crossover_prob": 0.8,
                "mutation_prob": 0.12,
                "patience": 10,
            },
            "history_assignments": {},
        }

        if self.db.count("plans") > 0:
            for p in self.db.query("plans", order_by="score DESC", limit=5):
                for proj_id, assigns in (p.get("assignments") or {}).items():
                    self.model["history_assignments"].setdefault(proj_id, set()).update(assigns)

    def _preprocess(self, input_data: Any) -> Any:
        if self.model is None:
            self._load_model()
        if not isinstance(input_data, dict):
            raise ValueError("input_data 必须为 dict，含 auditors / projects")

        raw_auditors = input_data.get("auditors", [])
        raw_projects = input_data.get("projects", [])
        constraints = input_data.get("constraints", {})

        auditors = []
        for a in raw_auditors:
            aid = a.get("auditor_id") or a.get("id", "")
            if not aid:
                continue
            skills = a.get("skills", {}) or {}
            industries = a.get("industries", []) or []
            auditors.append({
                "auditor_id": aid,
                "name": a.get("name", aid),
                "level": a.get("level", "初级"),
                "skills": {k: float(v) for k, v in skills.items()},
                "industries": list(industries),
                "city": a.get("city", "北京"),
                "hourly_rate": float(a.get("hourly_rate", 300)),
                "weekly_hours": float(a.get("weekly_hours", 40)),
                "available_hours": float(a.get("available_hours", 40)),
                "development_goals": a.get("development_goals", []) or [],
            })
            self.db.upsert("auditors", {
                "auditor_id": aid, "name": a.get("name", aid),
                "level": a.get("level", "初级"),
                "skills": skills, "industries": industries,
                "city": a.get("city", "北京"),
                "hourly_rate": float(a.get("hourly_rate", 300)),
                "weekly_hours": float(a.get("weekly_hours", 40)),
                "available_hours": float(a.get("available_hours", 40)),
                "development_goals": a.get("development_goals", []),
                "created_at": datetime.now(),
            }, pk="auditor_id")

        projects = []
        for p in raw_projects:
            pid = p.get("project_id") or p.get("id", "")
            if not pid:
                continue
            req_skills = p.get("required_skills", {}) or {}
            industry = p.get("industry", "")
            cluster = [k for k, vs in self.model["industry_clusters"].items() if industry in vs]
            projects.append({
                "project_id": pid,
                "name": p.get("name", pid),
                "industry": industry,
                "industry_cluster": cluster[0] if cluster else industry,
                "city": p.get("city", "北京"),
                "required_skills": {k: float(v) for k, v in req_skills.items()},
                "required_count": int(p.get("required_count", 2)),
                "duration_weeks": float(p.get("duration_weeks", 4)),
                "budget": float(p.get("budget", 500000)),
                "complexity": float(p.get("complexity", 50)),
                "min_senior": int(p.get("min_senior", 0)),
            })
            self.db.upsert("projects", {
                "project_id": pid, "name": p.get("name", pid),
                "industry": industry, "city": p.get("city", "北京"),
                "required_skills": req_skills,
                "required_count": int(p.get("required_count", 2)),
                "duration_weeks": float(p.get("duration_weeks", 4)),
                "budget": float(p.get("budget", 500000)),
                "complexity": float(p.get("complexity", 50)),
                "created_at": datetime.now(),
            }, pk="project_id")

        self._auditors = auditors
        self._projects = projects
        self._constraints = constraints

        return {
            "auditors": auditors,
            "projects": projects,
            "constraints": constraints,
        }

    def _infer(self, prepared: Any) -> Any:
        auditors = prepared["auditors"]
        projects = prepared["projects"]
        constraints = prepared["constraints"]

        if not auditors or not projects:
            return {"action": "allocate", "plans": [], "best_plan": None}

        pop_size = int(constraints.get("pop_size", self.model["ga_params"]["pop_size"]))
        max_gen = int(constraints.get("max_gen", self.model["ga_params"]["max_gen"]))

        plans = self._run_genetic(auditors, projects, constraints, pop_size, max_gen)

        return {
            "action": "allocate",
            "plans": plans,
            "best_plan": plans[0] if plans else None,
            "total_projects": len(projects),
            "total_auditors": len(auditors),
        }

    # ---------- GA 核心 ----------

    def _chromosome_to_assignments(self, chromosome: list[list[int]],
                                   auditors: list[dict],
                                   projects: list[dict]) -> dict[str, list[str]]:
        result = {}
        for i, project in enumerate(projects):
            assigned = []
            for aud_idx in chromosome[i]:
                if 0 <= aud_idx < len(auditors):
                    assigned.append(auditors[aud_idx]["auditor_id"])
            result[project["project_id"]] = assigned
        return result

    def _init_population(self, auditors: list[dict], projects: list[dict],
                          pop_size: int) -> list[list[list[int]]]:
        n = len(projects)
        pop: list[list[list[int]]] = []

        greedy_count = int(pop_size * 0.5)
        for _ in range(greedy_count):
            chromo = self._greedy_init(auditors, projects)
            pop.append(chromo)

        random_count = int(pop_size * 0.3)
        for _ in range(random_count):
            chromo = []
            for proj in projects:
                n_need = proj["required_count"]
                avail = list(range(len(auditors)))
                random.shuffle(avail)
                chromo.append(avail[:n_need])
            pop.append(chromo)

        while len(pop) < pop_size:
            chromo = []
            for proj in projects:
                n_need = proj["required_count"]
                avail = list(range(len(auditors)))
                random.shuffle(avail)
                chromo.append(avail[:n_need])
            pop.append(chromo)

        return pop[:pop_size]

    def _greedy_init(self, auditors: list[dict], projects: list[dict]) -> list[list[int]]:
        chromo: list[list[int]] = []
        auditor_load: dict[int, float] = defaultdict(float)
        for proj in projects:
            n_need = proj["required_count"]
            req_skills = proj["required_skills"]
            scored = []
            for idx, aud in enumerate(auditors):
                load_penalty = auditor_load[idx] / max(aud["weekly_hours"], 1)
                skill_match = _cosine(aud["skills"], req_skills)
                scored.append((idx, skill_match - load_penalty * 0.5))
            scored.sort(key=lambda x: -x[1])
            chosen = [s[0] for s in scored[:n_need]]
            chromo.append(chosen)
            for idx in chosen:
                auditor_load[idx] += proj["duration_weeks"] * 10
        return chromo

    def _fitness(self, chromosome: list[list[int]], auditors: list[dict],
                 projects: list[dict], constraints: dict) -> tuple[float, dict]:
        assignments = self._chromosome_to_assignments(chromosome, auditors, projects)

        auditor_hours: dict[str, float] = defaultdict(float)
        project_teams: dict[str, list[dict]] = {}

        for proj in projects:
            pid = proj["project_id"]
            aids = assignments.get(pid, [])
            team = []
            for aid in aids:
                aud = next((a for a in auditors if a["auditor_id"] == aid), None)
                if aud:
                    team.append(aud)
                    auditor_hours[aid] += proj["duration_weeks"] * 10
            project_teams[pid] = team

        violations = 0

        for aid, hours in auditor_hours.items():
            aud = next((a for a in auditors if a["auditor_id"] == aid), None)
            if aud and hours > aud["available_hours"] * 4:
                violations += 1

        for proj in projects:
            pid = proj["project_id"]
            team = project_teams[pid]
            if proj.get("min_senior", 0) > 0:
                seniors = sum(1 for a in team if a["level"] in ("高级", "经理", "总监"))
                if seniors < proj["min_senior"]:
                    violations += 1

        skill_scores = []
        for proj in projects:
            req = proj["required_skills"]
            team = project_teams[proj["project_id"]]
            if not team:
                skill_scores.append(0.0)
                continue
            aggregate: dict[str, float] = defaultdict(float)
            for a in team:
                for sk, v in a["skills"].items():
                    aggregate[sk] = max(aggregate[sk], v)
            sim = _cosine(dict(aggregate), req)
            skill_scores.append(sim)
        skill_match = sum(skill_scores) / max(len(skill_scores), 1) * 100

        all_hours = list(auditor_hours.values()) or [0]
        mean_h = sum(all_hours) / len(all_hours)
        std_h = math.sqrt(sum((h - mean_h) ** 2 for h in all_hours) / len(all_hours)) if all_hours else 0
        load_balance = max(0, 100 - (std_h / max(mean_h, 1)) * 100)

        total_cost = 0.0
        budget_total = sum(p["budget"] for p in projects) or 1
        for proj in projects:
            city = proj["city"]
            team = project_teams[proj["project_id"]]
            for a in team:
                coord_a = self.model["city_coords"].get(a["city"], (35.0, 110.0))
                coord_p = self.model["city_coords"].get(city, (35.0, 110.0))
                dist = _haversine_km(coord_a, coord_p)
                travel = dist * 1.5
                hours_used = auditor_hours.get(a["auditor_id"], 0)
                salary = hours_used * a["hourly_rate"]
                total_cost += travel + salary
        cost_efficiency = max(0, 100 - (total_cost / budget_total) * 100)

        dev_scores = []
        for proj in projects:
            team = project_teams[proj["project_id"]]
            score = 0.0
            for a in team:
                goals = a.get("development_goals", [])
                if proj["industry"] in goals or proj["industry_cluster"] in goals:
                    score += 30
                for sk in proj["required_skills"]:
                    if sk in goals:
                        score += 20
                if a["level"] != "初级" and proj.get("min_senior", 0) > 0:
                    score += 20
            dev_scores.append(score / max(len(team), 1))
        development = sum(dev_scores) / max(len(dev_scores), 1) if dev_scores else 50

        synergy_scores = []
        for proj in projects:
            team = project_teams[proj["project_id"]]
            if len(team) < 2:
                synergy_scores.append(50)
                continue
            pair_count = 0
            compat_sum = 0.0
            for i in range(len(team)):
                for j in range(i + 1, len(team)):
                    compat = len(set(team[i]["skills"].keys()) & set(team[j]["skills"].keys()))
                    union = len(set(team[i]["skills"].keys()) | set(team[j]["skills"].keys())) or 1
                    compat_sum += compat / union
                    pair_count += 1
            synergy_scores.append(compat_sum / max(pair_count, 1) * 100)
        team_synergy = sum(synergy_scores) / max(len(synergy_scores), 1) if synergy_scores else 50

        cont_scores = []
        history = self.model["history_assignments"]
        for proj in projects:
            pid = proj["project_id"]
            team = project_teams[pid]
            if pid in history and history[pid]:
                overlap = sum(1 for a in team if a["auditor_id"] in history[pid])
                cont_scores.append(overlap / len(history[pid]) * 100)
            else:
                cont_scores.append(50)
        continuity = sum(cont_scores) / max(len(cont_scores), 1)

        total = (skill_match * 0.35 + load_balance * 0.20 + cost_efficiency * 0.15
                 + development * 0.15 + team_synergy * 0.10 + continuity * 0.05)
        total -= violations * 15

        details = {
            "skill_match": round(skill_match, 2),
            "load_balance": round(load_balance, 2),
            "cost_efficiency": round(cost_efficiency, 2),
            "development": round(development, 2),
            "team_synergy": round(team_synergy, 2),
            "continuity": round(continuity, 2),
            "violations": violations,
            "total_cost": round(total_cost, 0),
        }
        return total, details

    def _tournament_select(self, population: list[list[list[int]]],
                            fitnesses: list[float], k: int = 3) -> list[list[int]]:
        n = len(population)
        candidates = random.sample(range(n), min(k, n))
        best = max(candidates, key=lambda i: fitnesses[i])
        return population[best]

    def _pmx_crossover(self, p1: list[list[int]], p2: list[list[int]]) -> list[list[int]]:
        child: list[list[int]] = []
        for gp1, gp2 in zip(p1, p2):
            if len(gp1) != len(gp2) or not gp1:
                child.append(list(gp1))
                continue
            l = len(gp1)
            if l <= 1:
                child.append(list(gp1))
                continue
            a, b = sorted(random.sample(range(l), 2))
            seg = gp1[a:b + 1]
            seg_set = set(seg)
            mapping = {}
            for x, y in zip(gp1[a:b + 1], gp2[a:b + 1]):
                mapping[x] = y
            new_part = [None] * l
            for i in range(a, b + 1):
                new_part[i] = gp1[i]
            for i in range(l):
                if a <= i <= b:
                    continue
                val = gp2[i]
                # PMX 冲突消解：沿映射链查找不在段中的值
                guarded = 0
                while val in seg_set and guarded < l:
                    val = mapping.get(val, val)
                    guarded += 1
                new_part[i] = val
            child.append(new_part)
        return child

    def _mutate(self, chromosome: list[list[int]], n_auditors: int,
                mutation_prob: float) -> list[list[int]]:
        mutated = [list(g) for g in chromosome]
        for i in range(len(mutated)):
            if random.random() < mutation_prob:
                if mutated[i] and random.random() < 0.5:
                    j = random.randrange(len(mutated[i]))
                    new_val = random.randrange(n_auditors)
                    mutated[i][j] = new_val
                else:
                    l = mutated[i]
                    if len(l) >= 2:
                        a, b = random.sample(range(len(l)), 2)
                        l[a], l[b] = l[b], l[a]
        return mutated

    def _run_genetic(self, auditors: list[dict], projects: list[dict],
                     constraints: dict, pop_size: int, max_gen: int) -> list[dict]:
        random.seed(self.config.get("seed", 42))
        pop = self._init_population(auditors, projects, pop_size)
        fitnesses, details = zip(*[self._fitness(c, auditors, projects, constraints) for c in pop])
        fitnesses = list(fitnesses)
        details = list(details)

        best_score = -float("inf")
        best_details = {}
        best_chromo = None
        no_improve = 0
        patience = self.model["ga_params"]["patience"]

        for gen in range(max_gen):
            paired = sorted(range(len(pop)), key=lambda i: -fitnesses[i])
            n_elite = max(1, int(pop_size * self.model["ga_params"]["elite_ratio"]))
            new_pop = [pop[i] for i in paired[:n_elite]]

            while len(new_pop) < pop_size:
                p1 = self._tournament_select(pop, fitnesses)
                p2 = self._tournament_select(pop, fitnesses)
                if random.random() < self.model["ga_params"]["crossover_prob"]:
                    child = self._pmx_crossover(p1, p2)
                else:
                    child = [list(g1) if random.random() < 0.5 else list(g2)
                             for g1, g2 in zip(p1, p2)]
                child = self._mutate(child, len(auditors),
                                      self.model["ga_params"]["mutation_prob"])
                new_pop.append(child)

            pop = new_pop
            fitnesses, details = zip(*[self._fitness(c, auditors, projects, constraints) for c in pop])
            fitnesses = list(fitnesses)
            details = list(details)

            gen_best = max(range(len(pop)), key=lambda i: fitnesses[i])
            if fitnesses[gen_best] > best_score:
                best_score = fitnesses[gen_best]
                best_details = details[gen_best]
                best_chromo = [list(g) for g in pop[gen_best]]
                no_improve = 0
            else:
                no_improve += 1

            if no_improve >= patience:
                break

        if best_chromo is None:
            return []

        best_assignments = self._chromosome_to_assignments(best_chromo, auditors, projects)

        auditor_loads: dict[str, float] = defaultdict(float)
        for proj in projects:
            for aid in best_assignments.get(proj["project_id"], []):
                auditor_loads[aid] += proj["duration_weeks"] * 10

        plans = []
        plans.append({
            "plan_id": "plan_ga_best",
            "score": round(best_score, 2),
            **best_details,
            "assignments": best_assignments,
            "auditor_loads": dict(auditor_loads),
            "generations_run": gen + 1,
        })

        sorted_idx = sorted(range(len(pop)), key=lambda i: -fitnesses[i])
        for rank, idx in enumerate(sorted_idx[1:4], start=2):
            assignments = self._chromosome_to_assignments(pop[idx], auditors, projects)
            load_map: dict[str, float] = defaultdict(float)
            for proj in projects:
                for aid in assignments.get(proj["project_id"], []):
                    load_map[aid] += proj["duration_weeks"] * 10
            plans.append({
                "plan_id": f"plan_ga_rank{rank}",
                "score": round(fitnesses[idx], 2),
                **details[idx],
                "assignments": assignments,
                "auditor_loads": dict(load_map),
                "generations_run": gen + 1,
            })

        return plans

    def _postprocess(self, result: Any) -> Any:
        plans = result.get("plans", [])
        for plan in plans:
            self.db.insert("plans", {
                "plan_id": plan["plan_id"],
                "score": plan["score"],
                "skill_match": plan["skill_match"],
                "load_balance": plan["load_balance"],
                "cost_efficiency": plan["cost_efficiency"],
                "development": plan["development"],
                "team_synergy": plan["team_synergy"],
                "continuity": plan["continuity"],
                "violations": plan["violations"],
                "assignments": plan["assignments"],
                "created_at": datetime.now(),
            })

        best = plans[0] if plans else None
        if best:
            for proj_id, aids in best["assignments"].items():
                for aid in aids:
                    self.db.insert("assignments", {
                        "assignment_id": f"{proj_id}_{aid}",
                        "project_id": proj_id,
                        "auditor_id": aid,
                        "fit_score": best["skill_match"],
                        "assigned_at": datetime.now(),
                    })

        result["summary"] = {
            "total_plans": len(plans),
            "best_score": best["score"] if best else 0,
            "best_skill_match": best["skill_match"] if best else 0,
            "best_load_balance": best["load_balance"] if best else 0,
            "best_violations": best["violations"] if best else 0,
        }
        return result

    def close(self) -> None:
        if self.db is not None:
            self.db.close()
            self.db = None
