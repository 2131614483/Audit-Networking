"""[IT-05] pipeline 端到端单测：Pipeline.run() 全流程跑通。

it_05 的 custom_thresholds / custom_rules / format_output 均为 pass-through 骨架，
Pipeline 串联 engine.execute，输出结构等同 engine 结果。
注：difficulty=1 加速测试。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from modules.it_05.pipeline import Pipeline

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _sample() -> list:
    return json.loads((_FIXTURES / "sample_input.json").read_text(encoding="utf-8"))


def _make_pipeline(**overrides) -> Pipeline:
    pipe = Pipeline(config={"difficulty": 1, **overrides})
    pipe.engine.setup()
    return pipe


# ----------------------------------------------------------------------
# 端到端跑通
# ----------------------------------------------------------------------
def test_pipeline_end_to_end_with_sample():
    """用 sample_input.json 端到端跑通，输出含 deposit + certificates。"""
    pipe = _make_pipeline()
    output = pipe.run(_sample())
    assert "deposit" in output
    assert "certificates" in output
    assert output["deposit"]["transaction_count"] == 3
    assert len(output["certificates"]) == 3


def test_pipeline_passes_through_custom_stages():
    """custom_thresholds / custom_rules / format_output 均为 pass-through，
    Pipeline 输出与 engine.execute 输出结构一致。"""
    pipe = _make_pipeline()
    sample = _sample()
    output = pipe.run(sample)
    # 注意：engine 有状态，execute 会追加区块。这里比较结构而非全等
    assert output["deposit"]["transaction_count"] == 3
    assert "block" in output
    assert "chain_status" in output


def test_pipeline_config_propagates_to_engine():
    """Pipeline config 透传到 engine.config。"""
    pipe = Pipeline(config={"difficulty": 1, "custom_key": "value"})
    pipe.engine.setup()
    assert pipe.engine.config.get("custom_key") == "value"
    assert pipe.engine.difficulty == 1


def test_pipeline_verify_after_run():
    """Pipeline 跑完后可 verify_transaction（用 block 内存储的 tx hash）。"""
    pipe = _make_pipeline()
    pipe.run(_sample())
    # 取 block 内存储的第一笔交易字符串的 hash
    tx_in_block = pipe.engine.blocks[-1]["transactions"][0]
    tx_hash = hashlib.sha256(tx_in_block.encode()).hexdigest()
    result = pipe.engine.verify_transaction(tx_hash)
    assert result["found"] is True


def test_pipeline_empty_input_handled():
    """空 list 输入经 Pipeline 后返回 status=empty（不崩）。"""
    pipe = _make_pipeline()
    output = pipe.run([])
    assert output["status"] == "empty"
