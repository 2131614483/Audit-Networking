"""多模态数据对齐层（DataAligner）。

审计智能化平台多源数据对齐基础设施。在 78 个模块组网执行前，统一对齐：
  - 跨数据源实体（同名不同 ID / 同 ID 不同名）→ EntityAligner
  - 多源时间字段（字符串 / 时间戳 / 事件流）→ TimeAligner
  - 多模态数据（文本 / 图片 / 视频 / 时序 / 图）→ ModalAligner

纯 stdlib 实现（difflib / datetime / re / hashlib / dataclasses），
不依赖第三方库，与 modules/shared/contract.py 的 TypedField.modality 枚举对齐。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Callable

# ----------------------------------------------------------------------
# 常量
# ----------------------------------------------------------------------

# 上海时区（+08:00），数据对齐时假设输入为该时区
_SHANGHAI_TZ: timezone = timezone(timedelta(hours=8))
_UTC: timezone = timezone.utc

# 公司后缀（规范化名称时去除，按长度降序匹配避免误伤）
_COMPANY_SUFFIXES: list[str] = sorted(
    [
        "股份有限公司", "有限责任公司", "有限公司",
        "股份", "集团", "控股", "科技", "实业",
    ],
    key=len,
    reverse=True,
)

# USCC 字符集（GB 32100-2015）：0-9 + A-Z 去除 I/O/S/V/Z，共 31 个
_USCC_CHARS: str = "0123456789ABCDEFGHJKLMNPQRTUWXY"
# USCC 加权因子（前 17 位）
_USCC_WEIGHTS: tuple[int, ...] = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)


# ======================================================================
# 实体对齐数据结构
# ======================================================================


@dataclass
class EntityRecord:
    """待对齐的实体记录（来自单一数据源的一条实体描述）。

    每条记录描述某个源系统（ERP / 银行 / 合同 / 舆情 等）观察到的实体，
    通过 EntityAligner 跨源对齐后归并到 EntityCluster。

    Attributes:
        entity_id: 源系统中的实体 ID。
        source: 数据来源标签（ERP / 银行 / 合同 / 舆情 ...）。
        name: 实体名称（原始字符串）。
        uscc: 统一社会信用代码（18 位），可为空。
        aliases: 别名列表（曾用名、简称、舆情称呼等）。
        attributes: 其他属性（法人、地址、股东等），用于软匹配辅助判断。
    """

    entity_id: str
    source: str
    name: str
    uscc: str = ""
    aliases: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)


@dataclass
class EntityCluster:
    """对齐后的实体簇（多个 EntityRecord 指向同一现实实体）。

    Attributes:
        canonical_id: 规范化实体 ID（如 ENT-0001）。
        canonical_name: 规范化名称（去后缀后最长的名称）。
        uscc: 簇内最可信的统一信用代码（有效 USCC 优先）。
        members: 所有指向该实体的源记录。
        match_confidence: 匹配置信度 0-1（硬匹配=1.0，软匹配=最大综合分）。
        aliases: 合并后的所有别名（去重，不含 canonical_name）。
    """

    canonical_id: str
    canonical_name: str
    uscc: str
    members: list[EntityRecord]
    match_confidence: float
    aliases: list[str] = field(default_factory=list)


# ======================================================================
# 实体对齐器
# ======================================================================


class EntityAligner:
    """跨源实体对齐器。

    对齐策略三步走：
      a) 硬匹配：USCC 完全一致（18 位 + 校验位验证）→ 同一实体，confidence=1.0
      b) 软匹配：名称相似度（编辑距离归一化 + 去后缀精确匹配）+ 属性交集得分
         → confidence = 0.6*name_sim + 0.4*attr_overlap，阈值 > 0.75 判为同实体
      c) 传递闭包：A~B, B~C → A~C（并查集合并簇）
    """

    class _UnionFind:
        """并查集（内部类）：带按秩合并 + 路径压缩，用于实体传递闭包。"""

        def __init__(self, n: int) -> None:
            self.parent: list[int] = list(range(n))
            self.rank: list[int] = [0] * n

        def find(self, x: int) -> int:
            """查找根节点（路径压缩）。"""
            root = x
            while self.parent[root] != root:
                root = self.parent[root]
            while self.parent[x] != root:
                self.parent[x], x = root, self.parent[x]
            return root

        def union(self, x: int, y: int) -> None:
            """合并两个集合（按秩合并）。"""
            rx, ry = self.find(x), self.find(y)
            if rx == ry:
                return
            if self.rank[rx] < self.rank[ry]:
                rx, ry = ry, rx
            self.parent[ry] = rx
            if self.rank[rx] == self.rank[ry]:
                self.rank[rx] += 1

    # 软匹配阈值
    _SOFT_THRESHOLD: float = 0.75
    # 名称相似度权重
    _NAME_WEIGHT: float = 0.6
    _ATTR_WEIGHT: float = 0.4

    def align(self, entities: list[EntityRecord]) -> list[EntityCluster]:
        """对齐实体记录，返回规范化实体簇列表。

        Args:
            entities: 来自多数据源的实体记录列表。

        Returns:
            对齐后的实体簇列表，按簇中最小原始索引排序，canonical_id 形如 ENT-0001。
        """
        if not entities:
            return []
        n = len(entities)
        uf = self._UnionFind(n)
        # 预清洗 USCC
        usccs = [self._clean_uscc(e.uscc) for e in entities]
        # 两两比对：硬匹配 / 软匹配
        for i in range(n):
            for j in range(i + 1, n):
                if uf.find(i) == uf.find(j):
                    continue
                if self._is_hard_match(usccs[i], usccs[j]):
                    uf.union(i, j)
                    continue
                score = self._soft_score(entities[i], entities[j])
                if score > self._SOFT_THRESHOLD:
                    uf.union(i, j)
        # 按簇分组
        groups: dict[int, list[int]] = {}
        for i in range(n):
            root = uf.find(i)
            groups.setdefault(root, []).append(i)
        # 构建 EntityCluster
        clusters: list[EntityCluster] = []
        for idx, (_, member_indices) in enumerate(
            sorted(groups.items(), key=lambda kv: min(kv[1])), start=1
        ):
            members = [entities[i] for i in sorted(member_indices)]
            cluster_uscc = self._pick_uscc(members)
            canonical_name = self._pick_canonical_name(members)
            aliases = self._merge_aliases(members, canonical_name)
            confidence = self._cluster_confidence(members)
            clusters.append(
                EntityCluster(
                    canonical_id=f"ENT-{idx:04d}",
                    canonical_name=canonical_name,
                    uscc=cluster_uscc,
                    members=members,
                    match_confidence=confidence,
                    aliases=aliases,
                )
            )
        return clusters

    # ------------------------------------------------------------------
    # 公开辅助方法
    # ------------------------------------------------------------------

    def _normalize_name(self, name: str) -> str:
        """名称规范化：去除空白（含全角空格）+ 常见公司后缀。

        Args:
            name: 原始名称。

        Returns:
            规范化后的名称（仅去除一个最长匹配后缀，避免过度截断）。
        """
        if not name:
            return ""
        s = re.sub(r"[\s\u3000]+", "", str(name))
        for suf in _COMPANY_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                s = s[: -len(suf)]
                break
        return s

    def _name_similarity(self, a: str, b: str) -> float:
        """名称相似度：normalize 后精确匹配=1.0，否则编辑距离归一化。

        Args:
            a, b: 两个原始名称字符串。

        Returns:
            相似度 0.0-1.0。
        """
        na = self._normalize_name(a)
        nb = self._normalize_name(b)
        if not na or not nb:
            return 0.0
        if na == nb:
            return 1.0
        return SequenceMatcher(None, na, nb).ratio()

    def _attr_overlap(self, a: dict, b: dict) -> float:
        """属性交集得分（Jaccard：键值对交集 / 并集）。

        Args:
            a, b: 两个属性字典。

        Returns:
            交集得分 0.0-1.0。
        """
        if not a or not b:
            return 0.0
        sa = {(k, str(v)) for k, v in a.items()}
        sb = {(k, str(v)) for k, v in b.items()}
        union = sa | sb
        if not union:
            return 0.0
        return len(sa & sb) / len(union)

    def _clean_uscc(self, uscc: str) -> str:
        """USCC 清洗：去空格、转大写、18 位 + 校验位验证。

        Args:
            uscc: 原始 USCC 字符串。

        Returns:
            清洗后的 18 位 USCC；若长度/字符/校验位非法则返回空字符串。
        """
        if not uscc:
            return ""
        cleaned = re.sub(r"\s+", "", str(uscc)).upper()
        if len(cleaned) != 18:
            return ""
        total = 0
        for i in range(17):
            idx = _USCC_CHARS.find(cleaned[i])
            if idx < 0:
                return ""
            total += idx * _USCC_WEIGHTS[i]
        check_idx = (31 - total % 31) % 31
        if _USCC_CHARS[check_idx] != cleaned[17]:
            return ""
        return cleaned

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _is_hard_match(self, uscc_a: str, uscc_b: str) -> bool:
        """硬匹配：两个有效 USCC 完全一致。"""
        return bool(uscc_a) and bool(uscc_b) and uscc_a == uscc_b

    def _pair_name_sim(self, a: EntityRecord, b: EntityRecord) -> float:
        """两个实体的名称相似度（名称+别名两两组合取最大值）。"""
        a_names = [a.name] + list(a.aliases)
        b_names = [b.name] + list(b.aliases)
        best = 0.0
        for na in a_names:
            for nb in b_names:
                s = self._name_similarity(na, nb)
                if s > best:
                    best = s
        return best

    def _soft_score(self, a: EntityRecord, b: EntityRecord) -> float:
        """软匹配综合分：0.6*name_sim + 0.4*attr_overlap。"""
        name_sim = self._pair_name_sim(a, b)
        attr = self._attr_overlap(a.attributes, b.attributes)
        return self._NAME_WEIGHT * name_sim + self._ATTR_WEIGHT * attr

    def _pick_uscc(self, members: list[EntityRecord]) -> str:
        """选择簇内最可信 USCC（第一个有效 USCC）。"""
        for m in members:
            cleaned = self._clean_uscc(m.uscc)
            if cleaned:
                return cleaned
        return ""

    def _pick_canonical_name(self, members: list[EntityRecord]) -> str:
        """选择规范化名称：normalize 后最长的名称（返回 normalized 形式）。"""
        best = self._normalize_name(members[0].name) or members[0].name
        for m in members[1:]:
            nm = self._normalize_name(m.name)
            if len(nm) > len(best):
                best = nm
        return best

    def _merge_aliases(self, members: list[EntityRecord], canonical_name: str) -> list[str]:
        """合并簇内所有别名（去重，排除 canonical_name 及其 normalized 形式）。"""
        aliases: list[str] = []
        seen = {self._normalize_name(canonical_name), canonical_name}
        for m in members:
            for a in [m.name] + list(m.aliases):
                if not a:
                    continue
                if a in seen or self._normalize_name(a) in seen:
                    continue
                seen.add(a)
                seen.add(self._normalize_name(a))
                aliases.append(a)
        return aliases

    def _cluster_confidence(self, members: list[EntityRecord]) -> float:
        """簇置信度：单成员=1.0；任一对硬匹配=1.0；否则取最大软匹配分。"""
        if len(members) == 1:
            return 1.0
        usccs = [self._clean_uscc(m.uscc) for m in members]
        max_score = 0.0
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                if self._is_hard_match(usccs[i], usccs[j]):
                    return 1.0
                score = self._soft_score(members[i], members[j])
                if score > max_score:
                    max_score = score
        return max_score


# ======================================================================
# 时间对齐器
# ======================================================================


class TimeAligner:
    """时间对齐器：多源时间格式 → ISO8601 UTC + 业务期间。

    支持格式：
      - "2025-06" / "2025/06" / "202601"（YYYYMM 6 位数字）
      - "2025-06-15T10:30:00" / "2025-06-15 10:30:00" / "2025-06-15" / "2025/06/15"
      - Unix 时间戳（秒，≥10 位数字）
      - 中文 "2025年6月" / "2025年6月15日"

    时区归一：假设输入为 Asia/Shanghai (+08:00)，输出 UTC。
    重采样对齐：按 target_grain (day/week/month/quarter/year) 截断。
    """

    _GRAINS: frozenset = frozenset({"day", "week", "month", "quarter", "year"})

    def align(
        self,
        records: list[dict],
        time_field: str = "event_time",
        target_grain: str = "month",
    ) -> list[dict]:
        """对齐时间字段。

        Args:
            records: 记录列表，每条 dict 含 time_field 字段。
            time_field: 时间字段名，默认 "event_time"。
            target_grain: 目标粒度，day/week/month/quarter/year。

        Returns:
            新的记录列表（浅拷贝），每条增加统一字段：
              - event_time: ISO8601 UTC 时间戳（粒度起点）
              - period: 业务期间字符串（如 "2025-06"）
        """
        if target_grain not in self._GRAINS:
            raise ValueError(
                f"target_grain 非法: {target_grain}，合法值: {sorted(self._GRAINS)}"
            )
        aligned: list[dict] = []
        for rec in records:
            new_rec = dict(rec)
            raw = rec.get(time_field)
            dt = self._parse_time(raw)
            if dt is None:
                new_rec["event_time"] = None
                new_rec["period"] = None
            else:
                # 在源时区（上海）截断到粒度，再转 UTC 输出
                dt_sh = (
                    dt.astimezone(_SHANGHAI_TZ)
                    if dt.tzinfo
                    else dt.replace(tzinfo=_SHANGHAI_TZ)
                )
                truncated_sh = self._truncate_to_grain(dt_sh, target_grain)
                truncated_utc = truncated_sh.astimezone(_UTC)
                new_rec["event_time"] = truncated_utc.isoformat()
                new_rec["period"] = self._period_str(truncated_sh, target_grain)
            aligned.append(new_rec)
        return aligned

    def _parse_time(self, raw: Any) -> datetime | None:
        """解析多种时间格式为 datetime（带上海时区）。"""
        if raw is None:
            return None
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=_SHANGHAI_TZ)
        if isinstance(raw, (int, float)):
            try:
                return datetime.fromtimestamp(float(raw), tz=_UTC)
            except (ValueError, OSError):
                return None
        s = str(raw).strip()
        if not s:
            return None
        # Unix 时间戳（纯数字，≥10 位）
        if s.isdigit() and len(s) >= 10:
            try:
                return datetime.fromtimestamp(int(s), tz=_UTC)
            except (ValueError, OSError):
                pass
        # 中文格式：2025年6月15日
        m = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?$", s)
        if m:
            try:
                return datetime(
                    int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=_SHANGHAI_TZ
                )
            except ValueError:
                return None
        # 中文格式：2025年6月
        m = re.match(r"^(\d{4})年(\d{1,2})月$", s)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=_SHANGHAI_TZ)
            except ValueError:
                return None
        # YYYY-MM / YYYY/MM（仅年月）
        m = re.match(r"^(\d{4})[-/](\d{1,2})$", s)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), 1, tzinfo=_SHANGHAI_TZ)
            except ValueError:
                return None
        # YYYYMM（6 位数字，年月）
        if re.match(r"^\d{6}$", s):
            try:
                return datetime(int(s[:4]), int(s[4:6]), 1, tzinfo=_SHANGHAI_TZ)
            except ValueError:
                return None
        # 标准格式逐一尝试
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d",
        ):
            try:
                return datetime.strptime(s, fmt).replace(tzinfo=_SHANGHAI_TZ)
            except ValueError:
                continue
        # 兜底：ISO 解析
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=_SHANGHAI_TZ)
        except ValueError:
            return None

    def _truncate_to_grain(self, dt: datetime, grain: str) -> datetime:
        """在指定时区内将 datetime 截断到目标粒度。"""
        if grain == "year":
            return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        if grain == "quarter":
            q_month = (dt.month - 1) // 3 * 3 + 1
            return dt.replace(month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        if grain == "month":
            return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if grain == "week":
            # ISO 周，周一为起始
            days_since_mon = dt.weekday()
            return (dt - timedelta(days=days_since_mon)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        # day
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)

    def _period_str(self, dt: datetime, grain: str) -> str:
        """生成业务期间字符串。"""
        if grain == "year":
            return f"{dt.year}"
        if grain == "quarter":
            q = (dt.month - 1) // 3 + 1
            return f"{dt.year}-Q{q}"
        if grain == "month":
            return f"{dt.year:04d}-{dt.month:02d}"
        if grain == "week":
            iso = dt.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        # day
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"


# ======================================================================
# 模态对齐器
# ======================================================================


class ModalAligner:
    """多模态对齐器（框架 + 简化实现，不依赖外部模型）。

    提供模态编码、跨模态检索、多模态融合三类能力。当前实现基于关键词重叠
    与哈希向量，用于演示对齐机制；可由 register_encoder 注入真实编码器替换。
    """

    _VECTOR_DIM: int = 16

    def __init__(self) -> None:
        self._encoders: dict[str, Callable[[dict], list[float]]] = {}

    def register_encoder(self, modality: str, encoder: Callable[[dict], list[float]]) -> None:
        """注册指定模态的编码器（替换默认哈希向量实现）。"""
        self._encoders[modality] = encoder

    def encode(self, record: dict, modality: str) -> list[float]:
        """将记录编码为向量（默认简化哈希向量，非真实 embedding）。"""
        if modality in self._encoders:
            return self._encoders[modality](record)
        text = self._extract_text(record, modality)
        return self._hash_vector(text, self._VECTOR_DIM)

    def cross_modal_search(
        self,
        text_query: str,
        multimodal_store: list[dict],
    ) -> list[dict]:
        """跨模态检索：基于关键词重叠返回匹配记录（按相关度降序）。

        Args:
            text_query: 文本查询。
            multimodal_store: 多模态记录列表。

        Returns:
            命中记录列表（相关度 > 0），按相关度降序。
        """
        query_tokens = self._tokenize(text_query)
        if not query_tokens:
            return []
        scored: list[tuple[float, dict]] = []
        for rec in multimodal_store:
            rec_text = " ".join(str(v) for v in rec.values())
            rec_tokens = self._tokenize(rec_text)
            if not rec_tokens:
                scored.append((0.0, rec))
                continue
            overlap = len(query_tokens & rec_tokens)
            score = overlap / len(query_tokens)
            scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for s, r in scored if s > 0]

    def align_fusion(self, records: list[dict]) -> list[dict]:
        """多模态融合：同一实体的文本/图片/视频记录合并为融合特征。

        按 entity_id（或 canonical_id）分组，合并所有模态记录为一个融合向量。

        Args:
            records: 多模态记录列表，每条含 entity_id / modality 字段。

        Returns:
            融合记录列表，每条含 entity_id / modalities / fused_vector / fused_text。
        """
        groups: dict[str, list[dict]] = {}
        order: list[str] = []
        for rec in records:
            eid = str(rec.get("entity_id", rec.get("canonical_id", "")))
            if eid not in groups:
                groups[eid] = []
                order.append(eid)
            groups[eid].append(rec)
        fused: list[dict] = []
        for eid in order:
            group = groups[eid]
            modalities: list[str] = []
            for r in group:
                m = r.get("modality", "text")
                if m not in modalities:
                    modalities.append(m)
            merged_text = " ".join(
                self._extract_text(r, r.get("modality", "text")) for r in group
            ).strip()
            fused_vec = self._hash_vector(merged_text, self._VECTOR_DIM)
            fused.append(
                {
                    "entity_id": eid,
                    "modalities": modalities,
                    "fused_vector": fused_vec,
                    "fused_text": merged_text,
                    "record_count": len(group),
                }
            )
        return fused

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _extract_text(self, record: dict, modality: str) -> str:
        """从记录中提取指定模态的文本表示。"""
        if modality == "text":
            return str(record.get("text", record.get("content", record.get("title", ""))))
        if modality == "image":
            return str(record.get("caption", record.get("ocr_text", record.get("filename", ""))))
        if modality == "video":
            return str(record.get("transcript", record.get("title", record.get("caption", ""))))
        if modality == "audio":
            return str(record.get("transcript", record.get("title", "")))
        return str(record.get("text", record.get("content", "")))

    def _tokenize(self, text: str) -> set[str]:
        """简易分词：英文/数字单词 + 中文单字（小写化）。"""
        if not text:
            return set()
        tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", str(text).lower())
        return {t for t in tokens if t}

    def _hash_vector(self, text: str, dim: int) -> list[float]:
        """将文本哈希为固定维度向量（L2 归一化）。"""
        vec = [0.0] * dim
        tokens = self._tokenize(text)
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            vec[h % dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ======================================================================
# 统一对齐入口
# ======================================================================


class DataAligner:
    """统一对齐入口：编排实体 / 时间 / 模态三类对齐。

    典型输入：
        {
            "entities": [EntityRecord(...), ...],
            "time_records": [{"event_time": "2025-06"}, ...],
            "modal_records": [{"entity_id": "ENT-0001", "modality": "text", ...}, ...],
        }

    输出：
        {
            "clusters": [EntityCluster, ...],
            "aligned_times": [dict, ...],
            "fused_modal": [dict, ...],
            "report": {"entities_aligned": N, "times_aligned": N, "modalities_fused": N},
        }
    """

    def __init__(
        self,
        entity_aligner: EntityAligner | None = None,
        time_aligner: TimeAligner | None = None,
        modal_aligner: ModalAligner | None = None,
    ) -> None:
        self.entity_aligner = entity_aligner or EntityAligner()
        self.time_aligner = time_aligner or TimeAligner()
        self.modal_aligner = modal_aligner or ModalAligner()

    def align(self, input_data: dict) -> dict:
        """统一对齐流程：实体对齐 → 时间对齐 → 多模态融合。

        Args:
            input_data: 含 entities / time_records / modal_records 键的字典。
                entities 可为 EntityRecord 对象列表或 dict 列表（自动转换）。

        Returns:
            对齐后数据 + 对齐报告。
        """
        raw_entities = list(input_data.get("entities", []))
        # 兼容 dict 列表：自动转换为 EntityRecord
        entity_records: list[EntityRecord] = []
        for e in raw_entities:
            if isinstance(e, EntityRecord):
                entity_records.append(e)
            elif isinstance(e, dict):
                entity_records.append(EntityRecord(
                    entity_id=e.get("entity_id", e.get("name", "")),
                    source=e.get("source", ""),
                    name=e.get("name", ""),
                    uscc=e.get("uscc", ""),
                    aliases=e.get("aliases", []),
                    attributes=e.get("attributes", {}),
                ))
            else:
                continue
        time_records: list[dict] = list(input_data.get("time_records", []))
        modal_records: list[dict] = list(input_data.get("modal_records", []))

        # 1. 实体对齐
        clusters = self.entity_aligner.align(entity_records)
        # 2. 时间对齐
        aligned_times = self.time_aligner.align(time_records)
        # 3. 多模态融合
        fused = self.modal_aligner.align_fusion(modal_records)

        report = {
            "entities_aligned": len(clusters),
            "times_aligned": sum(1 for r in aligned_times if r.get("event_time")),
            "modalities_fused": len(fused),
        }
        return {
            "clusters": clusters,
            "aligned_times": aligned_times,
            "fused_modal": fused,
            "report": report,
        }
