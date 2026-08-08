"""统一模块接口契约框架（强类型升级版）。

定义模块间数据流的输入/输出接口规范，用于组网时确保接口对应关系一致。
每个模块通过 ModuleContract 描述其输入来源和输出消费者。

v1.0: 弱类型契约（fields: list[str]）
v2.0: 强类型契约（TypedField）+ 多模态支持 + schema 版本化 + 编译期校验
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# ======================================================================
# v2.0 强类型字段定义
# ======================================================================

# 支持的数据类型枚举
DTYPES = frozenset({
    "str", "int", "float", "bool", "datetime", "date",
    "embedding",      # 向量嵌入（文本/图像/视频 embedding）
    "blob",            # 二进制引用（图片/视频/音频的对象存储路径 + 哈希）
    "tensor",          # 多维张量（时序信号矩阵）
    "dict", "list",    # 嵌套结构
    "any",             # 动态类型（过渡用）
})

# 支持的数据模态枚举（空字符串表示未指定/纯结构化）
MODALITIES = frozenset({
    "",                # 未指定（纯结构化数据）
    "text",            # 文本（财报、舆情、合同、NLP 输入）
    "image",           # 图片（票据、扫描件、截图）
    "video",           # 视频（会议录像、监控）
    "audio",           # 音频（电话录音）
    "timeseries",      # 时序（行情、流水、传感器）
    "tabular",         # 表格（ERP 明细、台账）
    "graph",           # 图结构（知识图谱、网络）
})

# 支持的接口格式枚举（扩展多模态）
FORMATS = frozenset({
    "json/dict",       # 内存 dict / JSON 文档
    "jsonl",           # 行式 JSON 批量交换
    "parquet",         # 列式存储分区
    "stream",          # 实时流（Kafka/Arrow IPC）
    "graph",           # 图结构（节点/边）
    # v2.0 多模态格式
    "blob_ref",        # 对象存储引用（uri + hash + mime）
    "embedding",       # 向量嵌入（float[] + 模型信息）
    "tensor",          # 多维张量（shape + dtype + 数据）
})


@dataclass
class TypedField:
    """单个字段的强类型规格。

    比 v1.0 的裸字符串字段名多出 dtype/unit/nullable/modality/sample_rate 等元信息，
    使得接口契约可在编译期校验类型兼容性，并支持多模态数据描述。
    """
    name: str                          # 字段名
    dtype: str = "any"                 # 数据类型（见 DTYPES）
    unit: str = ""                     # 单位（元/CNY/秒/像素/...）
    nullable: bool = True              # 是否可空
    modality: str = ""                 # 数据模态（见 MODALITIES）
    sample_rate: str = ""              # 采样率（1d/1h/事件驱动，仅时序用）
    description: str = ""              # 字段说明

    def __post_init__(self):
        if self.dtype not in DTYPES:
            raise ValueError(f"TypedField '{self.name}' dtype 非法: {self.dtype}，合法值: {sorted(DTYPES)}")
        if self.modality not in MODALITIES:
            raise ValueError(f"TypedField '{self.name}' modality 非法: {self.modality}，合法值: {sorted(MODALITIES)}")

    @classmethod
    def from_dict(cls, d: dict) -> "TypedField":
        """从 dict 加载（兼容缺省字段）。"""
        return cls(
            name=d["name"],
            dtype=d.get("dtype", "any"),
            unit=d.get("unit", ""),
            nullable=d.get("nullable", True),
            modality=d.get("modality", ""),
            sample_rate=d.get("sample_rate", ""),
            description=d.get("description", ""),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "dtype": self.dtype, "unit": self.unit,
            "nullable": self.nullable, "modality": self.modality,
            "sample_rate": self.sample_rate, "description": self.description,
        }

    def is_compatible_with(self, other: "TypedField") -> tuple[bool, str]:
        """校验本字段（作为消费者输入）是否能接受 other（作为生产者输出）的字段类型。

        规则：
          - 名称必须一致
          - dtype 兼容：any 接受一切；同类型直接通过；int↔float 数值兼容
          - modality 必须一致（模态不可隐式转换）
          - 若消费者声明 nullable=False，生产者必须 nullable=False
        """
        if self.name != other.name:
            return False, f"字段名不匹配: {self.name} vs {other.name}"
        # dtype 兼容性
        if self.dtype != "any" and other.dtype != "any":
            numeric = {"int", "float"}
            if self.dtype != other.dtype and not (self.dtype in numeric and other.dtype in numeric):
                return False, f"字段 '{self.name}' dtype 不兼容: 需要 {self.dtype}, 实际 {other.dtype}"
        # modality 严格匹配
        if self.modality and other.modality and self.modality != other.modality:
            return False, f"字段 '{self.name}' 模态不兼容: 需要 {self.modality}, 实际 {other.modality}"
        # nullable 约束
        if not self.nullable and other.nullable:
            return False, f"字段 '{self.name}' 消费者要求非空，但生产者可空"
        return True, ""


# ======================================================================
# 接口规格（v1.0 弱类型 + v2.0 强类型共存）
# ======================================================================


@dataclass
class InterfaceSpec:
    """单个接口规格（输入或输出）。

    v1.0 字段保持向后兼容；fields_typed 为 v2.0 强类型字段（与 fields 共存）。
    """
    module: str        # 对端模块 slug（输入时为来源，输出时为消费者）
    data_type: str     # 数据类型名称（如"标准化数据集"）
    format: str        # 数据格式（见 FORMATS）
    description: str   # 接口描述
    fields: list[str]  # v1.0 字段名列表（向后兼容）
    # v2.0 强类型扩展
    fields_typed: list[TypedField] = field(default_factory=list)
    schema_version: str = "1.0"
    schema_hash: str = ""              # 字段结构哈希（编译期校验用）

    def __post_init__(self):
        if self.format not in FORMATS:
            raise ValueError(f"InterfaceSpec format 非法: {self.format}，合法值: {sorted(FORMATS)}")

    @property
    def is_multimodal(self) -> bool:
        """是否为多模态接口（含非空 modality 字段）。"""
        return any(f.modality for f in self.fields_typed)

    @property
    def modalities(self) -> list[str]:
        """本接口涉及的所有模态（去重）。"""
        seen = []
        for f in self.fields_typed:
            if f.modality and f.modality not in seen:
                seen.append(f.modality)
        return seen

    def compute_hash(self) -> str:
        """计算字段结构哈希（用于编译期契约一致性校验）。"""
        import hashlib
        parts = [self.format, self.schema_version]
        for f in self.fields_typed:
            parts.append(f"{f.name}:{f.dtype}:{f.modality}:{f.nullable}")
        raw = "|".join(parts)
        self.schema_hash = hashlib.md5(raw.encode()).hexdigest()[:12]
        return self.schema_hash


@dataclass
class ModuleContract:
    """模块接口契约。"""
    slug: str
    name: str
    inputs: list[InterfaceSpec] = field(default_factory=list)
    outputs: list[InterfaceSpec] = field(default_factory=list)

    @property
    def has_upstream(self) -> bool:
        return len(self.inputs) > 0

    @property
    def has_downstream(self) -> bool:
        return len(self.outputs) > 0

    @property
    def is_terminal(self) -> bool:
        return not self.has_upstream and not self.has_downstream

    @property
    def is_multimodal(self) -> bool:
        """模块是否涉及多模态数据。"""
        return any(i.is_multimodal for i in self.inputs + self.outputs)


# ======================================================================
# 契约加载与编译期校验
# ======================================================================


def _load_interface(d: dict) -> InterfaceSpec:
    """从 JSON dict 加载接口规格，兼容 v1.0/v2.0 schema。"""
    fields_typed = [TypedField.from_dict(fd) for fd in d.get("fields_typed", [])]
    spec = InterfaceSpec(
        module=d["module"],
        data_type=d["data_type"],
        format=d["format"],
        description=d.get("description", ""),
        fields=d.get("fields", []),
        fields_typed=fields_typed,
        schema_version=d.get("schema_version", "1.0" if not fields_typed else "2.0"),
    )
    if fields_typed:
        spec.compute_hash()
    return spec


def load_contracts() -> dict[str, ModuleContract]:
    """从 network_schema.json 加载所有模块契约（兼容 v1.0/v2.0）。"""
    import json
    from pathlib import Path
    schema_path = Path(__file__).parent / "network_schema.json"
    with open(schema_path, encoding="utf-8") as f:
        data = json.load(f)
    contracts = {}
    for slug, m in data["modules"].items():
        contracts[slug] = ModuleContract(
            slug=slug,
            name=m["name"],
            inputs=[_load_interface(i) for i in m.get("inputs", [])],
            outputs=[_load_interface(o) for o in m.get("outputs", [])],
        )
    return contracts


def get_contract(slug: str) -> ModuleContract | None:
    """获取单个模块契约。"""
    return load_contracts().get(slug)


def validate_edge_compatibility(
    producer: ModuleContract,
    consumer: ModuleContract,
    output_idx: int = 0,
    input_idx: int = 0,
) -> tuple[bool, list[str]]:
    """编译期校验：生产者输出接口与消费者输入接口的兼容性。

    校验项：
      1. format 必须一致
      2. 若双方均有 fields_typed，逐字段校验类型/模态/可空性兼容
      3. 若仅 v1.0 fields，校验字段名交集非空
    """
    issues: list[str] = []
    if output_idx >= len(producer.outputs):
        return False, [f"生产者 {producer.slug} 无第 {output_idx} 个输出"]
    if input_idx >= len(consumer.inputs):
        return False, [f"消费者 {consumer.slug} 无第 {input_idx} 个输入"]

    out_spec = producer.outputs[output_idx]
    in_spec = consumer.inputs[input_idx]

    # format 校验
    if out_spec.format != in_spec.format:
        issues.append(f"format 不匹配: 生产者 {out_spec.format} vs 消费者 {in_spec.format}")

    # 强类型校验
    if out_spec.fields_typed and in_spec.fields_typed:
        out_map = {f.name: f for f in out_spec.fields_typed}
        in_map = {f.name: f for f in in_spec.fields_typed}
        for name, in_field in in_map.items():
            if name not in out_map:
                if not in_field.nullable:
                    issues.append(f"字段 '{name}': 消费者要求非空但生产者未提供")
                continue
            ok, msg = in_field.is_compatible_with(out_map[name])
            if not ok:
                issues.append(msg)
    elif out_spec.fields or in_spec.fields:
        # v1.0 兜底：字段名交集
        out_names = set(out_spec.fields)
        in_names = set(in_spec.fields)
        if in_names and out_names and not (in_names & out_names):
            issues.append(f"v1.0 字段名无交集: 生产者 {out_names} vs 消费者 {in_names}")

    return len(issues) == 0, issues
